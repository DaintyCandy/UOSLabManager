import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from plugins.devices.ctvideo_3m.panel import CTVideo3MPanel


class FakeManager:
    @staticmethod
    def get_device(_device_id):
        return None

    @staticmethod
    def get_metrics(_device_id):
        return {"response_ms": None}


class TestMacOSCameraPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = CTVideo3MPanel(
            FakeManager(), SimpleNamespace(device_id="CTVIDEO3M")
        )

    def tearDown(self):
        self.panel.close()

    def test_generic_uvc_widgets_are_not_restored(self):
        for attribute in (
            "camera_brightness",
            "camera_contrast",
            "camera_gain",
            "camera_exposure",
            "camera_roi",
        ):
            with self.subTest(attribute=attribute):
                self.assertFalse(hasattr(self.panel, attribute))

    def test_vendor_controls_stay_disabled_when_vendor_xu_is_unavailable(self):
        properties = {
            "operation": "read",
            "controls": {
                "CompactConnect Video Gain": {
                    "supported": False,
                    "current": None,
                    "detail": "Vendor XU is unavailable on macOS",
                },
                "CompactConnect Anti-flicker": {
                    "supported": False,
                    "current": None,
                    "display": "Anti-flicker unavailable",
                    "detail": "Vendor XU is unavailable on macOS",
                },
            },
        }

        self.panel.update_camera_properties(properties)

        self.assertFalse(self.panel.compactconnect_video_gain.isEnabled())
        self.assertFalse(self.panel.compactconnect_anti_flicker.isEnabled())
        self.assertIn("Unavailable", self.panel.video_gain_readback.text())
        self.assertIn("Unavailable", self.panel.anti_flicker_readback.text())


if __name__ == "__main__":
    unittest.main()
