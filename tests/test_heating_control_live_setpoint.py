import os
import unittest

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

    def test_sequence_completion_follows_live_setpoint(self):
        self.panel.target_temperature.setValue(350.0)
        self.panel.apply_running_setpoint()

        self.assertTrue(
            self.panel.is_sequence_command_complete("ramp_to_setpoint", 300.0)
        )


if __name__ == "__main__":
    unittest.main()
