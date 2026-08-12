import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget

from gui.main_window import MainWindow
from gui.panel_measurement import MeasurementPanels
from gui.panel_sequence import SYSTEM_DEVICE, SequencePanel


class FakeManager:
    def __init__(self):
        self.values = {}
        self.connected = set()
        self.devices = {}

    def get_device(self, name):
        return self.devices.get(name)

    def get_latest(self, name):
        return dict(self.values.get(name, {}))

    def get_metrics(self, name):
        return {
            "connected": name in self.connected,
            "age_ms": 0.0 if name in self.connected else None,
        }

    def read_all(self):
        return {name: dict(values) for name, values in self.values.items()}


class SequenceSystemActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = FakeManager()
        self.logs = []
        self.panel = SequencePanel(self.manager, self.logs.append)
        self.panel.engine_timer.stop()

    def tearDown(self):
        self.panel.engine_timer.stop()
        self.panel.deleteLater()

    def test_system_commands_are_available_without_a_device(self):
        self.assertEqual(self.panel.dev_combo.currentData(), SYSTEM_DEVICE)
        commands = {
            self.panel.cmd_combo.itemText(index)
            for index in range(self.panel.cmd_combo.count())
        }
        self.assertIn("Wait Time", commands)
        self.assertIn("Wait Until", commands)
        self.assertIn("Log Marker", commands)
        self.assertIn("Safe Output Off", commands)

    def test_legacy_ls331_wait_is_converted_from_minutes_to_seconds(self):
        steps = self.panel.validate_recipe({
            "schema_version": 1,
            "steps": [{"dev": "LS331", "cmd": "Wait Time", "val": 2}],
        })
        self.assertEqual(steps, [{
            "dev": SYSTEM_DEVICE, "cmd": "Wait Time", "val": 120.0,
        }])

    def test_wait_time_uses_monotonic_clock_and_changes_running_state(self):
        self.panel.add_recipe_item({
            "dev": SYSTEM_DEVICE, "cmd": "Wait Time", "val": 1.0,
        })
        states = []
        self.panel.running_changed.connect(states.append)
        self.panel.toggle_execution()
        self.panel.engine_timer.stop()
        with patch("gui.panel_sequence.time.monotonic", return_value=10.0):
            self.panel.run_engine()
        self.assertEqual(self.panel.state, "WAIT_FOR_TIME")
        with patch("gui.panel_sequence.time.monotonic", return_value=11.0):
            self.panel.run_engine()
        self.panel.run_engine()
        self.assertEqual(states, [True, False])

    def test_wait_until_requires_stable_time(self):
        condition = {
            "label": "CTvideo Temperature",
            "device": "CTVIDEO3M",
            "key": "actual_temp_C",
            "unit": "degC",
            "operator": ">=",
            "target": 100.0,
            "tolerance": 0.0,
            "stable_s": 1.0,
            "timeout_s": 10.0,
            "on_timeout": "stop",
        }
        self.manager.connected.add("CTVIDEO3M")
        self.manager.values["CTVIDEO3M"] = {"actual_temp_C": 101.0}
        with patch("gui.panel_sequence.time.monotonic", return_value=0.0):
            self.panel.execute_system_step({
                "dev": SYSTEM_DEVICE, "cmd": "Wait Until", "val": condition,
            })
            self.panel.poll_wait_condition()
        self.assertEqual(self.panel.current_step_idx, 0)
        with patch("gui.panel_sequence.time.monotonic", return_value=1.0):
            self.panel.poll_wait_condition()
        self.assertEqual(self.panel.current_step_idx, 1)

    def test_recording_marker_and_safe_output_callbacks(self):
        recording = []
        markers = []
        safe_calls = []

        def recording_action(enabled):
            recording.append(enabled)
            return enabled

        self.panel.set_common_actions(
            recording_action, markers.append, lambda: safe_calls.append(True)
        )
        for command, value in (
            ("Start Recording", 0),
            ("Log Marker", "target reached"),
            ("Safe Output Off", 0),
            ("Stop Recording", 0),
        ):
            self.panel.execute_system_step({
                "dev": SYSTEM_DEVICE, "cmd": command, "val": value,
            })
        self.assertEqual(recording, [True, False])
        self.assertEqual(markers, ["target reached"])
        self.assertEqual(safe_calls, [True])

    def test_measurement_rows_include_sequence_markers(self):
        measurement = MeasurementPanels(self.manager, {}, self.logs.append)
        measurement.recording = True
        measurement.add_sequence_marker("heating started")
        measurement.update()
        self.assertEqual(
            measurement.rows[-1]["sequence_marker"], "heating started"
        )
        self.assertIn("sequence_marker", measurement.data_logger.columns)
        measurement.timer.stop()

    def test_sequence_tab_changes_color_while_running(self):
        tabs = QTabWidget()
        sequence_workspace = QWidget()
        tabs.addTab(QWidget(), "Data")
        tabs.addTab(sequence_workspace, "Sequence")
        window = SimpleNamespace(
            tabs=tabs, sequence_workspace=sequence_workspace,
        )
        MainWindow.update_sequence_tab_state(window, True)
        index = tabs.indexOf(sequence_workspace)
        self.assertIn("Sequence", tabs.tabText(index))
        self.assertEqual(tabs.tabBar().tabTextColor(index).name(), "#00e676")
        MainWindow.update_sequence_tab_state(window, False)
        self.assertEqual(tabs.tabText(index), "Sequence")
        self.assertEqual(tabs.tabBar().tabTextColor(index).name(), "#ffb74d")


if __name__ == "__main__":
    unittest.main()
