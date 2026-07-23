import unittest
from unittest.mock import MagicMock, patch

import serial
from plugins.devices.gpd3303s.driver import GPD3303S


class TestGPD3303SDriver(unittest.TestCase):
    def setUp(self):
        self.serial_patch = patch("plugins.devices.gpd3303s.driver.serial.Serial")
        self.mock_serial_class = self.serial_patch.start()
        self.addCleanup(self.serial_patch.stop)
        self.ser = MagicMock()
        self.ser.is_open = True
        self.ser.read_until.return_value = b"ON\r"
        self.mock_serial_class.return_value = self.ser

    def test_init_uses_serial_parameters_without_writing(self):
        device = GPD3303S("COM1")
        self.mock_serial_class.assert_called_once_with(
            port="COM1",
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
            xonxoff=False,
            rtscts=False,
        )
        self.assertFalse(self.ser.write.called)

    def test_constructor_does_not_send_out0_by_default(self):
        GPD3303S("COM1")
        self.assertFalse(any(call.args[0].startswith(b"OUT0") or call.args[0].startswith(b"OUT1") for call in self.ser.write.call_args_list))

    def test_write_and_query_use_terminators(self):
        device = GPD3303S("COM1", write_termination="\n", read_termination="\n")
        self.ser.read_until.return_value = b"OK\n"
        device.write("TEST")
        self.ser.write.assert_called_with(b"TEST\n")
        self.ser.read_until.assert_not_called()
        response = device.query("VSET1?")
        self.assertEqual(response, "OK")
        self.ser.write.assert_called_with(b"VSET1?\n")

    def test_channel_voltage_current_validation(self):
        device = GPD3303S("COM1")
        with self.assertRaises(ValueError):
            device.set_channel_voltage("CH1", 30.1)
        with self.assertRaises(ValueError):
            device.set_channel_current("CH1", 3.1)

    def test_output_on_requires_both_channels_configured(self):
        device = GPD3303S("COM1")
        device.set_channel_voltage("CH1", 5.0)
        device.set_channel_current("CH1", 0.5)
        with self.assertRaises(RuntimeError):
            device.output_on()

    def test_output_off_sends_command(self):
        device = GPD3303S("COM1")
        device.output_off()
        self.ser.write.assert_called_with(b"OUT0\n")

    def test_close_sends_output_off_when_enabled(self):
        device = GPD3303S("COM1", output_off_on_close=True)
        device.close()
        self.ser.write.assert_called_with(b"OUT0\n")
        self.ser.close.assert_called_once()

    def test_identify_validates_idn_response(self):
        self.ser.read_until.return_value = b"GW INSTEK,GPD-3303S,1234\r"
        device = GPD3303S("COM1")
        identity = device.identify()
        self.assertIn("GW INSTEK", identity)
        self.assertIn("GPD-3303S", identity)

    def test_read_settings_parses_channel_settings(self):
        self.ser.read_until.side_effect = [
            b"5.000V\r",
            b"1.000A\r",
            b"10.000V\r",
            b"0.500A\r",
            b"00011010\r",
        ]
        device = GPD3303S("COM1")
        settings = device.read_settings()
        self.assertEqual(settings["CH1_voltage_setpoint"], 5.0)
        self.assertEqual(settings["CH1_current_setpoint"], 1.0)
        self.assertEqual(settings["CH2_voltage_setpoint"], 10.0)
        self.assertEqual(settings["CH2_current_setpoint"], 0.5)
        self.assertFalse(settings["output_on"])
        self.assertEqual(settings["status_raw"], "00011010")
        self.assertEqual(settings["status_int"], 26)
        self.assertEqual(settings["ch1_mode"], "CC")
        self.assertEqual(settings["ch2_mode"], "CV")
        self.assertEqual(settings["beep"], True)
        self.assertEqual(settings["tracking_mode"], "Independent")

    def test_read_monitoring_returns_channel_values(self):
        self.ser.read_until.side_effect = [
            b"5.000V\r",
            b"0.500A\r",
            b"10.000V\r",
            b"1.000A\r",
            b"00011010\r",
        ]
        device = GPD3303S("COM1")
        state = device.read_monitoring()
        self.assertEqual(state["CH1_voltage_V"], 5.0)
        self.assertEqual(state["CH1_current_A"], 0.5)
        self.assertEqual(state["CH2_voltage_V"], 10.0)
        self.assertEqual(state["CH2_current_A"], 1.0)
        self.assertFalse(state["output_on"])
        self.assertEqual(state["status_raw"], "00011010")
        self.assertEqual(state["status_int"], 26)
        self.assertEqual(state["tracking_mode"], "Independent")

    def test_status_output_true_when_bit6_set(self):
        self.ser.read_until.return_value = b"01011010\r"
        device = GPD3303S("COM1")
        result = device.read_status()
        self.assertTrue(result["output_on"])
        self.assertEqual(result["status_int"], 90)

    def test_status_output_false_when_bit6_clear(self):
        self.ser.read_until.return_value = b"00011010\r"
        device = GPD3303S("COM1")
        result = device.read_status()
        self.assertFalse(result["output_on"])
        self.assertEqual(result["status_int"], 26)

    def test_tracking_mode_independent(self):
        self.ser.read_until.return_value = b"00011010\r"
        device = GPD3303S("COM1")
        result = device.read_status()
        self.assertEqual(result["tracking_mode"], "Independent")

    def test_tracking_mode_series(self):
        self.ser.read_until.return_value = b"00011110\r"
        device = GPD3303S("COM1")
        result = device.read_status()
        self.assertEqual(result["tracking_mode"], "Series")

    def test_tracking_mode_parallel(self):
        self.ser.read_until.return_value = b"00010110\r"
        device = GPD3303S("COM1")
        result = device.read_status()
        self.assertEqual(result["tracking_mode"], "Parallel")

    def test_parse_numeric_with_unit_raises_on_invalid_unit(self):
        device = GPD3303S("COM1")
        with self.assertRaises(ValueError):
            device._parse_numeric_with_unit("5.000X", "V")

    def test_parse_numeric_with_unit_raises_on_invalid_number(self):
        device = GPD3303S("COM1")
        with self.assertRaises(ValueError):
            device._parse_numeric_with_unit("ABCV", "V")

    def test_set_channel_settings_update_internal_state(self):
        device = GPD3303S("COM1")
        device.set_channel_voltage("CH1", 3.0)
        device.set_channel_current("CH1", 1.0)
        self.assertEqual(device.channel_settings["CH1"]["voltage"], 3.0)
        self.assertEqual(device.channel_settings["CH1"]["current"], 1.0)

    def test_output_on_with_valid_settings_writes_command(self):
        device = GPD3303S("COM1")
        device.set_channel_voltage("CH1", 5.0)
        device.set_channel_current("CH1", 0.5)
        device.set_channel_voltage("CH2", 10.0)
        device.set_channel_current("CH2", 1.0)
        device.output_on()
        self.assertEqual(self.ser.write.call_args_list[-1], ((b"OUT1\n",),))


if __name__ == "__main__":
    unittest.main()
