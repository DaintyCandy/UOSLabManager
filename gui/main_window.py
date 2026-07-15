import os
from datetime import datetime

from PyQt6.QtGui import QColor
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QScrollArea, QSplitter,
    QSizePolicy, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from core import DeviceManager, load_device_plugins
from .panel_dashboard import DashboardPanel
from .panel_camera import CameraWorkspace
from .panel_measurement import MeasurementPanels
from .panel_sequence import SequencePanel
from .panel_settings import SettingsPanel

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """Main tab workspace with a compact status header."""

    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager
        self.setWindowTitle("UOS Lab Manager")
        self.resize(1360, 800)
        self.window_settings = QSettings("UOSLabManager", "UOSLabManager")
        self.manager = DeviceManager()
        self.plugins = load_device_plugins()
        self.device_tabs = {}
        self.device_tab_containers = {}
        self.settings_panel = None
        self._build_ui()

    def _build_ui(self):
        self.measurement = MeasurementPanels(self.manager, self.plugins, self.log)
        self.sequence_panel = SequencePanel(self.manager, self.log)
        default_output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "camera_recordings")
        output_dir = self.window_settings.value("camera/output_dir", default_output_dir)
        self.camera_panel = CameraWorkspace(output_dir, self.log)

        self.data_workspace = QSplitter(Qt.Orientation.Vertical)
        self.data_workspace.addWidget(self.measurement.graph_widget)
        self.data_workspace.addWidget(self.measurement.table_widget)
        self.data_workspace.setStretchFactor(0, 3)
        self.data_workspace.setStretchFactor(1, 2)
        self.data_workspace.setSizes([420, 280])

        self.sequence_workspace = QWidget()
        sequence_layout = QHBoxLayout(self.sequence_workspace)
        sequence_layout.setContentsMargins(4, 4, 4, 4)
        sequence_layout.addWidget(self.sequence_panel, 2)
        sequence_layout.addWidget(self.measurement.log_widget, 1)
        output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "camera_recordings")
        self.camera_panel = CameraPanel(output_dir, self.log)
        self.measurement.get_rheed_profile = self.camera_panel.get_latest_profile

        experiment_left = QSplitter(Qt.Orientation.Vertical)
        experiment_left.addWidget(self.sequence_panel)
        experiment_left.addWidget(self.measurement.log_widget)
        experiment_left.setStretchFactor(0, 4)
        experiment_left.setStretchFactor(1, 1)

        experiment_right = QSplitter(Qt.Orientation.Vertical)
        experiment_right.addWidget(self.measurement.graph_widget)
        experiment_right.addWidget(self.measurement.table_widget)
        experiment_right.setStretchFactor(0, 3)
        experiment_right.setStretchFactor(1, 2)

        self.experiment_workspace = QSplitter(Qt.Orientation.Horizontal)
        self.experiment_workspace.addWidget(experiment_left)
        self.experiment_workspace.addWidget(experiment_right)
        self.experiment_workspace.setStretchFactor(0, 2)
        self.experiment_workspace.setStretchFactor(1, 5)
        self.dashboard = DashboardPanel(
            self.manager, self.plugins, self.measurement, self.open_device_tab,
            self.emergency_stop,
        )

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.addTab(self.data_workspace, "Data")
        self.tabs.addTab(self.sequence_workspace, "Sequence")
        self.tabs.addTab(self.camera_panel, "Camera")
        for index, color in enumerate(("#4da3ff", "#ffb74d", "#66bb6a")):
            self.tabs.tabBar().setTabTextColor(index, QColor(color))
            self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
            self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        self.tabs.setCurrentIndex(0)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_header())
        self.dashboard.setFixedWidth(240)
        self.sidebar_open = True
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.dashboard)
        toggle_strip = QWidget()
        toggle_strip.setFixedWidth(18)
        toggle_layout = QVBoxLayout(toggle_strip)
        toggle_layout.setContentsMargins(1, 0, 1, 0)
        self.sidebar_toggle_button = QToolButton()
        self.sidebar_toggle_button.setText("◀")
        self.sidebar_toggle_button.setToolTip("Collapse or expand the device panel")
        self.sidebar_toggle_button.setFixedWidth(16)
        self.sidebar_toggle_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.sidebar_toggle_button.setStyleSheet(
            "QToolButton { font-size:9pt; font-weight:bold; border:1px solid #777; "
            "border-radius:3px; background:palette(button); }"
            "QToolButton:hover { background:#4d78a8; color:white; }"
        )
        self.sidebar_toggle_button.clicked.connect(self.toggle_sidebar)
        toggle_layout.addWidget(self.sidebar_toggle_button)
        body_layout.addWidget(toggle_strip)
        body_layout.addWidget(self.tabs, 1)
        central_layout.addWidget(body, 1)
        self.setCentralWidget(central)
        self.apply_theme_to_panels(self.theme_manager.current_theme)
        self.update_device_status()
        self.restore_window_layout()

    def _build_header(self):
        header = QWidget()
        header.setObjectName("mainHeader")
        header.setFixedHeight(46)
        header.setStyleSheet("#mainHeader { border-bottom: 1px solid #666; }")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 5, 8, 5)
        left_slot = QWidget()
        left_slot.setFixedWidth(110)
        left_layout = QHBoxLayout(left_slot)
        left_layout.setContentsMargins(0, 0, 0, 0)
        settings = QPushButton("⚙")
        settings.setToolTip("Settings")
        settings.setFixedSize(36, 34)
        settings.setStyleSheet("font-size:14pt; font-weight:bold;")
        settings.clicked.connect(self.open_settings_tab)
        left_layout.addWidget(settings)
        left_layout.addStretch()
        layout.addWidget(left_slot)
        layout.addStretch()
        self.clock_label = QLabel()
        self.clock_label.setStyleSheet("font-size:12pt; font-weight:600;")
        layout.addWidget(self.clock_label)
        layout.addStretch()
        stop = QPushButton("STOP")
        stop.setToolTip("Emergency stop and disconnect all devices")
        stop.setFixedSize(110, 34)
        stop.setStyleSheet(
            "QPushButton { background:#c62828; color:white; font-size:12pt; "
            "font-weight:900; border:2px solid #ff8a80; border-radius:6px; }"
            "QPushButton:hover { background:#e53935; }"
            "QPushButton:pressed { background:#8e0000; }"
        )
        stop.clicked.connect(self.emergency_stop)
        layout.addWidget(stop)
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start()
        self.update_clock()
        return header

    def update_clock(self):
        self.clock_label.setText(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    def toggle_sidebar(self, _checked=False):
        self.set_sidebar_visible(not self.sidebar_open)

    def set_sidebar_visible(self, visible):
        self.sidebar_open = bool(visible)
        self.dashboard.setVisible(self.sidebar_open)
        self.sidebar_toggle_button.setText("◀" if self.sidebar_open else "▶")

    def open_settings_tab(self, _checked=False):
        if self.settings_panel is None:
            self.settings_panel = SettingsPanel(
                self.theme_manager, self.apply_theme_to_panels, self,
                camera_workspace=self.camera_panel,
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
        self.save_window_layout()
        self.camera_panel.stop_preview()
        self.disconnect_all()
        event.accept()

    def save_window_layout(self):
        self.window_settings.setValue("window/geometry", self.saveGeometry())
        self.window_settings.setValue("splitter/data", self.data_workspace.saveState())
        self.window_settings.setValue("splitter/graphs", self.measurement.graph_splitter.saveState())
        self.window_settings.setValue("splitter/cameras", self.camera_panel.splitter.saveState())
        self.window_settings.setValue("data/split_graph", self.measurement.split_graph_button.isChecked())
        self.window_settings.setValue("camera/split_view", self.camera_panel.split_button.isChecked())
        self.window_settings.setValue("sidebar/open", self.sidebar_open)

    def restore_window_layout(self):
        geometry = self.window_settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        for key, splitter in (
            ("splitter/data", self.data_workspace),
            ("splitter/graphs", self.measurement.graph_splitter),
            ("splitter/cameras", self.camera_panel.splitter),
        ):
            state = self.window_settings.value(key)
            if state is not None:
                splitter.restoreState(state)
        sidebar_open = self.window_settings.value("sidebar/open", True, type=bool)
        self.set_sidebar_visible(sidebar_open)
        split_graph = self.window_settings.value("data/split_graph", False, type=bool)
        self.measurement.split_graph_button.setChecked(split_graph)
        split_camera = self.window_settings.value("camera/split_view", False, type=bool)
        self.camera_panel.split_button.setChecked(split_camera)
