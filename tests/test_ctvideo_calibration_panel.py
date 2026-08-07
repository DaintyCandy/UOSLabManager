import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox

from plugins.devices.ctvideo_3m.driver import (
    CalibrationApplyResult,
    CalibrationSnapshot,
)
from plugins.devices.ctvideo_3m.panel import CTVideo3MPanel


class FakeManager:
    def __init__(self):
        self.device = None

    def get_device(self, name):
        return self.device if name == "CTVIDEO3M" else None

    def get_metrics(self, _name):
        return {"response_ms": None, "updated_at": None}

    def get_latest(self, _name):
        return {}


class CTVideoCalibrationPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.manager = FakeManager()
        self.panel = CTVideo3MPanel(self.manager, MagicMock())
        self.snapshot = CalibrationSnapshot(
            serial_number=42,
            firmware_revision=0x0102,
            tweak_offset_C=0.0,
            tweak_gain=1.0,
            raw_offset=0x03E8,
            raw_gain=0x8000,
        )
        self.device = MagicMock()
        self.device.read_calibration.return_value = self.snapshot
        self.manager.device = self.device
        self.panel._video_attach_attempted = True
        self.panel.sync_connection_status()

    def tearDown(self):
        self.panel.shutdown()
        self.panel.deleteLater()
        self.app.processEvents()

    def tab_names(self):
        return [self.panel.tabs.tabText(index)
                for index in range(self.panel.tabs.count())]

    def test_calibration_is_separate_and_connection_remains_rightmost(self):
        self.assertEqual(
            self.tab_names(),
            ["Pyrometer", "Settings", "Calibration", "Connection"],
        )
        self.assertNotIn("calibration", self.panel.profile_data())

    def test_normal_apply_never_writes_calibration(self):
        self.panel.apply_settings()
        self.device.apply_calibration.assert_not_called()
        self.device.set_tweak_offset.assert_not_called()
        self.device.set_tweak_gain.assert_not_called()

    def test_write_is_disabled_until_current_calibration_is_read(self):
        self.assertFalse(self.panel.apply_calibration_button.isEnabled())
        with patch.object(self.panel, "show_error") as show_error:
            self.assertFalse(self.panel.apply_calibration())
        show_error.assert_called_once()
        self.device.apply_calibration.assert_not_called()

    def test_no_confirmation_never_calls_driver_write(self):
        self.assertTrue(self.panel.read_calibration())
        self.panel.calibration_offset_proposed.setValue(0.5)
        self.panel.calibration_ack.setChecked(True)
        self.assertTrue(self.panel.apply_calibration_button.isEnabled())
        with patch(
            "plugins.devices.ctvideo_3m.panel.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.No,
        ):
            self.assertFalse(self.panel.apply_calibration())
        self.device.apply_calibration.assert_not_called()

    def test_confirmed_write_updates_only_after_verified_readback(self):
        after = CalibrationSnapshot(
            serial_number=42,
            firmware_revision=0x0102,
            tweak_offset_C=0.5,
            tweak_gain=1.0,
            raw_offset=0x03ED,
            raw_gain=0x8000,
        )
        self.device.apply_calibration.return_value = CalibrationApplyResult(
            before=self.snapshot,
            requested={"tweak_offset_C": 0.5, "tweak_gain": 1.0},
            after=after,
            statuses={"tweak_offset_C": "verified", "tweak_gain": "unchanged"},
        )
        self.assertTrue(self.panel.read_calibration())
        self.panel.calibration_offset_proposed.setValue(0.5)
        self.panel.calibration_ack.setChecked(True)
        with patch(
            "plugins.devices.ctvideo_3m.panel.QMessageBox.warning",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.assertTrue(self.panel.apply_calibration())
        self.device.apply_calibration.assert_called_once()
        args, kwargs = self.device.apply_calibration.call_args
        self.assertEqual(args[0], self.snapshot)
        self.assertEqual(args[1]["tweak_offset_C"], 0.5)
        self.assertTrue(kwargs["confirmed"])
        self.assertEqual(self.panel.calibration_snapshot, after)
        self.assertIn("verified", self.panel.calibration_status_label.text().lower())


if __name__ == "__main__":
    unittest.main()
