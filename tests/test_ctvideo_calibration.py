import math
import unittest
from unittest.mock import MagicMock, patch

import serial

from plugins.devices.ctvideo_3m.driver import (
    CTVideo3M,
    CalibrationProtocolError,
    CalibrationSnapshot,
    CalibrationStateChangedError,
)


class CTVideoCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.serial_patch = patch("plugins.devices.ctvideo_3m.driver.serial.Serial")
        self.serial_class = self.serial_patch.start()
        self.addCleanup(self.serial_patch.stop)
        self.ser = MagicMock()
        self.ser.is_open = True
        self.serial_class.return_value = self.ser
        self.device = CTVideo3M("COM6")

    def queue_responses(self, *responses):
        self.ser.read.side_effect = list(responses)

    def written_packets(self):
        return [call.args[0] for call in self.ser.write.call_args_list]

    def test_constructor_uses_required_115200_8n1_without_writing(self):
        self.serial_class.assert_called_once_with(
            port="COM6",
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self.ser.write.assert_not_called()

    def test_read_tweak_offset_and_gain_use_read_commands_without_checksum(self):
        self.queue_responses(b"\x04\xD3", b"\x80\x00")
        self.assertEqual(self.device.read_tweak_offset(), 23.5)
        self.assertEqual(self.device.read_tweak_gain(), 1.0)
        self.assertEqual(self.written_packets(), [b"\x26", b"\x27"])

    def test_set_offset_and_gain_send_exact_packets_and_verify_echo(self):
        self.queue_responses(b"\x03\xE8", b"\xA0\x00")
        self.assertEqual(
            self.device.set_tweak_offset(0.0, confirmed=True), 0.0
        )
        self.assertEqual(
            self.device.set_tweak_gain(1.25, confirmed=True), 1.25
        )
        self.assertEqual(
            self.written_packets(),
            [b"\xA6\x03\xE8\x4D", b"\xA7\xA0\x00\x07"],
        )

    def test_calibration_write_requires_explicit_confirmation(self):
        with self.assertRaises(PermissionError):
            self.device.set_tweak_offset(0.0)
        with self.assertRaises(PermissionError):
            self.device.set_tweak_gain(1.0)
        expected = CalibrationSnapshot(1, 1, 0.0, 1.0, 1000, 32768)
        with self.assertRaises(PermissionError):
            self.device.apply_calibration(expected, {"tweak_offset_C": 1.0})
        self.ser.write.assert_not_called()

    def test_set_echo_mismatch_is_reported_and_never_retried(self):
        self.queue_responses(b"\x03\xE9")
        with self.assertRaises(CalibrationProtocolError):
            self.device.set_tweak_offset(0.0, confirmed=True)
        self.assertEqual(self.written_packets(), [b"\xA6\x03\xE8\x4D"])

    def test_short_set_response_is_not_retried(self):
        self.queue_responses(b"")
        with self.assertRaises(TimeoutError):
            self.device.set_tweak_gain(1.0, confirmed=True)
        self.assertEqual(self.written_packets(), [b"\xA7\x80\x00\x27"])

    def test_read_timeout_may_retry(self):
        self.queue_responses(b"", b"\x03\xE8")
        with patch("plugins.devices.ctvideo_3m.driver.time.sleep"):
            self.assertEqual(self.device.read_tweak_offset(), 0.0)
        self.assertEqual(self.written_packets(), [b"\x26", b"\x26"])

    def test_non_finite_and_out_of_range_values_do_not_touch_serial(self):
        invalid_offsets = (math.nan, math.inf, -100.1, 6453.6)
        invalid_gains = (math.nan, math.inf, -0.0001, 2.0)
        for value in invalid_offsets:
            with self.subTest(offset=value):
                with self.assertRaises(ValueError):
                    self.device.set_tweak_offset(value, confirmed=True)
        for value in invalid_gains:
            with self.subTest(gain=value):
                with self.assertRaises(ValueError):
                    self.device.set_tweak_gain(value, confirmed=True)
        self.ser.write.assert_not_called()

    def test_apply_calibration_checks_snapshot_writes_once_and_reads_back(self):
        expected = CalibrationSnapshot(42, 0x0102, 0.0, 1.0, 0x03E8, 0x8000)
        self.queue_responses(
            b"\x00\x00\x2A", b"\x01\x02", b"\x03\xE8", b"\x80\x00",
            b"\x03\xED", b"\xA0\x00",
            b"\x00\x00\x2A", b"\x01\x02", b"\x03\xED", b"\xA0\x00",
        )
        result = self.device.apply_calibration(
            expected,
            {"tweak_offset_C": 0.5, "tweak_gain": 1.25},
            confirmed=True,
        )
        self.assertTrue(result.verified)
        self.assertEqual(
            result.statuses,
            {"tweak_offset_C": "verified", "tweak_gain": "verified"},
        )
        set_packets = [
            packet for packet in self.written_packets()
            if packet[0] in (CTVideo3M.SET_TWEAK_OFFSET, CTVideo3M.SET_TWEAK_GAIN)
        ]
        self.assertEqual(
            set_packets,
            [b"\xA6\x03\xED\x48", b"\xA7\xA0\x00\x07"],
        )

    def test_changed_snapshot_blocks_all_set_commands(self):
        expected = CalibrationSnapshot(42, 0x0102, 0.0, 1.0, 0x03E8, 0x8000)
        self.queue_responses(
            b"\x00\x00\x2A", b"\x01\x02", b"\x03\xE9", b"\x80\x00"
        )
        with self.assertRaises(CalibrationStateChangedError):
            self.device.apply_calibration(
                expected, {"tweak_offset_C": 0.5}, confirmed=True
            )
        self.assertFalse(any(
            packet[0] in (CTVideo3M.SET_TWEAK_OFFSET, CTVideo3M.SET_TWEAK_GAIN)
            for packet in self.written_packets()
        ))

    def test_temperature_polling_never_reads_calibration_registers(self):
        self.queue_responses(b"\x03\xE8", b"\x03\xE8", b"\x03\xE8", b"\x03\xE8")
        self.device.read_all()
        self.assertEqual(
            self.written_packets(), [b"\x01", b"\x81", b"\x02", b"\x03"]
        )


if __name__ == "__main__":
    unittest.main()
