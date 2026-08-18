import unittest
from unittest.mock import MagicMock, patch

from plugins.devices.lakeshore331.plugin import LakeShore331Plugin
from plugins.devices.zup36_12.driver import ZUP36_12


class ConnectionSettingsPreservedTests(unittest.TestCase):
    @patch("plugins.devices.lakeshore331.driver.LakeShore331")
    def test_ls331_plugin_connect_does_not_write_initial_settings(self, driver_class):
        device = driver_class.return_value

        connected = LakeShore331Plugin().connect("COM3")

        self.assertIs(connected, device)
        device.write.assert_not_called()
        device.set_ramp.assert_not_called()
        device.set_control_mode.assert_not_called()

    @patch("plugins.devices.zup36_12.driver.time.sleep")
    @patch("plugins.devices.zup36_12.driver.serial.Serial")
    def test_zup_connect_only_identifies_and_preserves_operating_state(
        self, serial_class, _sleep,
    ):
        serial_port = MagicMock()
        serial_port.is_open = True
        serial_port.read_until.return_value = b"ZUP36-12\n"
        serial_class.return_value = serial_port

        device = ZUP36_12("COM4")

        transmitted = b"".join(
            call.args[0] for call in serial_port.write.call_args_list
        )
        self.assertIn(b":MDL?;", transmitted)
        self.assertNotIn(b":RMT1;", transmitted)
        self.assertNotIn(b":AST0;", transmitted)
        self.assertNotIn(b":OUT0;", transmitted)
        self.assertNotIn(b":VOL", transmitted)
        self.assertNotIn(b":CUR", transmitted)
        # Avoid exercising the intentionally safe disconnect behavior here.
        device.ser.is_open = False


if __name__ == "__main__":
    unittest.main()
