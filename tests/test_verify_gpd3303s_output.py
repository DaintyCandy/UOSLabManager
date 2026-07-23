import sys
import unittest
from unittest.mock import MagicMock, patch

from scripts.verify_gpd3303s_output import main as verify_main


class TestVerifyGPD3303SOutput(unittest.TestCase):
    def setUp(self):
        self.serial_patch = patch("plugins.devices.gpd3303s.driver.serial.Serial")
        self.mock_serial_class = self.serial_patch.start()
        self.addCleanup(self.serial_patch.stop)

        self.ser = MagicMock()
        self.ser.is_open = True
        self.mock_serial_class.return_value = self.ser

    def test_out0_always_sent_in_finally(self):
        self.ser.read_until.side_effect = [
            b"GW INSTEK,GPD-3303S,1234\r",
            b"00000000\r",
            b"1.000V\r",
            b"0.050A\r",
            b"0.000V\r",
            b"0.050A\r",
            b"00000000\r",
            b"1.000V\r",
            b"0.050A\r",
            b"0.000V\r",
            b"0.050A\r",
            b"00000000\r",
            b"00000000\r",
        ]
        argv = ["verify_gpd3303s_output.py", "--port", "COM1", "--confirm-output-test"]
        with patch.object(sys, "argv", argv), patch("scripts.verify_gpd3303s_output.time.sleep", return_value=None):
            result = verify_main()

        self.assertEqual(result, 0)
        out_commands = [call.args[0].decode("ascii") for call in self.ser.write.call_args_list]
        self.assertEqual(out_commands.count("OUT0\n"), 3)
        self.assertEqual(out_commands.count("OUT1\n"), 1)

    def test_exits_without_out1_when_no_confirm_flag(self):
        self.ser.read_until.return_value = b"GW INSTEK,GPD-3303S,1234\r"
        argv = ["verify_gpd3303s_output.py", "--port", "COM1"]
        with patch.object(sys, "argv", argv):
            result = verify_main()

        self.assertEqual(result, 2)
        self.assertFalse(any(call.args[0] == b"OUT1\n" for call in self.ser.write.call_args_list))

    def test_unexpected_identity_exits_without_out1(self):
        self.ser.read_until.return_value = b"SOMEOTHER,MODEL,1234\r"
        argv = ["verify_gpd3303s_output.py", "--port", "COM1", "--confirm-output-test"]
        with patch.object(sys, "argv", argv):
            result = verify_main()

        self.assertEqual(result, 1)
        self.assertFalse(any(call.args[0] == b"OUT1\n" for call in self.ser.write.call_args_list))

    def test_output_is_off_after_initial_out0(self):
        self.ser.read_until.side_effect = [
            b"GW INSTEK,GPD-3303S,1234\r",
            b"00000000\r",
            b"1.000V\r",
            b"0.050A\r",
            b"0.000V\r",
            b"0.050A\r",
            b"00000000\r",
            b"1.000V\r",
            b"0.050A\r",
            b"0.000V\r",
            b"0.050A\r",
            b"00000000\r",
        ]
        argv = ["verify_gpd3303s_output.py", "--port", "COM1", "--confirm-output-test"]
        with patch.object(sys, "argv", argv), patch("scripts.verify_gpd3303s_output.time.sleep", return_value=None):
            result = verify_main()

        self.assertEqual(result, 0)
        out_commands = [call.args[0].decode("ascii") for call in self.ser.write.call_args_list]
        self.assertEqual(out_commands[1], "OUT0\n")
        self.assertEqual(out_commands[2], "STATUS?\n")

    def test_final_out0_sent_on_exception(self):
        self.ser.read_until.side_effect = [
            b"GW INSTEK,GPD-3303S,1234\r",
            b"00000000\r",
            b"1.000V\r",
            b"0.050A\r",
            b"runtime error\r",
        ]
        self.ser.write.side_effect = [None, None, RuntimeError("write failed")]
        argv = ["verify_gpd3303s_output.py", "--port", "COM1", "--confirm-output-test"]
        with patch.object(sys, "argv", argv), patch("scripts.verify_gpd3303s_output.time.sleep", return_value=None):
            result = verify_main()

        self.assertNotEqual(result, 0)
        self.assertTrue(any(call.args[0] == b"OUT0\n" for call in self.ser.write.call_args_list))


if __name__ == "__main__":
    unittest.main()
