"""Portrait layout regression tests; no hardware or Codex sign-in is started."""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import (
    QApplication, QBoxLayout, QComboBox, QLabel, QMenuBar, QScrollArea, QWidget,
)

from core import DeviceManager, ExperimentContext
from gui.layout_mode import (
    AdaptiveGridLayout, AdaptiveRowLayout, AdaptiveSplitter,
)
from gui.main_window import MainWindow
from gui.panel_camera import CameraWorkspace
from gui.plugin_studio.codex_panel import CodexPanel
from plugins.devices.ctvideo_3m.plugin import plugin as ctvideo
from plugins.devices.gpd3303s.plugin import plugin as gpd
from plugins.devices.keithley2400.plugin import plugin as keithley
from plugins.devices.lakeshore331.plugin import plugin as lakeshore
from plugins.devices.zup36_12.plugin import plugin as zup
from plugins.devices.zup36_6.plugin import plugin as standard
from plugins.experiments.MBE1.plugin import plugin as mbe
from plugins.experiments.heating_control.plugin import plugin as heating
from plugins.experiments.line_profile.plugin import plugin as line_profile


class LayoutModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = QSettings(
            str(Path(self.temp.name) / "window.ini"), QSettings.Format.IniFormat,
        )
        self.patchers = [
            patch("gui.main_window.QSettings", return_value=self.settings),
            patch("gui.panel_settings.QSettings", return_value=self.settings),
            patch("gui.main_window.load_device_plugins", return_value={}),
            patch("gui.main_window.load_experiment_plugins", return_value={}),
            patch.object(MainWindow, "_fit_window_to_available_screen"),
            patch.object(CodexPanel, "refresh_auth"),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.theme = SimpleNamespace(
            current_theme="dark", THEMES={"Dark": "dark", "Light": "light"},
            display_name=lambda: "Dark",
        )
        self.window = MainWindow(self.theme)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_only_manual_modes_are_available(self):
        self.assertEqual(self.window.layout_preference, "landscape")
        self.window.open_settings_tab()
        combo = self.window.settings_panel.layout_mode_combo
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], ["landscape", "portrait"])
        with self.assertRaises(ValueError):
            self.window.set_layout_preference("auto")

    def test_clock_is_centered_in_the_header_at_both_window_sizes(self):
        window = self.window
        window.show()
        for preference in ("landscape", "portrait"):
            window.set_layout_preference(preference)
            self.app.processEvents()
            header = window.findChild(QWidget, "mainHeader")
            center = window.clock_label.geometry().center().x()
            self.assertAlmostEqual(center, header.rect().center().x(), delta=1)

    def test_selection_resizes_once_and_layout_updates_do_not_reset_size(self):
        window = self.window
        for preference, mode in (("portrait", "compact"), ("landscape", "wide")):
            window.set_layout_preference(preference)
            self.assertEqual((window.width(), window.height()), window.DEFAULT_WINDOW_SIZES[preference])
            self.assertEqual(window.layout_mode, mode)
            window.resize(1000, 1000)
            window.update_layout_mode()
            self.assertEqual((window.width(), window.height()), (1000, 1000))

    def test_legacy_auto_preference_migrates_to_landscape(self):
        self.window.close()
        self.window.deleteLater()
        self.settings.setValue("appearance/layout_mode", "auto")
        self.window = MainWindow(self.theme)
        self.assertEqual(self.window.layout_preference, "landscape")
        self.assertEqual(self.window.layout_mode, "wide")
        self.assertEqual(self.settings.value("appearance/layout_mode"), "landscape")

    def test_host_reflows_and_preserves_split_and_recording_state(self):
        window = self.window
        window.measurement.split_graph_button.setChecked(True)
        window.camera_panel.split_button.setChecked(True)
        window.measurement.record_button.setChecked(True)
        old_plot = window.measurement.plot
        old_camera = window.camera_panel.primary
        window.apply_layout_mode("compact")
        self.assertEqual(window.sequence_layout.direction(), QBoxLayout.Direction.TopToBottom)
        self.assertFalse(window.sidebar_open)
        for splitter in (window.measurement.graph_splitter, window.camera_panel.splitter):
            self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(window.measurement.graph_panes[0].minimumWidth(), 0)
        window.toggle_sidebar()
        self.assertTrue(window.sidebar_open)
        self.assertEqual(window.dashboard.maximumHeight(), 280)
        window.apply_layout_mode("wide")
        self.assertTrue(window.sidebar_open)
        self.assertEqual(window.sequence_layout.direction(), QBoxLayout.Direction.LeftToRight)
        self.assertEqual(window.measurement.graph_panes[0].minimumWidth(), 420)
        window.apply_layout_mode("compact")
        self.assertTrue(window.sidebar_open)
        self.assertIs(window.measurement.plot, old_plot)
        self.assertIs(window.camera_panel.primary, old_camera)
        self.assertTrue(window.measurement.recording)
        self.assertTrue(window.camera_panel.split_button.isChecked())
        # Toggling split view after changing mode must not restore wide minima.
        window.measurement.split_graph_button.setChecked(False)
        window.measurement.split_graph_button.setChecked(True)
        window.camera_panel.split_button.setChecked(False)
        window.camera_panel.split_button.setChecked(True)
        self.assertEqual(window.camera_panel.primary.minimumWidth(), 0)
        self.assertEqual(window.measurement.graph_panes[0].minimumWidth(), 0)

    def test_preference_and_separate_sidebar_preferences_are_persisted(self):
        window = self.window
        window.set_layout_preference("portrait")
        self.assertEqual(window.layout_mode, "compact")
        window.save_window_layout()
        self.assertEqual(self.settings.value("appearance/layout_mode"), "portrait")
        self.assertTrue(self.settings.value("sidebar/open", type=bool))
        self.assertFalse(self.settings.value("sidebar/compact_open", type=bool))

    def test_navigation_switches_between_side_and_top(self):
        window = self.window
        window.set_layout_preference("landscape")
        self.assertEqual(window.body_layout.direction(), QBoxLayout.Direction.LeftToRight)
        self.assertEqual(window.dashboard.maximumWidth(), 240)
        self.assertEqual(window.sidebar_toggle_strip.width(), 18)
        window.set_layout_preference("portrait")
        self.assertEqual(window.body_layout.direction(), QBoxLayout.Direction.TopToBottom)
        self.assertEqual(window.dashboard.maximumHeight(), 280)
        self.assertEqual(window.sidebar_toggle_strip.height(), 30)

    def test_device_tab_reopens_and_closes_without_recreating_panel(self):
        window = self.window
        window.set_layout_preference("portrait")
        factory = Mock(side_effect=lambda _manager, parent: QWidget(parent))
        window.plugins["device"] = SimpleNamespace(settings_factory=factory, display_name="Test Device")
        window.open_device_tab("device")
        panel = window.device_tabs["device"]
        panel.shutdown = Mock()
        container = window.device_tab_containers["device"]
        window.open_device_tab("device")
        self.assertIs(window.device_tabs["device"], panel)
        factory.assert_called_once()
        self.assertIs(window.tabs.currentWidget(), container)
        window.close_tab(window.tabs.indexOf(container))
        panel.shutdown.assert_called_once()
        self.assertNotIn("device", window.device_tabs)
        self.assertFalse(hasattr(window, "bottom_tabs"))
        self.assertFalse(hasattr(window, "tab_workspace"))

    def test_only_current_experiment_is_active_and_sequence_title_updates(self):
        window = self.window
        window.set_layout_preference("portrait")

        def create(_context, parent):
            panel = QWidget(parent)
            panel.activate = Mock()
            panel.deactivate = Mock()
            panel.shutdown = Mock()
            return panel

        for name in ("one", "two"):
            window.experiment_plugins[name] = SimpleNamespace(panel_factory=create, display_name=name)
            window.open_experiment(name)
        one, two = window.experiment_tabs["one"], window.experiment_tabs["two"]
        one.deactivate.reset_mock()
        two.deactivate.reset_mock()
        window.open_experiment("one")
        self.assertIs(window._active_experiment_panel, one)
        two.deactivate.assert_called_once()
        window.tabs.setCurrentWidget(window.sequence_workspace)
        one.deactivate.assert_called_once()
        window.update_sequence_tab_state(True)
        index = window.tabs.indexOf(window.sequence_workspace)
        self.assertEqual(window.tabs.tabText(index), "Sequence (Running)")
        window.update_sequence_tab_state(False)
        self.assertEqual(window.tabs.tabText(index), "Sequence")
        window.close_tab(index)
        self.assertIs(window.tabs.widget(index), window.sequence_workspace)

    def test_settings_keeps_current_tab_and_inputs_on_mode_changes(self):
        window = self.window
        window.set_layout_preference("portrait")
        window.open_settings_tab()
        settings = window.settings_panel
        old_path = settings.data_path.text()
        combo = settings.layout_mode_combo
        combo.setCurrentIndex(combo.findData("landscape"))
        self.assertIs(window.tabs.currentWidget(), settings)
        self.assertEqual((window.width(), window.height()), (1360, 800))
        combo.setCurrentIndex(combo.findData("portrait"))
        self.assertIs(window.tabs.currentWidget(), settings)
        self.assertEqual((window.width(), window.height()), (800, 1360))
        self.assertEqual(settings.data_path.text(), old_path)
        window.close_tab(window.tabs.indexOf(settings))
        self.assertIsNone(window.settings_panel)

    def test_layout_and_legal_information_are_only_in_settings(self):
        window = self.window
        header = window.findChild(QWidget, "mainHeader")
        self.assertEqual(header.findChildren(QComboBox), [])
        self.assertEqual(window.findChildren(QMenuBar), [])
        window.open_settings_tab()
        settings = window.settings_panel
        self.assertEqual(settings.tabs.tabText(0), "일반")
        self.assertEqual(settings.tabs.tabText(1), "정보 및 라이선스")
        self.assertIn("GNU GPL version 3", settings.about_view.toPlainText())
        self.assertIn("github.com/DaintyCandy/UOSLabManager", settings.about_view.toPlainText())
        self.assertIn("GNU GENERAL PUBLIC LICENSE", settings.license_tabs.widget(0).toPlainText())
        self.assertIn("PyQt6", settings.license_tabs.widget(1).toPlainText())
        combo = settings.layout_mode_combo
        combo.setCurrentIndex(combo.findData("portrait"))
        self.assertEqual(window.layout_mode, "compact")
        self.assertEqual(self.settings.value("appearance/layout_mode"), "portrait")
        window.set_layout_preference("landscape")
        self.assertEqual(combo.currentData(), "landscape")
        self.assertEqual(window.layout_mode, "wide")
        window.close_tab(window.tabs.indexOf(settings))
        window.open_settings_tab()
        self.assertEqual(window.settings_panel.layout_mode_combo.currentData(), "landscape")

    def test_missing_legal_resource_does_not_break_settings(self):
        with patch("gui.panel_settings.resource_path", side_effect=lambda name: Path(self.temp.name) / name):
            self.window.open_settings_tab()
        settings = self.window.settings_panel
        self.assertIn("Could not load LICENSE", settings.license_tabs.widget(0).toPlainText())
        settings.layout_mode_combo.setCurrentIndex(settings.layout_mode_combo.findData("portrait"))
        self.assertEqual(self.window.layout_mode, "compact")

    def test_manual_resizing_never_changes_selected_mode(self):
        window = self.window
        window.show()
        window.resize(864, 1536)
        QTest.qWait(150)
        self.assertEqual(window.layout_mode, "wide")
        self.assertLessEqual(window.width(), 864)
        window.set_layout_preference("portrait")
        window.resize(1360, 800)
        QTest.qWait(150)
        self.assertEqual(window.layout_mode, "compact")
        self.assertEqual((window.width(), window.height()), (1360, 800))

    def test_portrait_preference_and_split_direction_survive_restart(self):
        window = self.window
        window.set_layout_preference("portrait")
        window.measurement.split_graph_button.setChecked(True)
        window.camera_panel.split_button.setChecked(True)
        window.resize(700, 720)
        window.save_window_layout()
        window.close()
        window.deleteLater()
        self.window = MainWindow(self.theme)
        self.assertEqual(self.window.layout_preference, "portrait")
        self.assertEqual(self.window.layout_mode, "compact")
        self.assertEqual((self.window.width(), self.window.height()), (700, 720))
        for splitter in (self.window.measurement.graph_splitter, self.window.camera_panel.splitter):
            self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
        self.window.set_layout_preference("landscape")
        for splitter in (self.window.measurement.graph_splitter, self.window.camera_panel.splitter):
            self.assertEqual(splitter.orientation(), Qt.Orientation.Horizontal)

    def test_new_device_and_experiment_receive_current_mode(self):
        window = self.window
        window.apply_layout_mode("compact")

        class Panel(QWidget):
            def __init__(self, _context, parent):
                super().__init__(parent)
                self.calls = []

            def set_layout_mode(self, mode):
                self.calls.append(mode)

        window.plugins["device"] = SimpleNamespace(
            settings_factory=Panel, display_name="Test Device",
        )
        window.experiment_plugins["experiment"] = SimpleNamespace(
            panel_factory=Panel, display_name="Test Experiment",
        )
        window.open_device_tab("device")
        window.open_experiment("experiment")
        device = window.device_tabs["device"]
        experiment = window.experiment_tabs["experiment"]
        self.assertEqual(device.calls, ["compact"])
        self.assertEqual(experiment.calls, ["compact"])
        window.apply_layout_mode("wide")
        window.apply_layout_mode("wide")
        self.assertEqual(device.calls, ["compact", "wide"])
        self.assertEqual(experiment.calls, ["compact", "wide"])
        window.open_device_tab("device")
        self.assertIs(window.device_tabs["device"], device)

    def test_legacy_and_failing_optional_plugin_hooks_are_safe(self):
        window = self.window
        legacy = QWidget(window)
        broken = QWidget(window)
        broken.set_layout_mode = lambda _mode: (_ for _ in ()).throw(ValueError("bad hook"))
        good = QWidget(window)
        good.set_layout_mode = lambda mode: setattr(good, "received_mode", mode)
        window.device_tabs.update(legacy=legacy, broken=broken, good=good)
        with patch.object(window, "log") as log:
            window.apply_layout_mode("compact")
        self.assertEqual(good.received_mode, "compact")
        self.assertTrue(log.called)

    def test_row_restores_positions_without_duplicate_widgets(self):
        widget = QWidget()
        row = AdaptiveRowLayout(widget, compact_columns=2)
        labels = [QLabel(str(i)) for i in range(5)]
        for label in labels:
            row.addWidget(label)
        row.addStretch()
        positions = [row.getItemPosition(i) for i in range(row.count())]
        for _ in range(5):
            row.set_layout_mode("compact")
            self.assertEqual(row.count(), 5)
            self.assertEqual(row.getItemPosition(row.indexOf(labels[4])), (2, 0, 1, 1))
            row.set_layout_mode("wide")
            self.assertEqual(row.count(), 6)
            self.assertEqual([row.getItemPosition(i) for i in range(row.count())], positions)
        widget.deleteLater()

    def test_compact_label_and_input_pairs_stay_on_the_same_row(self):
        self.window.apply_layout_mode("compact")
        panel = self.window.measurement
        controls = panel.table_widget.layout().itemAt(0).layout()
        for label, control in (("Update (ms)", panel.interval_spin),
                               ("Buffer rows", panel.buffer_spin)):
            widget = next(w for w in panel.table_widget.findChildren(QLabel) if w.text() == label)
            label_position = controls.getItemPosition(controls.indexOf(widget))
            control_position = controls.getItemPosition(controls.indexOf(control))
            self.assertEqual(label_position[0], control_position[0])
            self.assertEqual((label_position[1], control_position[1]), (0, 1))

    def test_vertical_saved_splitter_restores_and_can_return_to_wide(self):
        original = AdaptiveSplitter()
        restored = AdaptiveSplitter()
        for splitter in (original, restored):
            splitter.addWidget(QWidget())
            splitter.addWidget(QWidget())
        original.set_layout_mode("compact")
        self.assertTrue(restored.restoreState(original.saveState()))
        self.assertEqual(restored.orientation(), Qt.Orientation.Vertical)
        restored.restore_mode_sizes("wide", [200, 600])
        restored.set_layout_mode("wide")
        self.assertEqual(restored.orientation(), Qt.Orientation.Horizontal)
        self.assertIn("compact", restored.mode_sizes())
        restored.restore_mode_sizes("wide", ["invalid"])
        original.deleteLater()
        restored.deleteLater()

    def test_portrait_builtin_pages_do_not_need_horizontal_scrolling(self):
        # Offscreen Qt on Windows does not discover system fonts automatically.
        for name in ("segoeui.ttf", "malgun.ttf"):
            path = Path("C:/Windows/Fonts") / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
        old_font = self.app.font()
        self.app.setFont(QFont("Segoe UI" if os.name == "nt" else "sans-serif", 9))
        manager = DeviceManager()
        cameras = CameraWorkspace(self.temp.name, lambda _message: None)
        context = ExperimentContext(manager, cameras, lambda *_args, **_kwargs: None)
        try:
            for plugin, service, factory in [
                (p, manager, "settings_factory") for p in (ctvideo, gpd, keithley, lakeshore, zup)
            ] + [(p, context, "panel_factory") for p in (mbe, heating, line_profile)]:
                with self.subTest(plugin=plugin.display_name):
                    panel = getattr(plugin, factory)(service, None)
                    area = QScrollArea()
                    area.setWidgetResizable(True)
                    area.setWidget(panel)
                    panel.set_layout_mode("compact")
                    area.resize(640, 1100)
                    area.show()
                    self.app.processEvents()
                    self.assertEqual(area.horizontalScrollBar().maximum(), 0, (
                        panel.minimumSizeHint(), panel.size(),
                        [(type(w).__name__, w.minimumSizeHint())
                         for w in panel.findChildren(QWidget)
                         if w.minimumSizeHint().width() > 600],
                    ))
                    if hasattr(panel, "shutdown"):
                        panel.shutdown()
                    for name in ("monitor_timer", "refresh_timer", "ramp_timer"):
                        timer = getattr(panel, name, None)
                        if timer is not None:
                            timer.stop()
                    if hasattr(panel, "video_view"):
                        panel.video_view.stop_preview()
                    area.close()
                    area.deleteLater()
        finally:
            cameras.stop_preview()
            cameras.deleteLater()
            self.app.setFont(old_font)

    def test_grid_restores_positions_without_duplicate_widgets(self):
        widget = QWidget()
        grid = AdaptiveGridLayout(widget)
        labels = [QLabel(str(i)) for i in range(3)]
        grid.addWidget(labels[0], 0, 0, 1, 2)
        grid.addWidget(labels[1], 1, 0)
        grid.addWidget(labels[2], 1, 1)
        grid.setRowStretch(1, 3)
        grid.setColumnStretch(1, 2)
        positions = [grid.getItemPosition(i) for i in range(grid.count())]
        for _ in range(5):
            grid.set_layout_mode("compact")
            self.assertEqual(grid.count(), 3)
            self.assertEqual(grid.getItemPosition(grid.indexOf(labels[2])), (2, 0, 1, 1))
            grid.set_layout_mode("wide")
            self.assertEqual([grid.getItemPosition(i) for i in range(grid.count())], positions)
            self.assertEqual(grid.rowStretch(1), 3)
            self.assertEqual(grid.columnStretch(1), 2)
        widget.deleteLater()

    def test_all_builtin_plugins_keep_panel_identity_and_snapshots(self):
        manager = DeviceManager()
        cameras = CameraWorkspace(self.temp.name, lambda _message: None)
        context = ExperimentContext(manager, cameras, lambda *_args, **_kwargs: None)
        plugins = [
            (plugin, manager, "settings_factory")
            for plugin in (ctvideo, gpd, keithley, lakeshore, zup, standard)
        ] + [
            (plugin, context, "panel_factory")
            for plugin in (mbe, heating, line_profile)
        ]
        with patch.object(manager, "add_device") as add, patch.object(manager, "remove_device") as remove:
            for plugin, service, factory in plugins:
                with self.subTest(plugin=plugin.display_name):
                    panel = getattr(plugin, factory)(service, None)
                    widgets = set(panel.findChildren(QWidget))
                    snapshot = object()
                    panel.snapshot = snapshot
                    layout = panel.layout()
                    positions = (
                        [layout.getItemPosition(i) for i in range(layout.count())]
                        if isinstance(layout, AdaptiveGridLayout) else None
                    )
                    for _ in range(3):
                        panel.set_layout_mode("compact")
                        for splitter in panel.findChildren(AdaptiveSplitter):
                            self.assertEqual(splitter.orientation(), Qt.Orientation.Vertical)
                        panel.set_layout_mode("wide")
                    self.assertEqual(set(panel.findChildren(QWidget)), widgets)
                    self.assertIs(panel.snapshot, snapshot)
                    if positions is not None:
                        self.assertEqual(
                            [layout.getItemPosition(i) for i in range(layout.count())], positions,
                        )
                    if hasattr(panel, "shutdown"):
                        panel.shutdown()
                    for timer_name in ("monitor_timer", "refresh_timer", "ramp_timer"):
                        timer = getattr(panel, timer_name, None)
                        if timer is not None:
                            timer.stop()
                    if hasattr(panel, "video_view"):
                        panel.video_view.stop_preview()
                    panel.deleteLater()
            add.assert_not_called()
            remove.assert_not_called()
        cameras.stop_preview()
        cameras.deleteLater()


if __name__ == "__main__":
    unittest.main()
