from datetime import datetime
from pathlib import Path

from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtCore import QRect, QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QBoxLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QSizePolicy, QTabBar, QTabWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from core import (
    DeviceManager, ExperimentContext, load_device_plugins,
    load_experiment_plugins, storage_dir,
)
from .panel_dashboard import DashboardPanel
from .panel_camera import CameraWorkspace
from .panel_measurement import MeasurementPanels
from .panel_sequence import SequencePanel
from .panel_settings import SettingsPanel
from .plugin_studio import PluginStudioPanel
from .widget_busy_spinner import run_busy_task, visible_busy_dialog
from .layout_mode import apply_panel_layout, validate_layout_mode

__all__ = ["MainWindow"]


class MainWindow(QMainWindow):
    """Main tab workspace with a compact status header."""

    DEFAULT_WINDOW_SIZES = {"landscape": (1360, 800), "portrait": (800, 1360)}

    def __init__(self, theme_manager):
        super().__init__()
        self.theme_manager = theme_manager
        self.setWindowTitle("UOS Lab Manager")
        self.window_settings = QSettings("UOSLabManager", "UOSLabManager")
        self.layout_preference = self.window_settings.value("appearance/layout_mode", "landscape")
        if self.layout_preference not in self.DEFAULT_WINDOW_SIZES:
            self.layout_preference = "landscape"
            self.window_settings.setValue("appearance/layout_mode", self.layout_preference)
        self.resize(*self.DEFAULT_WINDOW_SIZES[self.layout_preference])
        self.layout_mode = "wide"
        self._layout_mode_applied = False
        self._sidebar_preferences = {"wide": True, "compact": False}
        self.manager = DeviceManager()
        self.plugins = load_device_plugins()
        self.experiment_plugins = load_experiment_plugins(strict=False)
        self.device_tabs = {}
        self.device_tab_containers = {}
        self.experiment_tabs = {}
        self.experiment_tab_containers = {}
        self.settings_panel = None
        self._build_ui()

    def _build_ui(self):
        self.measurement = MeasurementPanels(self.manager, self.plugins, self.log)
        self.sequence_panel = SequencePanel(self.manager, self.log, self.plugins)
        default_output_dir = str(storage_dir("camera_recordings"))
        output_dir = self.window_settings.value("camera/output_dir", default_output_dir)
        self.camera_panel = CameraWorkspace(output_dir, self.log)
        self.experiment_context = ExperimentContext(
            self.manager, self.camera_panel, self._resolve_experiment_panel
        )
        self.plugin_studio = PluginStudioPanel(self)
        self.plugin_studio.reload_requested.connect(self.reload_experiment_plugins)

        self.data_workspace = QSplitter(Qt.Orientation.Vertical)
        self.data_workspace.addWidget(self.measurement.graph_widget)
        self.data_workspace.addWidget(self.measurement.table_widget)
        self.data_workspace.setStretchFactor(0, 3)
        self.data_workspace.setStretchFactor(1, 2)
        self.data_workspace.setSizes([420, 280])

        self.sequence_workspace = QWidget()
        sequence_layout = QHBoxLayout(self.sequence_workspace)
        self.sequence_layout = sequence_layout
        sequence_layout.setContentsMargins(4, 4, 4, 4)
        sequence_layout.addWidget(self.sequence_panel, 2)
        sequence_layout.addWidget(self.measurement.log_widget, 1)

        self.dashboard = DashboardPanel(
            self.manager, self.plugins, self.experiment_plugins,
            self.open_device_tab, self.open_experiment,
        )
        self.sequence_panel.set_experiment_plugins(
            self.experiment_plugins,
            self.execute_experiment_sequence_action,
            self.poll_experiment_sequence_action,
            self.cancel_experiment_sequence_action,
        )
        self.sequence_panel.set_common_actions(
            self.set_sequence_recording,
            self.measurement.add_sequence_marker,
            self.sequence_safe_output,
        )

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.update_active_experiment)
        self.tabs.addTab(self.plugin_studio, "Plugin Studio")
        self.tabs.addTab(self.data_workspace, "Data")
        self.tabs.addTab(self.sequence_workspace, "Sequence")
        self.tabs.addTab(self.camera_panel, "Camera")
        self.sequence_panel.running_changed.connect(
            self.update_sequence_tab_state
        )
        self.fixed_tabs = {
            self.plugin_studio, self.data_workspace,
            self.sequence_workspace, self.camera_panel,
        }
        for index, color in enumerate(("#ba68c8", "#4da3ff", "#ffb74d", "#66bb6a")):
            self.tabs.tabBar().setTabTextColor(index, QColor(color))
            self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
            self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        self.tabs.setCurrentWidget(self.plugin_studio)
        central = QWidget()
        # Wide plugin size hints must not prevent a manually selected narrow
        # window. Individual pages can scroll while keeping their controls usable.
        central.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        central.setMinimumWidth(640)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_header())
        self.dashboard.setMaximumHeight(280)
        self.sidebar_open = True
        body = QWidget()
        body_layout = QVBoxLayout(body)
        self.body_layout = body_layout
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.dashboard)
        toggle_strip = QWidget()
        self.sidebar_toggle_strip = toggle_strip
        toggle_strip.setFixedHeight(30)
        toggle_layout = QVBoxLayout(toggle_strip)
        toggle_layout.setContentsMargins(1, 0, 1, 0)
        self.sidebar_toggle_button = QToolButton()
        self.sidebar_toggle_button.setText("▲ 장비 및 실험")
        self.sidebar_toggle_button.setToolTip("Collapse or expand device and experiment plugins")
        self.sidebar_toggle_button.setFixedHeight(28)
        self.sidebar_toggle_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sidebar_toggle_button.setStyleSheet(
            "QToolButton { font-size:9pt; font-weight:bold; border:1px solid #777; "
            "border-radius:3px; background:palette(button); }"
            "QToolButton:hover { background:#4d78a8; color:white; }"
        )
        self.sidebar_toggle_button.clicked.connect(self.toggle_sidebar)
        toggle_layout.addWidget(self.sidebar_toggle_button)
        body_layout.addWidget(toggle_strip)
        self.tab_scroll_area = QScrollArea()
        self.tab_scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.tab_scroll_area.setWidgetResizable(True)
        self.tab_scroll_area.setWidget(self.tabs)
        body_layout.addWidget(self.tab_scroll_area, 1)
        central_layout.addWidget(body, 1)
        self.setCentralWidget(central)
        self.apply_theme_to_panels(self.theme_manager.current_theme)
        self.update_device_status()
        self.restore_window_layout()
        self.update_layout_mode()

    def set_layout_preference(self, preference):
        if preference not in self.DEFAULT_WINDOW_SIZES:
            raise ValueError(f"Unknown layout preference: {preference!r}")
        self.layout_preference = preference
        self.window_settings.setValue("appearance/layout_mode", self.layout_preference)
        if self.settings_panel is not None:
            self.settings_panel.sync_layout_preference(preference)
        self.update_layout_mode()
        self.resize_to_layout_default()

    def update_layout_mode(self):
        self.apply_layout_mode("compact" if self.layout_preference == "portrait" else "wide")

    def resize_to_layout_default(self):
        """Resize once on selection; subsequent user resizes leave the mode alone."""
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        self.resize(*self.DEFAULT_WINDOW_SIZES[self.layout_preference])
        self._fit_window_to_available_screen()

    def _apply_plugin_layout_mode(self, panel):
        handler = getattr(panel, "set_layout_mode", None)
        if callable(handler):
            try:
                handler(self.layout_mode)
            except Exception as error:
                # An optional third-party UI hook must not stop other panels.
                self.log(f"Plugin layout update failed ({type(panel).__name__}): {error}")

    def apply_layout_mode(self, mode):
        validate_layout_mode(mode)
        if self._layout_mode_applied and mode == self.layout_mode:
            return
        self.layout_mode = mode
        compact = mode == "compact"
        self.dashboard.set_layout_mode(mode)
        self.body_layout.setDirection(QBoxLayout.Direction.TopToBottom if compact
                                      else QBoxLayout.Direction.LeftToRight)
        self.sidebar_toggle_strip.setMinimumSize(0, 0)
        self.sidebar_toggle_strip.setMaximumSize(16777215, 16777215)
        self.sidebar_toggle_button.setMinimumSize(0, 0)
        self.sidebar_toggle_button.setMaximumSize(16777215, 16777215)
        if compact:
            self.sidebar_toggle_strip.setFixedHeight(30)
            self.sidebar_toggle_button.setFixedHeight(28)
        else:
            self.sidebar_toggle_strip.setFixedWidth(18)
            self.sidebar_toggle_button.setFixedWidth(16)
        self.sidebar_toggle_button.setSizePolicy(
            QSizePolicy.Policy.Expanding if compact else QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed if compact else QSizePolicy.Policy.Expanding,
        )
        self.sequence_layout.setDirection(
            QBoxLayout.Direction.TopToBottom if compact
            else QBoxLayout.Direction.LeftToRight
        )
        self.set_sidebar_visible(self._sidebar_preferences[mode])
        self.measurement.set_layout_mode(mode)
        for panel in (self.sequence_panel, self.plugin_studio):
            apply_panel_layout(panel, mode)
        if self.settings_panel is not None:
            apply_panel_layout(self.settings_panel, mode)
        self.camera_panel.set_layout_mode(mode)
        for panel in (*self.device_tabs.values(), *self.experiment_tabs.values()):
            self._apply_plugin_layout_mode(panel)
        self._layout_mode_applied = True

    def update_sequence_tab_state(self, running):
        index = self.tabs.indexOf(self.sequence_workspace)
        if index < 0:
            return
        self.tabs.setTabText(
            index, "Sequence (Running)" if running else "Sequence"
        )
        self.tabs.tabBar().setTabTextColor(
            index, QColor("#00e676" if running else "#ffb74d")
        )

    def set_sequence_recording(self, enabled):
        was_recording = self.measurement.recording
        if enabled:
            self.measurement.start()
            self.measurement.record_button.setChecked(True)
            return not was_recording
        if not was_recording:
            return False
        self.measurement.flush_sequence_markers()
        self.measurement.record_button.setChecked(False)
        if not self.measurement.rows:
            return True
        output_dir = Path(
            self.window_settings.value(
                "data/output_dir", str(storage_dir("data"))
            )
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        recipe_name = self.sequence_panel.recipe_label.text().rstrip(" *")
        safe_name = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in recipe_name
        ).strip("_") or "sequence"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"{safe_name}_{timestamp}.csv"
        self.measurement.data_logger.save_csv(
            path, self.measurement.data_logger.columns
        )
        self.log(f"Sequence data saved: {path}")
        return True

    def sequence_safe_output(self):
        errors = []
        for panel in self.experiment_tabs.values():
            if hasattr(panel, "emergency_stop"):
                try:
                    panel.emergency_stop()
                except Exception as error:
                    errors.append(f"experiment: {error}")
        errors.extend(self._device_safe_state_errors())
        if errors:
            raise RuntimeError("; ".join(errors))

    def _device_safe_state_errors(self):
        """Apply safe states declared by connected device plug-ins."""
        errors = []
        for plugin in self.plugins.values():
            if not getattr(plugin, "safe_actions", ()):
                continue
            device = self.manager.get_device(plugin.device_id)
            if device is None:
                continue
            try:
                plugin.enter_safe_state(device)
            except Exception as error:
                errors.append(f"{plugin.display_name}: {error}")
        return errors

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
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self._sidebar_preferences[self.layout_mode] = self.sidebar_open
        self.dashboard.setVisible(self.sidebar_open)
        self.sidebar_toggle_button.setText(
            ("▲ 장비 및 실험" if self.sidebar_open else "▼ 장비 및 실험")
            if self.layout_mode == "compact" else ("◀" if self.sidebar_open else "▶")
        )

    def open_settings_tab(self, _checked=False):
        if self.settings_panel is None:
            self.settings_panel = SettingsPanel(
                self.theme_manager, self.apply_theme_to_panels, self,
                camera_workspace=self.camera_panel,
                layout_preference=self.layout_preference,
                layout_changed=self.set_layout_preference,
            )
            apply_panel_layout(self.settings_panel, self.layout_mode)
            self.tabs.addTab(self.settings_panel, "Settings")
        self.tabs.setCurrentWidget(self.settings_panel)

    def open_device_tab(self, device_id):
        plugin = self.plugins[device_id]
        panel = self.device_tabs.get(device_id)
        if panel is None:
            if plugin.settings_factory is None:
                return
            try:
                with visible_busy_dialog(self):
                    panel = plugin.settings_factory(self.manager, self)
            except Exception as error:
                QMessageBox.critical(
                    self, "Device plugin failed",
                    f"Could not open {plugin.display_name}:\n\n{error}",
                )
                return
            self.device_tabs[device_id] = panel
            self._apply_plugin_layout_mode(panel)
            container = QScrollArea()
            container.setWidgetResizable(True)
            container.setWidget(panel)
            self.device_tab_containers[device_id] = container
            self.tabs.addTab(container, f"{plugin.display_name} Settings")
        if hasattr(panel, "sync_connection_status"):
            panel.sync_connection_status()
        self.tabs.setCurrentWidget(self.device_tab_containers[device_id])

    def _resolve_experiment_panel(self, experiment_id, *, create=False):
        panel = self.experiment_tabs.get(experiment_id)
        if panel is None and create:
            if experiment_id not in self.experiment_plugins:
                return None
            self.open_experiment(experiment_id)
            panel = self.experiment_tabs.get(experiment_id)
        return panel

    def open_experiment(self, experiment_id):
        plugin = self.experiment_plugins[experiment_id]
        if plugin.panel_factory is not None:
            panel = self.experiment_tabs.get(experiment_id)
            if panel is None:
                try:
                    with visible_busy_dialog(self):
                        panel = plugin.panel_factory(self.experiment_context, self)
                except Exception as error:
                    message = (
                        f"Could not open {plugin.display_name}:\n\n{error}"
                    )
                    QMessageBox.critical(self, "Experiment plugin failed", message)
                    self.plugin_studio.codex_panel.set_activity(message)
                    self.log(message.replace("\n", " "))
                    return
                self.experiment_tabs[experiment_id] = panel
                self._apply_plugin_layout_mode(panel)
                container = QScrollArea()
                container.setWidgetResizable(True)
                container.setWidget(panel)
                self.experiment_tab_containers[experiment_id] = container
                self.tabs.addTab(container, plugin.display_name)
            if hasattr(panel, "sync_connection_status"):
                panel.sync_connection_status()
            self.tabs.setCurrentWidget(self.experiment_tab_containers[experiment_id])
            return
        if self.sequence_panel.load_experiment(plugin):
            self.tabs.setCurrentWidget(self.sequence_workspace)

    def reload_experiment_plugins(self):
        if self.sequence_panel.is_running:
            QMessageBox.warning(
                self, "Plugin Studio",
                "Stop the running sequence before reloading plugins.",
            )
            return
        if self.experiment_tabs:
            QMessageBox.warning(
                self, "Plugin Studio",
                "Close all open experiment tabs before reloading plugins.",
            )
            return
        if self.manager.devices or self.device_tabs:
            QMessageBox.warning(
                self, "Plugin Studio",
                "Disconnect all devices and close all device settings tabs before "
                "reloading device plugins.",
            )
            return
        run_busy_task(
            self,
            lambda: (
                load_experiment_plugins(),
                load_device_plugins(reload_modules=True),
            ),
            self._plugins_reloaded,
            self._plugin_reload_failed,
            key="plugin_reload",
        )

    def _plugin_reload_failed(self, error):
        QMessageBox.critical(self, "Plugin reload failed", str(error))
        self.plugin_studio.codex_panel.set_activity(f"Reload failed:\n{error}")

    def _plugins_reloaded(self, result):
        experiment_plugins, device_plugins = result
        self.experiment_plugins = experiment_plugins
        self.plugins = device_plugins
        self.measurement.set_plugins(device_plugins)
        self.dashboard.set_experiment_plugins(experiment_plugins)
        self.dashboard.set_device_plugins(device_plugins)
        self.sequence_panel.set_device_plugins(device_plugins)
        self.sequence_panel.set_experiment_plugins(experiment_plugins)
        self.plugin_studio.codex_panel.set_activity(
            f"Reloaded {len(experiment_plugins)} experiment plugins and "
            f"{len(device_plugins)} device plugins. Restart the application if a "
            "device plugin changed its measurement columns."
        )
        self.log(
            f"Reloaded {len(experiment_plugins)} experiment plugins and "
            f"{len(device_plugins)} device plugins"
        )

    def _experiment_panel_for_sequence(self, step, create=False):
        experiment_id = step["dev"].partition(":")[2]
        panel = self.experiment_tabs.get(experiment_id)
        if panel is None and create:
            plugin = self.experiment_plugins.get(experiment_id)
            if plugin is None or plugin.panel_factory is None:
                raise RuntimeError(f"Experiment panel is unavailable: {experiment_id}")
            self.open_experiment(experiment_id)
            panel = self.experiment_tabs.get(experiment_id)
        if panel is None:
            raise RuntimeError(f"Experiment panel is unavailable: {experiment_id}")
        return panel

    def execute_experiment_sequence_action(self, step):
        panel = self._experiment_panel_for_sequence(step, create=True)
        handler = getattr(panel, "execute_sequence_command", None)
        if handler is None:
            raise RuntimeError("This experiment does not implement sequence commands")
        return bool(handler(step["cmd"], step["val"]))

    def poll_experiment_sequence_action(self, step):
        panel = self._experiment_panel_for_sequence(step)
        handler = getattr(panel, "is_sequence_command_complete", None)
        if handler is None:
            raise RuntimeError("This experiment cannot report sequence progress")
        return bool(handler(step["cmd"], step["val"]))

    def cancel_experiment_sequence_action(self, step):
        panel = self._experiment_panel_for_sequence(step)
        handler = getattr(panel, "cancel_sequence_command", None)
        if handler is not None:
            handler()

    def update_active_experiment(self, _index=None):
        if not hasattr(self, "dashboard") or not hasattr(self, "tabs"):
            return
        current = self.tabs.currentWidget()
        active_id = next((experiment_id for experiment_id, container
                          in self.experiment_tab_containers.items() if container is current), None)
        active_panel = self.experiment_tabs.get(active_id)
        previous_panel = getattr(self, "_active_experiment_panel", None)
        if previous_panel is not None and previous_panel is not active_panel:
            deactivate = getattr(previous_panel, "deactivate", None)
            if deactivate is not None:
                deactivate()
        self._active_experiment_panel = active_panel
        if active_panel is not None and active_panel is not previous_panel:
            activate = getattr(active_panel, "activate", None)
            if activate is not None:
                activate()
        elif current is self.camera_panel:
            self.camera_panel.show_camera_workspace()
        self.dashboard.set_active_experiment(active_id)

    def close_tab(self, index):
        container = self.tabs.widget(index)
        if container is None or container in self.fixed_tabs:
            return
        self.tabs.removeTab(index)
        if container is self.settings_panel:
            self.settings_panel.deleteLater()
            self.settings_panel = None
            return
        for device_id, opened_container in list(self.device_tab_containers.items()):
            if opened_container is container:
                panel = self.device_tabs.pop(device_id)
                del self.device_tab_containers[device_id]
                if hasattr(panel, "shutdown"):
                    panel.shutdown()
                panel.deleteLater()
                container.deleteLater()
                return
        for experiment_id, opened_container in list(self.experiment_tab_containers.items()):
            if opened_container is container:
                panel = self.experiment_tabs.pop(experiment_id)
                del self.experiment_tab_containers[experiment_id]
                if hasattr(panel, "shutdown"):
                    panel.shutdown()
                panel.deleteLater()
                container.deleteLater()
                return

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
        for panel in self.experiment_tabs.values():
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
        for panel in self.device_tabs.values():
            if hasattr(panel, "stop_video"):
                panel.stop_video()
        for panel in self.experiment_tabs.values():
            if hasattr(panel, "emergency_stop"):
                try:
                    panel.emergency_stop()
                except Exception as error:
                    self.log(f"Emergency stop warning (experiment): {error}")
        for error in self._device_safe_state_errors():
            self.log(f"Emergency stop warning ({error})")
        self.manager.close_all()
        self.update_device_status()
        self.log("EMERGENCY STOP ACTIVATED")

    def closeEvent(self, event):
        if not self.plugin_studio.maybe_discard_changes():
            event.ignore()
            return
        self.plugin_studio.shutdown()
        self.clock_timer.stop()
        self.measurement.timer.stop()
        self.sequence_panel.shutdown()
        self.dashboard.refresh_timer.stop()
        self.save_window_layout()
        self.camera_panel.stop_preview()
        for panel in self.device_tabs.values():
            if hasattr(panel, "shutdown"):
                panel.shutdown()
        for panel in self.experiment_tabs.values():
            if hasattr(panel, "shutdown"):
                panel.shutdown()
        self.disconnect_all()
        event.accept()

    def save_window_layout(self):
        self.window_settings.setValue("window/geometry", self.saveGeometry())
        self.window_settings.setValue("splitter/data", self.data_workspace.saveState())
        self.window_settings.setValue("splitter/graphs", self.measurement.graph_splitter.saveState())
        self.window_settings.setValue("splitter/cameras", self.camera_panel.splitter.saveState())
        for name, splitter in (("graphs", self.measurement.graph_splitter),
                               ("cameras", self.camera_panel.splitter)):
            for mode, sizes in splitter.mode_sizes().items():
                self.window_settings.setValue(f"splitter/{name}/{mode}_sizes", sizes)
        self.window_settings.setValue("data/split_graph", self.measurement.split_graph_button.isChecked())
        self.window_settings.setValue("camera/split_view", self.camera_panel.split_button.isChecked())
        self.window_settings.setValue("sidebar/open", self._sidebar_preferences["wide"])
        self.window_settings.setValue("sidebar/compact_open", self._sidebar_preferences["compact"])

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
        for name, splitter in (("graphs", self.measurement.graph_splitter),
                               ("cameras", self.camera_panel.splitter)):
            for mode in ("wide", "compact"):
                sizes = self.window_settings.value(f"splitter/{name}/{mode}_sizes")
                if sizes is not None:
                    splitter.restore_mode_sizes(mode, sizes)
        sidebar_open = self.window_settings.value("sidebar/open", True, type=bool)
        self._sidebar_preferences["compact"] = self.window_settings.value(
            "sidebar/compact_open", False, type=bool,
        )
        self.set_sidebar_visible(sidebar_open)
        split_graph = self.window_settings.value("data/split_graph", False, type=bool)
        self.measurement.split_graph_button.setChecked(split_graph)
        split_camera = self.window_settings.value("camera/split_view", False, type=bool)
        self.camera_panel.split_button.setChecked(split_camera)
        self._fit_window_to_available_screen()

    @staticmethod
    def bounded_window_geometry(rect, available, minimum_width=1000,
                                minimum_height=640):
        """Return a window rectangle fully contained in a screen work area."""
        width = min(
            max(int(minimum_width), rect.width()),
            available.width(),
        )
        height = min(
            max(int(minimum_height), rect.height()),
            available.height(),
        )
        maximum_x = available.right() - width + 1
        maximum_y = available.bottom() - height + 1
        x = min(max(rect.x(), available.left()), maximum_x)
        y = min(max(rect.y(), available.top()), maximum_y)
        return QRect(x, y, width, height)

    def _fit_window_to_available_screen(self):
        """Clamp restored geometry after monitor or DPI configuration changes."""
        screens = QGuiApplication.screens()
        if not screens:
            return
        rect = self.geometry()
        screen = QGuiApplication.screenAt(rect.center())
        if screen is None:
            def overlap_area(candidate):
                intersection = rect.intersected(candidate.availableGeometry())
                return intersection.width() * intersection.height()

            screen = max(screens, key=overlap_area)
            if overlap_area(screen) <= 0:
                screen = QGuiApplication.primaryScreen()
        frame = self.frameGeometry()
        available = screen.availableGeometry().adjusted(
            max(0, rect.left() - frame.left()), max(0, rect.top() - frame.top()),
            -max(0, frame.right() - rect.right()), -max(0, frame.bottom() - rect.bottom()),
        )
        bounded = self.bounded_window_geometry(
            rect, available,
            minimum_width=1000 if self.layout_preference == "landscape" else 640,
        )
        if bounded != rect:
            self.setGeometry(bounded)
