import unittest
from unittest import mock

from plugins.devices.ctvideo_3m.compactconnect_camera import (
    KSPROPERTY_TYPE_GET,
    KSPROPERTY_TYPE_SET,
    CompactConnectVideoGainSnapshot,
    CompactConnectCameraController,
)


class CompactConnectVideoGainSafetyTests(unittest.TestCase):
    """Safety contract for the vendor EEPROM-backed product setting.

    ``CompactConnect Video Gain`` is the product's YTarget setting.  It is not
    the standard UVC/DirectShow ``Gain`` control.  These tests deliberately use
    a closed controller so they can run on every platform and prove that
    rejected writes cannot reach the native camera path.
    """

    def setUp(self):
        self.controller = CompactConnectCameraController(
            friendly_name="CTvideo offline safety test"
        )

    def test_write_requires_explicit_acknowledgement_before_device_access(self):
        with mock.patch.object(self.controller, "_require_open") as require_open:
            with self.assertRaises(PermissionError):
                self.controller.set_compactconnect_video_gain(4)
            with self.assertRaises(PermissionError):
                self.controller.set_compactconnect_video_gain(
                    4, acknowledged=False
                )

        require_open.assert_not_called()

    def test_acknowledgement_is_keyword_only(self):
        with mock.patch.object(self.controller, "_require_open") as require_open:
            with self.assertRaises(TypeError):
                self.controller.set_compactconnect_video_gain(4, True)

        require_open.assert_not_called()

    def test_invalid_values_are_rejected_before_device_access(self):
        cases = (
            (True, TypeError),
            (1.0, TypeError),
            ("4", TypeError),
            (0, ValueError),
            (256, ValueError),
        )
        with mock.patch.object(self.controller, "_require_open") as require_open:
            for value, exception_type in cases:
                with self.subTest(value=value):
                    with self.assertRaises(exception_type):
                        self.controller.set_compactconnect_video_gain(
                            value, acknowledged=True
                        )

        require_open.assert_not_called()

    def test_boundary_values_pass_safety_validation(self):
        access_attempt = RuntimeError("native access attempted")
        with mock.patch.object(
            self.controller, "_require_open", side_effect=access_attempt
        ) as require_open:
            for value in (1, 255):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(
                        RuntimeError, "native access attempted"
                    ):
                        self.controller.set_compactconnect_video_gain(
                            value, acknowledged=True
                        )

        self.assertEqual(require_open.call_count, 2)


class CompactConnectVideoGainProtocolTests(unittest.TestCase):
    def setUp(self):
        self.controller = CompactConnectCameraController(
            friendly_name="CTvideo offline protocol test"
        )

    @staticmethod
    def snapshot(value=179):
        complement = max(255 - value, 10)
        return CompactConnectVideoGainSnapshot(
            value=value,
            complement=complement,
            blocks=(
                (0x0800, bytes((15, value, 25, 8, 4, 8, 8, 0))),
                (0x0808, bytes((7, 7, 0, 1, 250, 16, 0, 32))),
                (0x0810, bytes((0, 192, 5, 0, 5, 0, 5, 5))),
                (0x0838, bytes((0, 5, 25, complement, 2, 1, 243, 5))),
            ),
        )

    def test_eeprom_read_uses_address_latch_then_ten_byte_get(self):
        raw = bytes.fromhex("0f b3 19 08 04 08 08 00 aa bb")
        with mock.patch.object(
            self.controller,
            "_xu_property",
            side_effect=(b"", raw),
        ) as property_call:
            block = self.controller._read_eeprom_block(0x0800)

        self.assertEqual(block, raw[:8])
        self.assertEqual(property_call.call_args_list, [
            mock.call(
                5, KSPROPERTY_TYPE_SET,
                payload=bytes.fromhex("00 08 00 00"),
            ),
            mock.call(7, KSPROPERTY_TYPE_GET, output_size=10),
        ])

    def test_eeprom_write_payload_matches_compactconnect_commit_protocol(self):
        block = bytes.fromhex("07 07 00 01 fa 10 00 20")
        with mock.patch.object(
            self.controller, "_xu_property"
        ) as property_call:
            self.controller._write_eeprom_block(0x0808, block)

        self.assertEqual(property_call.call_args_list, [
            mock.call(
                8, KSPROPERTY_TYPE_SET,
                payload=bytes.fromhex("07 07 00 01 fa 10 00 20 08 00"),
            ),
            mock.call(
                8, KSPROPERTY_TYPE_SET,
                payload=bytes.fromhex("00 00 00 00 00 00 00 20 00 08"),
            ),
        ])

    def test_gain_patch_matches_camsetytarget_eeprom_offsets(self):
        before = self.snapshot(179)
        patched = dict(
            self.controller._patched_video_gain_blocks(before, 200)
        )
        self.assertEqual(patched[0x0800][1], 200)
        self.assertEqual(patched[0x0838][3], 55)
        self.assertEqual(patched[0x0808][5], 16)
        self.assertEqual(patched[0x0808][7], 32)
        self.assertEqual(patched[0x0810][1:7], bytes((192, 5, 0, 5, 0, 5)))

    def test_same_value_skips_all_eeprom_writes(self):
        before = self.snapshot(179)
        with mock.patch.object(self.controller, "_require_open"), mock.patch.object(
            self.controller, "read_compactconnect_video_gain", return_value=before
        ), mock.patch.object(
            self.controller, "_write_eeprom_block"
        ) as write_block:
            result = self.controller.set_compactconnect_video_gain(
                179, acknowledged=True
            )

        self.assertTrue(result.verified)
        self.assertIs(result.before, result.after)
        write_block.assert_not_called()


if __name__ == "__main__":
    unittest.main()
