import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from plugins.devices.ctvideo_3m import panel as panel_module
from plugins.devices.ctvideo_3m.panel import CTVideo3MPanel


class FakeManager:
    @staticmethod
    def get_device(_device_id):
        return None

    @staticmethod
    def get_metrics(_device_id):
        return {"response_ms": None}


class TestMacOSUVCPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = CTVideo3MPanel(
            FakeManager(), SimpleNamespace(device_id="CTVIDEO3M")
        )

    def tearDown(self):
        self.panel.close()

    def test_uses_native_range_and_disables_unadvertised_gain(self):
        properties = {
            "brightness_supported": True,
            "gain_supported": False,
            "auto_exposure": None,
            "auto_exposure_raw": None,
            "uvc_controls": {
                "Brightness": {
                    "supported": True,
                    "settable": True,
                    "minimum": 0,
                    "maximum": 255,
                    "step": 1,
                    "default": 118,
                    "current": 118,
                },
                "Gain": {
                    "supported": False,
                    "settable": False,
                    "minimum": None,
                    "maximum": None,
                    "step": None,
                    "default": None,
                    "current": None,
                },
            },
        }

        with patch.object(panel_module.sys, "platform", "darwin"):
            self.panel.update_camera_properties(properties)

        self.assertTrue(self.panel.camera_brightness.isEnabled())
        self.assertEqual(self.panel.camera_brightness.minimum(), 0)
        self.assertEqual(self.panel.camera_brightness.maximum(), 255)
        self.assertEqual(self.panel.camera_brightness.value(), 118)
        self.assertFalse(self.panel.camera_gain.isEnabled())
        self.assertEqual(
            self.panel.auto_exposure_label.text(), "Auto exposure: unsupported"
        )

    def test_disables_controls_when_native_probe_is_unavailable(self):
        properties = {
            "brightness_supported": False,
            "gain_supported": False,
            "auto_exposure": None,
            "auto_exposure_raw": None,
            "uvc_controls": {},
        }

        with patch.object(panel_module.sys, "platform", "darwin"):
            self.panel.update_camera_properties(properties)

        self.assertFalse(self.panel.camera_brightness.isEnabled())
        self.assertFalse(self.panel.camera_gain.isEnabled())
        self.assertFalse(self.panel.camera_power_line.isEnabled())
        self.assertFalse(self.panel.camera_roi.isEnabled())


if __name__ == "__main__":
    unittest.main()
