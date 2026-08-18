import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from plugins.experiments.heating_control.panel import (
    HeatingControlPanel, HeatingPIDWorker,
)


class FakeManager:
    def __init__(self):
        self.latest = {"CTVIDEO3M": {"actual_temp_C": 351.0}}

    def get_device(self, _name):
        return None

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
