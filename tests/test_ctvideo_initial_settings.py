import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from plugins.devices.ctvideo_3m.panel import CTVideo3MPanel


ORIGINAL = {
    "emissivity": 0.91,
    "transmission": 0.87,
    "average_time_s": 1.2,
    "smart_averaging": True,
    "peak_hold_s": 0.4,
}


class Manager:
    def __init__(self, device):
        self.device = device

    def get_device(self, _name):
        return self.device

    def get_metrics(self, _name):
        return {"response_ms": None, "updated_at": None}

    def get_latest(self, _name):
        return {}


def run_now(_owner, work, completed, failed, **_kwargs):
    try:
        completed(work())
    except Exception as error:
        failed(error)


class CTVideoInitialSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.device = MagicMock()
        self.device.read_settings.return_value = dict(ORIGINAL)
        self.manager = Manager(None)
        self.panel = CTVideo3MPanel(self.manager, MagicMock())
        self.manager.device = self.device
        self.panel._apply_device_settings(ORIGINAL)

    def tearDown(self):
        self.panel.shutdown()
        self.panel.deleteLater()
        self.app.processEvents()

    def _apply(self):
        with patch(
            "plugins.devices.ctvideo_3m.panel.run_busy_task", side_effect=run_now
        ):
            self.panel.apply_settings()

    def test_unchanged_original_values_send_no_device_writes(self):
        self._apply()

        for name in (
            "set_emissivity", "set_transmission", "set_average_time",
            "set_smart_averaging", "set_peak_hold_time",
        ):
            getattr(self.device, name).assert_not_called()
        self.device.read_settings.assert_called_once_with()

    def test_only_user_changed_value_is_written(self):
        self.panel.emissivity.setValue(0.95)
        self.device.read_settings.return_value = {**ORIGINAL, "emissivity": 0.95}

        self._apply()

        self.device.set_emissivity.assert_called_once_with(0.95)
        self.device.set_transmission.assert_not_called()
        self.device.set_average_time.assert_not_called()
        self.device.set_smart_averaging.assert_not_called()
        self.device.set_peak_hold_time.assert_not_called()
        self.assertEqual(self.panel.device_settings_snapshot["emissivity"], 0.95)

    def test_write_is_blocked_until_current_device_values_are_read(self):
        self.panel.device_settings_snapshot = None
        self.panel.show_error = MagicMock()

        self._apply()

        self.panel.show_error.assert_called_once()
        self.device.read_settings.assert_not_called()
        self.device.set_emissivity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
