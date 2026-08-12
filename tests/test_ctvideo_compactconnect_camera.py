import unittest
from unittest import mock

from plugins.devices.ctvideo_3m.compactconnect_camera import (
    EEPROM_VIDEO_7,
    CompactConnectAntiFlickerSnapshot,
    CompactConnectCameraController,
    CompactConnectCameraError,
)


class CompactConnectAntiFlickerSafetyTests(unittest.TestCase):
    """No persistent anti-flicker write may happen implicitly."""

    def setUp(self):
        self.controller = CompactConnectCameraController(
            friendly_name="CTvideo offline anti-flicker test"
        )

    def test_write_requires_explicit_acknowledgement_before_device_access(self):
        with mock.patch.object(self.controller, "_require_open") as require_open:
            for kwargs in ({}, {"acknowledged": False}):
                with self.subTest(kwargs=kwargs):
                    with self.assertRaises(PermissionError):
                        self.controller.set_compactconnect_anti_flicker(1, **kwargs)

        require_open.assert_not_called()

    def test_acknowledgement_is_keyword_only(self):
        with mock.patch.object(self.controller, "_require_open") as require_open:
            with self.assertRaises(TypeError):
                self.controller.set_compactconnect_anti_flicker(1, True)

        require_open.assert_not_called()

    def test_invalid_modes_are_rejected_before_device_access(self):
        cases = (
            (True, TypeError),
            (1.0, TypeError),
            ("1", TypeError),
            (-1, ValueError),
            (3, ValueError),
        )
        with mock.patch.object(self.controller, "_require_open") as require_open:
            for mode, exception_type in cases:
                with self.subTest(mode=mode):
                    with self.assertRaises(exception_type):
                        self.controller.set_compactconnect_anti_flicker(
                            mode, acknowledged=True
                        )

        require_open.assert_not_called()

    def test_all_documented_modes_pass_validation(self):
        access_attempt = RuntimeError("native access attempted")
        with mock.patch.object(
            self.controller, "_require_open", side_effect=access_attempt
        ) as require_open:
            for mode in (0, 1, 2):
                with self.subTest(mode=mode):
                    with self.assertRaisesRegex(
                        RuntimeError, "native access attempted"
                    ):
                        self.controller.set_compactconnect_anti_flicker(
                            mode, acknowledged=True
                        )

        self.assertEqual(require_open.call_count, 3)


class CompactConnectAntiFlickerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.controller = CompactConnectCameraController(
            friendly_name="CTvideo offline anti-flicker protocol test"
        )

    @staticmethod
    def snapshot(raw_value):
        block = bytes((0, 5, raw_value, 76, 2, 1, 243, 5))
        return CompactConnectAntiFlickerSnapshot(
            raw_value=raw_value,
            block=block,
        )

    def test_read_uses_video_page_seven_byte_two(self):
        block = bytes((0, 5, 30, 76, 2, 1, 243, 5))
        with mock.patch.object(self.controller, "_require_open"), mock.patch.object(
            self.controller, "_read_eeprom_block", return_value=block
        ) as read_block:
            snapshot = self.controller.read_compactconnect_anti_flicker()

        read_block.assert_called_once_with(EEPROM_VIDEO_7)
        self.assertEqual(snapshot.raw_value, 30)
        self.assertEqual(snapshot.possible_modes, (2,))

    def test_raw_25_reports_the_documented_off_or_50hz_ambiguity(self):
        snapshot = self.snapshot(25)

        self.assertEqual(snapshot.possible_modes, (0, 1))
        self.assertIn("Off", snapshot.description)
        self.assertIn("50 Hz", snapshot.description)

    def test_equivalent_raw_value_skips_eeprom_write(self):
        before = self.snapshot(25)
        with mock.patch.object(self.controller, "_require_open"), mock.patch.object(
            self.controller,
            "read_compactconnect_anti_flicker",
            return_value=before,
        ), mock.patch.object(self.controller, "_write_eeprom_block") as write_block:
            result = self.controller.set_compactconnect_anti_flicker(
                1, acknowledged=True
            )

        self.assertTrue(result.verified)
        self.assertEqual(result.requested_raw, 25)
        self.assertIs(result.before, result.after)
        write_block.assert_not_called()

    def test_60hz_patches_only_the_indoor_byte_and_reads_back(self):
        before = self.snapshot(25)
        after = self.snapshot(30)
        with mock.patch.object(self.controller, "_require_open"), mock.patch.object(
            self.controller,
            "read_compactconnect_anti_flicker",
            side_effect=(before, after),
        ) as read_setting, mock.patch.object(
            self.controller, "_write_eeprom_block"
        ) as write_block:
            result = self.controller.set_compactconnect_anti_flicker(
                2, acknowledged=True
            )

        expected = bytearray(before.block)
        expected[2] = 30
        write_block.assert_called_once_with(EEPROM_VIDEO_7, bytes(expected))
        self.assertEqual(read_setting.call_count, 2)
        self.assertEqual(result.requested_mode, 2)
        self.assertEqual(result.requested_raw, 30)
        self.assertTrue(result.verified)

    def test_failed_write_is_not_retried(self):
        before = self.snapshot(25)
        with mock.patch.object(self.controller, "_require_open"), mock.patch.object(
            self.controller,
            "read_compactconnect_anti_flicker",
            return_value=before,
        ), mock.patch.object(
            self.controller,
            "_write_eeprom_block",
            side_effect=RuntimeError("simulated write failure"),
        ) as write_block:
            with self.assertRaises(CompactConnectCameraError):
                self.controller.set_compactconnect_anti_flicker(
                    2, acknowledged=True
                )

        self.assertEqual(write_block.call_count, 1)


if __name__ == "__main__":
    unittest.main()
