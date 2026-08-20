import unittest

from core.plugin_manager import AlarmRule, DevicePlugin, SafeAction


class CapabilityDevice:
    def __init__(self):
        self.calls = []

    def output_off(self):
        self.calls.append(("output_off",))
        raise OSError("offline")

    def set_value(self, value):
        self.calls.append(("set_value", value))


class CapabilityPlugin(DevicePlugin):
    device_id = "CAPABILITY"
    display_name = "Capability Device"
    safe_actions = (
        SafeAction("output_off"),
        SafeAction("set_value", (0.0,)),
    )

    def connect(self, connection):
        return CapabilityDevice()


class PluginCapabilityTests(unittest.TestCase):
    def test_safe_state_attempts_every_action_and_aggregates_errors(self):
        device = CapabilityDevice()

        with self.assertRaisesRegex(RuntimeError, "output_off: offline"):
            CapabilityPlugin().enter_safe_state(device)

        self.assertEqual(
            device.calls,
            [("output_off",), ("set_value", 0.0)],
        )

    def test_alarm_rule_distinguishes_normal_and_active_values(self):
        rule = AlarmRule(
            "status", message="{device}: {value}",
            normal_values=(None, "OK"),
        )

        self.assertFalse(rule.is_active(None))
        self.assertFalse(rule.is_active("OK"))
        self.assertTrue(rule.is_active("FAULT"))
        self.assertEqual(rule.format_message("Supply", "FAULT"), "Supply: FAULT")


if __name__ == "__main__":
    unittest.main()
