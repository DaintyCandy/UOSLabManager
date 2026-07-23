import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox

from plugins.devices.gpd3303s.panel import GPD3303SPanel


class FakeManager:
    def __init__(self, device):
        self.device = device

    def get_device(self, _device_id):
        return self.device

    def get_latest(self, _device_id):
        return {}

    def remove_device(self, _device_id):
        pass


class TestGPD3303SPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.device = MagicMock()
        manager = FakeManager(self.device)
        plugin = SimpleNamespace(device_id="GPD3303S")
        self.panel = GPD3303SPanel(manager, plugin)
        self.panel.show_error = MagicMock()
        self.panel.ch1_voltage.setValue(1.0)
        self.panel.ch1_current.setValue(0.05)
        self.panel.ch2_voltage.setValue(0.0)
        self.panel.ch2_current.setValue(0.05)

    def tearDown(self):
        self.panel.close()

    def test_out0_on_connect_is_checked_by_default(self):
        self.assertTrue(self.panel.output_off_on_connect.isChecked())

    def test_channel_settings_apply_current_before_voltage(self):
        self.panel._apply_channel_settings("CH1")
        self.assertEqual(
            self.device.method_calls,
            [call.set_channel_current("CH1", 0.05), call.set_channel_voltage("CH1", 1.0)],
        )

    def test_partial_setting_failure_never_sends_out1(self):
        self.panel.output_enabled.setChecked(True)
        self.device.set_channel_current.side_effect = RuntimeError("write failed")

        self.panel.apply_settings()

        self.device.output_on.assert_not_called()
        self.assertGreaterEqual(self.device.output_off.call_count, 1)
        self.assertFalse(self.panel.output_enabled.isChecked())
        self.panel.show_error.assert_called_once()


    def test_output_off_now_enters_off_confirmation_and_prevents_stale_on_display(self):
        self.panel.output_enabled.setChecked(True)

        self.panel.output_off_now()

        self.device.output_off.assert_called_once_with()
        self.assertFalse(self.panel.output_enabled.isChecked())
        self.assertEqual(self.panel.output_status.text(), "Output OFF 확인 중...")

        self.panel.manager.get_latest = lambda _device_id: {"output_on": True, "CH1_voltage_V": 0.0, "CH1_current_A": 0.0, "CH2_voltage_V": 0.0, "CH2_current_A": 0.0, "status_raw": "OK"}
        self.panel.refresh_monitoring()
        self.assertEqual(self.panel.output_status.text(), "Output OFF 확인 중...")

    @patch(
        "plugins.devices.gpd3303s.panel.QMessageBox.warning",
        return_value=QMessageBox.StandardButton.Ok,
    )
    @patch("plugins.devices.gpd3303s.panel.time.monotonic", return_value=12345.0)
    def test_output_off_confirmation_shows_failure_after_timeout(self, mocked_time, mocked_warning):
        self.panel.output_enabled.setChecked(True)
        self.panel.output_off_now()
        self.panel.off_confirmation_start = 12339.0

        self.panel.manager.get_latest = lambda _device_id: {"output_on": True, "CH1_voltage_V": 0.0, "CH1_current_A": 0.0, "CH2_voltage_V": 0.0, "CH2_current_A": 0.0, "status_raw": "OK"}
        self.panel.refresh_monitoring()

        mocked_warning.assert_called_once()
        self.assertEqual(self.panel.output_status.text(), "Output OFF 확인 실패")
    def test_output_off_now_sends_out0_immediately(self):
        self.panel.output_enabled.setChecked(True)

        self.panel.output_off_now()

        self.device.output_off.assert_called_once_with()
        self.device.output_on.assert_not_called()
        self.assertFalse(self.panel.output_enabled.isChecked())
        self.assertEqual(self.panel.output_status.text(), "Output OFF 확인 중...")

    @patch(
        "plugins.devices.gpd3303s.panel.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    )
    def test_cancelled_confirmation_leaves_output_off(self, _question):
        self.panel.output_enabled.setChecked(True)

        self.panel.apply_settings()

        self.device.output_on.assert_not_called()
        self.device.output_off.assert_called_once()
        self.assertFalse(self.panel.output_enabled.isChecked())

    @patch(
        "plugins.devices.gpd3303s.panel.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    )
    def test_confirmed_output_sends_out1_after_all_settings(self, _question):
        self.panel.output_enabled.setChecked(True)

        self.panel.apply_settings()

        self.assertEqual(
            self.device.method_calls,
            [
                call.output_off(),
                call.set_channel_current("CH1", 0.05),
                call.set_channel_voltage("CH1", 1.0),
                call.set_channel_current("CH2", 0.05),
                call.set_channel_voltage("CH2", 0.0),
                call.output_on(),
            ],
        )


if __name__ == "__main__":
    unittest.main()
