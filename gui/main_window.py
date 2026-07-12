import os
from datetime import datetime

from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QScrollArea, QSplitter, QTabWidget, QToolBar

from core import DeviceManager, load_device_plugins
from .panel_dashboard import DashboardPanel
from .panel_camera import CameraPanel
from .panel_measurement import MeasurementPanels
from .panel_sequence import SequencePanel
from .panel_settings import SettingsPanel

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """Main tab workspace with device settings opened from the toolbar."""

    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager
        self.setWindowTitle("UOS Lab Manager")
        self.resize(1120, 720)
        self.manager = DeviceManager()
        self.plugins = load_device_plugins()
        self.device_tabs = {}
        self.device_tab_containers = {}
        self.settings_panel = None
        self._build_ui()

    def _build_ui(self):
        self.measurement = MeasurementPanels(self.manager, self.plugins, self.log)
        self.sequence_panel = SequencePanel(self.manager, self.log)
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "camera_recordings")
        self.camera_panel = CameraPanel(output_dir, self.log)

        experiment_left = QSplitter(Qt.Orientation.Vertical)
        experiment_left.addWidget(self.sequence_panel)
        experiment_left.addWidget(self.measurement.log_widget)
        experiment_left.setStretchFactor(0, 3)
        experiment_left.setStretchFactor(1, 2)
        experiment_left.setSizes([400, 240])

        experiment_right = QSplitter(Qt.Orientation.Vertical)
        experiment_right.addWidget(self.measurement.graph_widget)
        experiment_right.addWidget(self.measurement.table_widget)
        experiment_right.setStretchFactor(0, 3)
        experiment_right.setStretchFactor(1, 3)
        experiment_right.setSizes([340, 300])

        self.experiment_workspace = QSplitter(Qt.Orientation.Horizontal)
        self.experiment_workspace.addWidget(experiment_left)
        self.experiment_workspace.addWidget(experiment_right)
        self.experiment_workspace.setStretchFactor(0, 1)
        self.experiment_workspace.setStretchFactor(1, 6)
        self.experiment_workspace.setSizes([330, 740])
        self.dashboard = DashboardPanel(
            self.manager, self.plugins, self.measurement, self.open_device_tab,
            self.emergency_stop,
        )

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.addTab(self.dashboard, "Main")
        self.tabs.addTab(self.experiment_workspace, "Experiment")
        self.tabs.addTab(self.camera_panel, "Camera")
        self.setCentralWidget(self.tabs)
        self._create_toolbar()
        self.apply_theme_to_panels(self.theme_manager.current_theme)
        self.update_device_status()

    def _create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        main_action = QAction("MAIN", self)
        main_action.triggered.connect(lambda _: self.tabs.setCurrentIndex(0))
        toolbar.addAction(main_action)
        experiment_action = QAction("EXPERIMENT", self)
        experiment_action.triggered.connect(lambda _: self.tabs.setCurrentIndex(1))
        toolbar.addAction(experiment_action)
        camera_action = QAction("CAMERA", self)
        camera_action.triggered.connect(lambda _: self.tabs.setCurrentIndex(2))
        toolbar.addAction(camera_action)

        settings_action = QAction("SETTINGS", self)
        settings_action.triggered.connect(self.open_settings_tab)
        toolbar.addAction(settings_action)

        toolbar.addSeparator()
        for device_id, plugin in self.plugins.items():
            action = QAction(plugin.display_name, self)
            action.setToolTip(f"Open {plugin.display_name} settings")
            action.triggered.connect(lambda _, key=device_id: self.open_device_tab(key))
            toolbar.addAction(action)

        toolbar.addSeparator()
        stop = QAction("DISCONNECT ALL", self)
        stop.triggered.connect(self.disconnect_all)
        toolbar.addAction(stop)
        exit_action = QAction("EXIT", self)
        exit_action.triggered.connect(self.close)
        toolbar.addAction(exit_action)

    def open_settings_tab(self, _checked=False):
        if self.settings_panel is None:
            self.settings_panel = SettingsPanel(
                self.theme_manager, self.apply_theme_to_panels, self
            )
            index = self.tabs.addTab(self.settings_panel, "Settings")
        else:
            index = self.tabs.indexOf(self.settings_panel)
        self.tabs.setCurrentIndex(index)

    def open_device_tab(self, device_id):
        plugin = self.plugins[device_id]
        panel = self.device_tabs.get(device_id)
        if panel is None:
            if plugin.settings_factory is None:
                return
            panel = plugin.settings_factory(self.manager, self)
            self.device_tabs[device_id] = panel
            container = QScrollArea()
            container.setWidgetResizable(True)
            container.setWidget(panel)
            self.device_tab_containers[device_id] = container
            index = self.tabs.addTab(container, f"{plugin.display_name} Settings")
        else:
            index = self.tabs.indexOf(self.device_tab_containers[device_id])
        if hasattr(panel, "sync_connection_status"):
            panel.sync_connection_status()
        self.tabs.setCurrentIndex(index)

    def close_tab(self, index):
        if index < 3:
            return
        container = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if container is self.settings_panel:
            self.settings_panel.deleteLater()
            self.settings_panel = None
            return
        for device_id, opened_container in list(self.device_tab_containers.items()):
            if opened_container is container:
                panel = self.device_tabs.pop(device_id)
                del self.device_tab_containers[device_id]
                panel.deleteLater()
                container.deleteLater()
                break

    def log(self, message):
        if hasattr(self.measurement, "log_box"):
            stamp = datetime.now().strftime("%H:%M:%S")
            self.measurement.log_box.append(f"[{stamp}] {message}")
        if hasattr(self, "dashboard"):
            self.dashboard.append_log(message)

    def apply_theme_to_panels(self, theme):
        self.measurement.set_theme(theme)
        self.dashboard.set_theme(theme)

    def update_device_status(self):
        self.measurement.sync_columns()
        if hasattr(self, "dashboard"):
            self.dashboard.refresh_devices()
        for panel in self.device_tabs.values():
            if hasattr(panel, "sync_connection_status"):
                panel.sync_connection_status()
        if self.manager.devices:
            self.measurement.start()
        else:
            self.measurement.stop_if_empty()

    def disconnect_all(self):
        self.measurement.timer.stop()
        self.manager.close_all()
        self.update_device_status()
        self.log("All devices disconnected")

    def emergency_stop(self, _checked=False):
        self.measurement.timer.stop()
        if self.sequence_panel.is_running:
            self.sequence_panel.finish_seq("Emergency stop activated.")
        self.camera_panel.stop_preview()
        for device_id, stop_method in (
            ("LS331", "heater_off"), ("K2400", "output_off"), ("ZUP", "output_off")
        ):
            device = self.manager.get_device(device_id)
            if device is not None:
                try:
                    getattr(device, stop_method)()
                except Exception as error:
                    self.log(f"Emergency stop warning ({device_id}): {error}")
        self.manager.close_all()
        self.update_device_status()
        self.log("EMERGENCY STOP ACTIVATED")

    def closeEvent(self, event):
        self.camera_panel.stop_preview()
        self.disconnect_all()
        event.accept()
