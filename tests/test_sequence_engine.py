import threading
import time
import unittest

from core.plugin_manager import DevicePlugin, RecipeMigration, SequenceCommand
from core.sequence_engine import (
    SYSTEM_DEVICE, SequenceEngine, SequenceState,
)


class FakeDevice:
    def __init__(self):
        self.values = []

    def set_value(self, value):
        self.values.append(value)


def execute_value(device, value, _context):
    device.set_value(value)


class FakePlugin(DevicePlugin):
    device_id = "FAKE"
    display_name = "Fake Device"
    sequence_aliases = ("OLD_FAKE",)
    recipe_migrations = (
        RecipeMigration(
            command="Legacy Wait", target_device="SYSTEM",
            target_command="Wait Time", transform=lambda value: value * 2,
        ),
    )
    sequence_commands = (
        SequenceCommand(
            key="Set Value", label="Set Value", unit="V",
            minimum=0.0, maximum=10.0, executor=execute_value,
        ),
    )

    def connect(self, connection):
        return FakeDevice()


class FakeManager:
    def __init__(self):
        self.device = FakeDevice()
        self.latest = {}
        self.connected = set()

    def get_device(self, device_id):
        return self.device if device_id == "FAKE" else None

    def get_metrics(self, device_id):
        return {
            "connected": device_id in self.connected,
            "age_ms": 0.0 if device_id in self.connected else None,
        }

    def get_latest(self, device_id):
        return dict(self.latest.get(device_id, {}))


class SequenceEngineTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeManager()
        self.plugin = FakePlugin()
        self.engine = SequenceEngine(
            self.manager, {self.plugin.device_id: self.plugin}, poll_interval=0.01
        )

    def test_device_alias_is_normalized_and_command_is_plugin_dispatched(self):
        steps = self.engine.validate_recipe({
            "schema_version": 1,
            "steps": [{"dev": "OLD_FAKE", "cmd": "Set Value", "val": 4}],
        })
        self.assertEqual(steps[0]["dev"], "FAKE")
        self.engine.load(steps)
        result = self.engine.run()
        self.assertEqual(result.state, SequenceState.COMPLETED)
        self.assertEqual(self.manager.device.values, [4.0])

    def test_plugin_metadata_rejects_out_of_range_recipe_value(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 10"):
            self.engine.validate_recipe({
                "schema_version": 1,
                "steps": [{"dev": "FAKE", "cmd": "Set Value", "val": 11}],
            })

    def test_plugin_migrates_a_legacy_recipe_without_core_device_knowledge(self):
        steps = self.engine.validate_recipe({
            "schema_version": 1,
            "steps": [{"dev": "OLD_FAKE", "cmd": "Legacy Wait", "val": 3}],
        })
        self.assertEqual(steps, [{
            "dev": SYSTEM_DEVICE, "cmd": "Wait Time", "val": 6.0,
        }])

    def test_stop_interrupts_wait_without_waiting_for_timeout(self):
        self.engine.load([{
            "dev": SYSTEM_DEVICE, "cmd": "Wait Time", "val": 60.0,
        }])
        result = {}
        thread = threading.Thread(
            target=lambda: result.setdefault("value", self.engine.run())
        )
        thread.start()
        deadline = time.monotonic() + 1.0
        while self.engine.state != SequenceState.WAITING and time.monotonic() < deadline:
            time.sleep(0.005)
        started = time.monotonic()
        self.engine.stop()
        thread.join(1.0)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(result["value"].state, SequenceState.STOPPED)

    def test_system_callbacks_and_wait_condition_run_in_core(self):
        markers = []
        recording = []
        self.manager.connected.add("SENSOR")
        self.manager.latest["SENSOR"] = {"temperature": 101.0}
        self.engine.configure_callbacks(
            marker_action=markers.append,
            recording_action=lambda enabled: recording.append(enabled) or enabled,
        )
        condition = {
            "label": "Temperature", "device": "SENSOR", "key": "temperature",
            "unit": "K", "operator": ">=", "target": 100.0,
            "tolerance": 0.0, "stable_s": 0.0, "timeout_s": 1.0,
            "on_timeout": "stop",
        }
        self.engine.load([
            {"dev": SYSTEM_DEVICE, "cmd": "Start Recording", "val": 0},
            {"dev": SYSTEM_DEVICE, "cmd": "Log Marker", "val": "ready"},
            {"dev": SYSTEM_DEVICE, "cmd": "Wait Until", "val": condition},
        ])
        result = self.engine.run()
        self.assertEqual(result.state, SequenceState.COMPLETED)
        self.assertEqual(markers, ["ready"])
        self.assertEqual(recording, [True, False])

    def test_stop_requested_before_worker_enters_run_is_not_lost(self):
        self.engine.load([{
            "dev": SYSTEM_DEVICE, "cmd": "Wait Time", "val": 60.0,
        }])
        self.engine.stop()
        result = self.engine.run()
        self.assertEqual(result.state, SequenceState.STOPPED)

    def test_built_in_device_commands_are_declared_by_plugins(self):
        from plugins.devices.keithley2400.plugin import plugin as keithley
        from plugins.devices.lakeshore331.plugin import plugin as lakeshore
        from plugins.devices.zup36_12.plugin import plugin as zup

        expected = {
            "LS331": {"Set Temp", "Heater", "Apply Ramp", "Ramp Off"},
            "K2400": {"Set Voltage", "Output On", "Output Off"},
            "ZUP": {
                "Set Volt", "Set Amp", "Set OVP", "Set UVP",
                "Output On", "Output Off",
            },
        }
        for plugin in (lakeshore, keithley, zup):
            commands = {command.key for command in plugin.sequence_commands}
            self.assertEqual(commands, expected[plugin.device_id])
            self.assertTrue(all(command.executor for command in plugin.sequence_commands))


if __name__ == "__main__":
    unittest.main()
