import unittest
from unittest.mock import MagicMock, patch

from plugins.devices.zup36_12.driver import ZUP36_12


VALID_STATUS = b"AV00.00SV00.00AA00.000SA01.000OS00000000AL00000PS000000\r\n"


class ZUPConnectionTests(unittest.TestCase):
    @patch("plugins.devices.zup36_12.driver.time.sleep")
    @patch("plugins.devices.zup36_12.driver.serial.Serial")
    def test_verified_connection_uses_com4_and_official_serial_settings(
        self, serial_class, _sleep,
    ):
        serial_port = MagicMock()
        serial_port.is_open = True
        serial_port.read_until.side_effect = [b"TDK-Lambda ZUP(36V-12A)\r\n", VALID_STATUS]
        serial_class.return_value = serial_port

        device = ZUP36_12.connect_verified(" COM4 ")

        serial_class.assert_called_once_with(
            port="COM4", baudrate=9600, bytesize=8, parity="N",
            stopbits=1.0, timeout=2.0, write_timeout=2.0,
            xonxoff=True, rtscts=False, dsrdtr=False,
        )
        self.assertEqual(device.get_port(), str(serial_port.port))
        self.assertEqual(device.get_verified_settings()["current"], 1.0)
        transmitted = b"".join(
            call.args[0] for call in serial_port.write.call_args_list
        )
        self.assertIn(b":ADR01;", transmitted)
        self.assertIn(b":MDL?;", transmitted)
        self.assertIn(b":STT?;", transmitted)
        device.close_port()

    @patch("plugins.devices.zup36_12.driver.time.sleep")
    @patch("plugins.devices.zup36_12.driver.serial.Serial")
    def test_failed_verification_releases_com4_without_changing_output(
        self, serial_class, _sleep,
    ):
        serial_port = MagicMock()
        serial_port.is_open = True
        serial_port.read_until.return_value = b""
        serial_class.return_value = serial_port

        with self.assertRaisesRegex(ConnectionError, "RS232 mode"):
            ZUP36_12.connect_verified("COM4")

        serial_port.close.assert_called_once_with()
        transmitted = b"".join(
            call.args[0] for call in serial_port.write.call_args_list
        )
        self.assertNotIn(b":OUT0;", transmitted)
        self.assertNotIn(b":VOL", transmitted)
        self.assertNotIn(b":CUR", transmitted)

    def test_address_zero_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 31"):
            ZUP36_12("COM4", address=0)


if __name__ == "__main__":
    unittest.main()
