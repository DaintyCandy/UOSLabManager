import unittest
from dataclasses import FrozenInstanceError

import cv2
import numpy as np

from plugins.devices.ctvideo_3m.video_display import (
    CompactConnectVideoDisplaySettings,
    canonical_video_display_profile,
    process_frame,
)
from plugins.devices.ctvideo_3m.video import CTVideoView, CTVideoWorker


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
    "background_color",
    "background_circle_color",
    "background_circle_diameter",
}


class _CV2WithoutOverlay:
    """Delegate image operations to cv2 while suppressing drawn overlays."""

    def __getattr__(self, name):
        return getattr(cv2, name)

    @staticmethod
    def circle(*_args, **_kwargs):
        return None


class CompactConnectVideoDisplayModelTests(unittest.TestCase):
    def test_profile_schema_contains_only_the_fourteen_software_settings(self):
        settings = CompactConnectVideoDisplaySettings()

        self.assertEqual(set(settings.to_dict()), SOFTWARE_DISPLAY_KEYS)
        self.assertEqual(
            set(settings.to_profile()["video_display"]), SOFTWARE_DISPLAY_KEYS
        )
        self.assertNotIn("anti_flicker_mode", settings.to_dict())
        self.assertNotIn("video_gain", settings.to_dict())

    def test_direct_and_nested_profiles_round_trip_canonically(self):
        values = {
            "red_gain": 1.25,
            "green_gain": 0.75,
            "blue_gain": 2.5,
            "brightness": 1.1,
            "rotation_deg": 73,
            "black_and_white": True,
            "mirror_x": False,
            "mirror_y": True,
            "target_circle_style": "dotted",
            "target_circle_width": 3,
            "target_circle_color": "#123456",
            "background_color": "#234567",
            "background_circle_color": "#345678",
            "background_circle_diameter": 420,
        }

        direct = CompactConnectVideoDisplaySettings.from_dict(values)
        nested = CompactConnectVideoDisplaySettings.from_profile(
            {"video_display": values}
        )

        self.assertEqual(direct, nested)
        self.assertEqual(direct.to_dict(), values)
        self.assertEqual(
            canonical_video_display_profile(values),
            {"video_display": values},
        )

    def test_colors_and_style_are_normalized_for_json(self):
        settings = CompactConnectVideoDisplaySettings.from_dict({
            "target_circle_style": " DOTTED ",
            "target_circle_color": "abcdef",
            "background_color": "#a1b2c3",
            "background_circle_color": "010203",
        })

        self.assertEqual(settings.target_circle_style, "dotted")
        self.assertEqual(settings.target_circle_color, "#ABCDEF")
        self.assertEqual(settings.background_color, "#A1B2C3")
        self.assertEqual(settings.background_circle_color, "#010203")

    def test_model_is_immutable_and_updates_return_a_validated_copy(self):
        settings = CompactConnectVideoDisplaySettings()

        with self.assertRaises(FrozenInstanceError):
            settings.rotation_deg = 90
        updated = settings.with_updates(rotation_deg=90, red_gain=1.5)

        self.assertEqual(settings.rotation_deg, 0)
        self.assertEqual(updated.rotation_deg, 90)
        self.assertEqual(updated.red_gain, 1.5)

    def test_vendor_and_legacy_uvc_keys_are_rejected(self):
        for key in (
            "anti_flicker_mode",
            "video_gain",
            "Gain",
            "Contrast",
            "Exposure Absolute",
            "ROI",
        ):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    CompactConnectVideoDisplaySettings.from_dict({key: 1})

    def test_documented_ranges_are_validated(self):
        invalid = (
            ("red_gain", -0.01),
            ("brightness", 10.01),
            ("rotation_deg", 360),
            ("target_circle_width", -1),
            ("target_circle_width", 26),
            ("background_circle_diameter", 99),
            ("background_circle_diameter", 1201),
            ("target_circle_style", "dash-dot"),
            ("target_circle_color", "red"),
        )
        for name, value in invalid:
            with self.subTest(name=name, value=value):
                with self.assertRaises((TypeError, ValueError)):
                    CompactConnectVideoDisplaySettings.from_dict({name: value})


class CompactConnectVideoDisplayProcessorTests(unittest.TestCase):
    def setUp(self):
        self.cv2_without_overlay = _CV2WithoutOverlay()

    @staticmethod
    def settings(**changes):
        return CompactConnectVideoDisplaySettings(
            mirror_x=False,
            mirror_y=False,
            background_circle_diameter=480,
        ).with_updates(**changes)

    def test_processing_is_pure_and_deterministic(self):
        frame = np.arange(120 * 160 * 3, dtype=np.uint8).reshape(120, 160, 3)
        before = frame.copy()
        settings = self.settings()

        first = process_frame(frame, settings, self.cv2_without_overlay)
        second = process_frame(frame, settings, self.cv2_without_overlay)

        np.testing.assert_array_equal(frame, before)
        np.testing.assert_array_equal(first, second)
        self.assertIsNot(first, frame)

    def test_bgr_channels_use_rgb_gains_and_global_brightness(self):
        frame = np.full((120, 160, 3), (10, 20, 30), dtype=np.uint8)
        settings = self.settings(
            red_gain=4.0,
            green_gain=3.0,
            blue_gain=2.0,
            brightness=0.5,
        )

        result = process_frame(frame, settings, self.cv2_without_overlay)

        np.testing.assert_array_equal(result[60, 80], (10, 30, 60))

    def test_black_and_white_produces_equal_channels(self):
        frame = np.full((120, 160, 3), (10, 80, 220), dtype=np.uint8)

        result = process_frame(
            frame,
            self.settings(black_and_white=True),
            self.cv2_without_overlay,
        )

        self.assertEqual(int(result[60, 80, 0]), int(result[60, 80, 1]))
        self.assertEqual(int(result[60, 80, 1]), int(result[60, 80, 2]))

    def test_mirror_axes_match_compactconnect_flags(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        frame[60, 30] = (1, 2, 3)
        frame[60, 129] = (4, 5, 6)
        frame[10, 80] = (7, 8, 9)
        frame[109, 80] = (10, 11, 12)

        horizontal = process_frame(
            frame,
            self.settings(mirror_x=True),
            self.cv2_without_overlay,
        )
        vertical = process_frame(
            frame,
            self.settings(mirror_y=True),
            self.cv2_without_overlay,
        )

        np.testing.assert_array_equal(horizontal[60, 30], (4, 5, 6))
        np.testing.assert_array_equal(vertical[10, 80], (10, 11, 12))

    def test_background_diameter_uses_centered_diameter_plus_twenty_crop(self):
        height, width = 200, 300
        yy, xx = np.indices((height, width), dtype=np.uint16)
        frame = np.stack(
            ((xx % 256), (yy % 256), ((xx + yy) % 256)), axis=2
        ).astype(np.uint8)
        settings = self.settings(background_circle_diameter=100)

        result = process_frame(frame, settings, self.cv2_without_overlay)
        expected_crop = frame[40:160, 90:210]
        expected = cv2.resize(expected_crop, (width, height))

        np.testing.assert_array_equal(result[80:120, 130:170], expected[80:120, 130:170])

    def test_background_circle_color_fills_outside_the_video_aperture(self):
        frame = np.full((200, 300, 3), (10, 20, 30), dtype=np.uint8)
        settings = self.settings(
            background_circle_diameter=100,
            background_circle_color="#123456",
        )

        result = process_frame(frame, settings, cv2)

        np.testing.assert_array_equal(result[0, 0], (0x56, 0x34, 0x12))
        np.testing.assert_array_equal(result[100, 150], (10, 20, 30))


class CTVideoDisplayWorkerContractTests(unittest.TestCase):
    def test_legacy_uvc_public_api_is_removed(self):
        for owner in (CTVideoWorker, CTVideoView):
            for name in ("set_uvc_settings", "set_gain", "set_brightness"):
                with self.subTest(owner=owner.__name__, name=name):
                    self.assertFalse(hasattr(owner, name))

    def test_display_update_is_queued_separately_from_hardware_writes(self):
        worker = CTVideoWorker(
            source=0,
            camera_name="offline display queue test",
        )
        values = CompactConnectVideoDisplaySettings().with_updates(
            red_gain=1.5,
            rotation_deg=45,
            mirror_x=False,
        ).to_dict()

        worker.set_video_display_settings(values)
        display, video_gain, anti_flicker, read_requested = (
            worker._take_requests()
        )

        self.assertEqual(display.to_dict(), values)
        self.assertIsNone(video_gain)
        self.assertIsNone(anti_flicker)
        self.assertFalse(read_requested)

    def test_display_settings_are_validated_before_worker_queueing(self):
        worker = CTVideoWorker(
            source=0,
            camera_name="offline display validation test",
        )

        with self.assertRaises(ValueError):
            worker.set_video_display_settings({"Contrast": 25})

        display, video_gain, anti_flicker, read_requested = (
            worker._take_requests()
        )
        self.assertIsNone(display)
        self.assertIsNone(video_gain)
        self.assertIsNone(anti_flicker)
        self.assertFalse(read_requested)

    def test_persistent_worker_writes_require_confirmation_and_valid_values(self):
        worker = CTVideoWorker(
            source=0,
            camera_name="offline persistent write safety test",
        )

        with self.assertRaises(PermissionError):
            worker.set_compactconnect_video_gain(180)
        with self.assertRaises(PermissionError):
            worker.set_compactconnect_anti_flicker(0)
        with self.assertRaises(ValueError):
            worker.set_compactconnect_video_gain(256, confirmed=True)
        with self.assertRaises(ValueError):
            worker.set_compactconnect_anti_flicker(3, confirmed=True)

        display, video_gain, anti_flicker, read_requested = (
            worker._take_requests()
        )
        self.assertIsNone(display)
        self.assertIsNone(video_gain)
        self.assertIsNone(anti_flicker)
        self.assertFalse(read_requested)


if __name__ == "__main__":
    unittest.main()
