import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea

from plugins.experiments.heating_control.panel import (
    HeatingControlPanel, HeatingPIDWorker,
)


class FakeManager:
    def __init__(self):
        self.latest = {"CTVIDEO3M": {"actual_temp_C": 351.0}}
        self.devices = {}

    def get_device(self, name):
        return self.devices.get(name)

    def get_latest(self, name):
        return dict(self.latest.get(name, {}))

    def get_metrics(self, _name):
        return {
            "connected": False, "age_ms": None, "updated_at": None,
            "error": "", "response_ms": None,
        }


class HeatingControlLiveSetpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = FakeManager()
        self.panel = HeatingControlPanel(self.manager)
        self.panel.refresh_timer.stop()
        config = {
            "target_temperature": 300.0,
            "max_temperature": 500.0,
            "current_ramp_enabled": True,
            "current_ramp_rate": 0.1,
        }
        self.worker = HeatingPIDWorker(self.manager, config, self.panel)
        self.panel.control_worker = self.worker
        self.panel.control_active = True

    def tearDown(self):
        self.panel.control_active = False
        self.panel.control_worker = None
        self.worker.deleteLater()
        self.panel.video_view.stop_preview()
        self.panel.deleteLater()

    def test_target_control_stays_enabled_during_pid(self):
        self.assertNotIn(
            self.panel.target_temperature,
            self.panel.control_setting_widgets,
        )
        self.assertTrue(self.panel.target_temperature.isEnabled())
        self.assertTrue(self.panel.apply_setpoint_button.isEnabled())

    def test_device_connections_are_status_only(self):
        for removed_control in (
            "zup_port", "zup_address", "zup_button", "ctvideo_port",
            "ctvideo_button",
        ):
            self.assertFalse(hasattr(self.panel, removed_control))

        self.manager.devices["ZUP"] = object()
        self.panel.sync_connection_status()

        self.assertEqual(self.panel.zup_status.text(), "Connected")
        self.assertEqual(self.panel.ctvideo_status.text(), "Disconnected")

    def test_status_log_and_live_values_use_compact_grid(self):
        connection_index = self.panel.status_layout.indexOf(
            self.panel.connection_status_panel
        )
        log_index = self.panel.status_layout.indexOf(
            self.panel.log_group
        )
        measurements_index = self.panel.status_layout.indexOf(
            self.panel.measurements_panel
        )

        self.assertEqual(
            self.panel.status_layout.getItemPosition(connection_index),
            (0, 0, 1, 1),
        )
        self.assertEqual(
            self.panel.status_layout.getItemPosition(log_index),
            (1, 0, 1, 1),
        )
        self.assertEqual(
            self.panel.status_layout.getItemPosition(measurements_index),
            (0, 1, 2, 1),
        )

        measurement_grid = self.panel.measurements_panel.layout()
        positions = []
        for button in self.panel.value_buttons.values():
            index = measurement_grid.indexOf(button)
            row, column, _row_span, _column_span = (
                measurement_grid.getItemPosition(index)
            )
            positions.append((row, column))
        self.assertEqual(positions, [(0, 0), (0, 1), (1, 0), (1, 1)])

        self.assertLessEqual(self.panel.minimumSizeHint().width(), 1000)
        self.assertLessEqual(self.panel.minimumSizeHint().height(), 700)

    def test_workspace_uses_requested_four_quadrants(self):
        layout = self.panel.layout()
        expected = (
            (self.panel.status_panel, (0, 0, 1, 1)),
            (self.panel.heating_panel, (0, 1, 1, 1)),
            (self.panel.graph_panel, (1, 0, 1, 1)),
            (self.panel.pyrometer_panel, (1, 1, 1, 1)),
        )
        for widget, position in expected:
            self.assertEqual(layout.getItemPosition(layout.indexOf(widget)), position)

        self.assertEqual(layout.rowStretch(0), 0)
        self.assertEqual(layout.rowStretch(1), 1)
        self.assertLessEqual(self.panel.status_panel.minimumSizeHint().height(), 260)
        self.assertLessEqual(self.panel.heating_panel.minimumSizeHint().height(), 260)
        self.assertEqual(
            self.panel.status_panel.height(), self.panel.heating_panel.height()
        )

        labels = [label.text() for label in self.panel.findChildren(QLabel)]
        self.assertNotIn("Connections are managed in the Devices tab.", labels)

    def test_compact_view_does_not_require_vertical_scrolling(self):
        container = QScrollArea()
        container.setWidgetResizable(True)
        container.setWidget(self.panel)
        container.resize(1000, 480)
        container.show()
        self.app.processEvents()

        self.assertEqual(container.verticalScrollBar().maximum(), 0)
        self.assertEqual(
            self.panel.graph_panel.height(), self.panel.pyrometer_panel.height()
        )
        self.assertGreater(self.panel.graph_panel.height(), 0)
        container.takeWidget()
        container.close()

    def test_apply_setpoint_updates_running_worker(self):
        self.panel.target_temperature.setValue(350.0)

        self.panel.apply_running_setpoint()

        self.assertEqual(self.worker.get_target_temperature(), 350.0)

    def test_ramp_controls_remain_enabled_while_safety_and_pid_settings_lock(self):
        for widget in self.panel.control_setting_widgets:
            widget.setEnabled(False)
        self.assertTrue(self.panel.current_ramp_enabled.isEnabled())
        self.assertTrue(self.panel.current_ramp_rate.isEnabled())
        self.assertTrue(self.panel.apply_ramp_button.isEnabled())
        self.assertFalse(self.panel.control_current_limit.isEnabled())
        self.assertFalse(self.panel.max_temperature.isEnabled())
        self.assertFalse(self.panel.pid_p.isEnabled())

    def test_apply_ramp_changes_running_worker_without_restarting_or_writing_output(self):
        self.panel.current_ramp_rate.setValue(0.25)
        self.assertEqual(self.worker.get_current_ramp(), (True, 0.1))
        self.manager.devices["ZUP"] = Mock()
        with patch.object(self.worker, "start") as start:
            self.panel.apply_ramp_button.click()
            self.assertEqual(self.worker.get_current_ramp(), (True, 0.25))
            self.panel.current_ramp_enabled.setChecked(False)
            self.panel.apply_ramp_button.click()
            self.assertEqual(self.worker.get_current_ramp(), (False, 0.25))
            start.assert_not_called()
        self.assertEqual(self.worker.config["max_temperature"], 500.0)
        self.assertEqual(self.manager.devices["ZUP"].mock_calls, [])

    def test_invalid_ramp_values_leave_previous_settings_intact(self):
        for rate in (float("nan"), float("inf"), -1, 0, 0.0001, 12.1, True):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                self.worker.set_current_ramp(True, rate)
        self.assertEqual(self.worker.get_current_ramp(), (True, 0.1))

    def test_ramp_apply_when_stopped_only_leaves_settings_for_next_start(self):
        self.panel.control_active = False
        self.panel.current_ramp_rate.setValue(0.5)
        self.panel.apply_running_ramp()
        self.assertEqual(self.worker.get_current_ramp(), (True, 0.1))

    def test_live_rate_is_used_on_next_sample_in_both_current_directions(self):
        worker = self.worker
        worker.config.update(target_temperature=450.0, p=4.0, i=0.0, d=0.0,
                             voltage_limit=12.0, current_limit=1.0, power_limit=12.0)
        self.manager.latest["ZUP"] = {"voltage_V": 0.0, "current_A": 0.0, "power_W": 0.0}
        device = Mock()
        self.manager.devices["ZUP"] = device
        commands = []

        def command_current(value):
            if value > 0:
                commands.append(value)
                if len(commands) == 1:
                    worker.set_current_ramp(True, 0.25)
                elif len(commands) == 2:
                    worker.set_target_temperature(300.0)

        device.set_current.side_effect = command_current
        sample = 0

        def metrics(_name):
            nonlocal sample
            sample += 1
            return {"connected": True, "age_ms": 0, "updated_at": sample}

        trips = []
        worker.safety_tripped.connect(trips.append)
        with patch.object(self.manager, "get_metrics", side_effect=metrics), \
                patch.object(worker, "isInterruptionRequested", side_effect=lambda: len(commands) >= 3), \
                patch.object(worker, "msleep"), \
                patch("plugins.experiments.heating_control.panel.time.monotonic", side_effect=[0, 1, 2, 3]):
            worker.run()  # Real control loop, mock devices only; no thread or output is started.
        self.assertEqual(trips, [])
        self.assertEqual(len(commands), 3)
        for actual, expected in zip(commands, (0.1, 0.35, 0.1)):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(device.set_current.call_args.args, (0.0,))
        device.output_off.assert_called()

    def test_sequence_completion_follows_live_setpoint(self):
        self.panel.target_temperature.setValue(350.0)
        self.panel.apply_running_setpoint()

        self.assertTrue(
            self.panel.is_sequence_command_complete("ramp_to_setpoint", 300.0)
        )


if __name__ == "__main__":
    unittest.main()
