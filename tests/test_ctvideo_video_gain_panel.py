import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QLabel

from plugins.devices.ctvideo_3m.panel import CTVideo3MPanel
from plugins.devices.ctvideo_3m.video_display import (
    CompactConnectVideoDisplaySettings,
)


SOFTWARE_DISPLAY_KEYS = {
    "red_gain",
    "green_gain",
    "blue_gain",
    "brightness",
    "rotation_deg",
    "black_and_white",
    "mirror_x",
    "mirror_y",
    "target_circle_style",
    "target_circle_width",
    "target_circle_color",
    "target_optical_resolution",
    "background_color",
    "background_circle_color",
    "background_circle_diameter",
}


class FakeManager:
    def get_device(self, _name):
        return None

    def get_metrics(self, _name):
        return {"response_ms": None, "updated_at": None}

    def get_latest(self, _name):
        return {}


class CTVideoVendorPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = CTVideo3MPanel(FakeManager(), MagicMock())
        self.worker = MagicMock()
        self.panel.video_view.worker = self.worker
        self.panel.update_camera_properties({
            "operation": "read",
            "controls": {
                "CompactConnect Video Gain": {
                    "supported": True,
                    "current": 179,
                    "minimum": 1,
                    "maximum": 255,
                    "step": 1,
                    "detail": "EEPROM YTarget read-back 179",
                },
                "CompactConnect Anti-flicker": {
                    "supported": True,
                    "current": None,
                    "raw_current": 25,
                    "possible_modes": (0, 1),
                    "display": "Off/50 Hz (raw 25)",
                    "minimum": 0,
                    "maximum": 2,
                    "step": 1,
                    "detail": "Off and 50 Hz share raw value 25",
                },
            },
        })

    def tearDown(self):
        self.panel.video_view.worker = None
        self.panel.shutdown()
        self.panel.deleteLater()
        self.app.processEvents()

    def test_only_compactconnect_vendor_hardware_controls_are_present(self):
        for legacy_attribute in (
            "camera_gain",
            "camera_brightness",
            "camera_contrast",
            "camera_exposure",
            "camera_roi",
        ):
            with self.subTest(attribute=legacy_attribute):
                self.assertFalse(hasattr(self.panel, legacy_attribute))

        self.assertTrue(self.panel.compactconnect_video_gain.isEnabled())
        self.assertEqual(self.panel.compactconnect_video_gain.value(), 179)
        self.assertEqual(self.panel.compactconnect_video_gain.minimum(), 1)
        self.assertEqual(self.panel.compactconnect_video_gain.maximum(), 255)
        self.assertTrue(self.panel.compactconnect_anti_flicker.isEnabled())
        self.assertFalse(hasattr(self.panel, "write_video_gain_button"))
        self.assertFalse(hasattr(self.panel, "write_anti_flicker_button"))

    def test_target_circle_and_background_are_side_by_side_without_warning(self):
        layout = self.panel.target_circle_group.parentWidget().layout()
        self.assertEqual(layout.indexOf(self.panel.target_circle_group), 0)
        self.assertEqual(layout.indexOf(self.panel.background_group), 1)
        labels = [label.text() for label in self.panel.findChildren(QLabel)]
        self.assertFalse(any(
            "persist in camera EEPROM" in text for text in labels
        ))

    def test_profile_contains_only_software_display_settings(self):
        profile = self.panel.profile_data()

        self.assertNotIn("camera", profile)
        self.assertEqual(set(profile["video_display"]), SOFTWARE_DISPLAY_KEYS)
        self.assertNotIn("video_gain", profile["video_display"])
        self.assertNotIn("anti_flicker_mode", profile["video_display"])
        self.assertNotIn("CompactConnect Video Gain", profile["video_display"])
        self.assertNotIn("CompactConnect Anti-flicker", profile["video_display"])

    def test_software_profile_round_trip_never_queues_hardware_write(self):
        settings = CompactConnectVideoDisplaySettings().with_updates(
            red_gain=1.25,
            brightness=0.8,
            rotation_deg=37,
            mirror_x=False,
            mirror_y=True,
            target_circle_style="dotted",
            target_circle_width=3,
            target_circle_color="#123456",
            background_color="#234567",
            background_circle_color="#345678",
            background_circle_diameter=420,
        ).to_dict()
        self.worker.reset_mock()

        self.panel.load_profile_data({"video_display": settings})

        self.assertEqual(self.panel.video_display_settings(), settings)
        self.assertEqual(self.panel.profile_data()["video_display"], settings)
        self.worker.set_video_display_settings.assert_called_once_with(settings)
        self.worker.set_compactconnect_video_gain.assert_not_called()
        self.worker.set_compactconnect_anti_flicker.assert_not_called()
        self.assertEqual(self.panel.compactconnect_video_gain.value(), 179)

    def test_normal_display_apply_never_queues_hardware_write(self):
        self.worker.reset_mock()

        self.assertTrue(self.panel.apply_video_display_settings())

        self.worker.set_video_display_settings.assert_called_once_with(
            self.panel.video_display_settings()
        )
        self.worker.set_compactconnect_video_gain.assert_not_called()
        self.worker.set_compactconnect_anti_flicker.assert_not_called()

    def test_ambiguous_raw_25_is_displayed_without_claiming_one_mode(self):
        self.assertIn("Off/50 Hz", self.panel.anti_flicker_readback.text())
        self.assertIn(
            "Off and 50 Hz", self.panel.compactconnect_anti_flicker.toolTip()
        )

    def test_gain_change_is_queued_immediately_without_confirmation(self):
        self.worker.reset_mock()
        self.panel.compactconnect_video_gain.setValue(200)

        self.worker.set_compactconnect_video_gain.assert_called_once_with(200)
        self.worker.set_compactconnect_anti_flicker.assert_not_called()
        self.worker.set_video_display_settings.assert_not_called()

    def test_anti_flicker_change_is_queued_immediately_without_confirmation(self):
        self.worker.reset_mock()
        index = self.panel.compactconnect_anti_flicker.findData(2)
        self.panel.compactconnect_anti_flicker.setCurrentIndex(index)

        self.worker.set_compactconnect_anti_flicker.assert_called_once_with(2)
        self.worker.set_compactconnect_video_gain.assert_not_called()
        self.worker.set_video_display_settings.assert_not_called()

    def test_stale_gain_readback_does_not_replace_newer_input(self):
        self.worker.reset_mock()
        self.panel.compactconnect_video_gain.setValue(190)
        self.panel.compactconnect_video_gain.setValue(200)

        self.panel.update_camera_properties({
            "operation": "video_gain_apply",
            "controls": {
                "CompactConnect Video Gain": {
                    "supported": True,
                    "requested": 190,
                    "current": 190,
                    "applied": True,
                },
            },
        })

        self.assertEqual(self.panel.compactconnect_video_gain.value(), 200)
        self.assertEqual(self.panel._latest_vendor_gain_request, 200)


if __name__ == "__main__":
    unittest.main()
