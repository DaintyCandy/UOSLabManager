from core.plugin_manager import (
    AlarmRule, DataColumn, DevicePlugin, SafeAction, SequenceCommand,
)


def create_settings_panel(manager, parent):
    from .panel import ZUP3612Panel
    return ZUP3612Panel(manager, plugin, parent)


def _call(method):
    return lambda device, value, _context: getattr(device, method)(value)


def output_on(device, _value, _context):
    device.output_on()


def output_off(device, _value, _context):
    device.output_off()


class ZUP3612Plugin(DevicePlugin):
    device_id = "ZUP"
    display_name = "ZUP36-12"
    order = 30
    connection_label = "Port"
    default_connection = "COM4"
    columns = (
        DataColumn(
            "voltage_V", "ZUP_voltage_V", unit="V",
            condition_label="ZUP Voltage",
        ),
        DataColumn(
            "current_A", "ZUP_current_A", unit="A",
            condition_label="ZUP Current",
        ),
        DataColumn(
            "power_W", "ZUP_power_W", unit="W",
            condition_label="ZUP Power",
        ),
    )
    alarms = (
        AlarmRule(
            "alarm", message="{device} ALARM DETECTED: {value}",
            normal_values=(None, "", "AL00000"),
        ),
    )
    safe_actions = (
        SafeAction("output_off"),
        SafeAction("set_voltage", (0.0,)),
        SafeAction("set_current", (0.0,)),
    )
    settings_factory = staticmethod(create_settings_panel)
    sequence_aliases = ("ZUP36-12",)
    sequence_commands = (
        SequenceCommand(
            key="Set Volt", label="Set Volt", unit="V", minimum=0.0,
            maximum=36.0, default=0.0, decimals=3,
            settle_seconds=0.3, executor=_call("set_voltage"),
        ),
        SequenceCommand(
            key="Set Amp", label="Set Amp", unit="A", minimum=0.0,
            maximum=12.0, default=0.0, decimals=3,
            settle_seconds=0.3, executor=_call("set_current"),
        ),
        SequenceCommand(
            key="Set OVP", label="Set OVP", unit="V", minimum=0.0,
            maximum=36.0, default=36.0, decimals=3,
            settle_seconds=0.3, executor=_call("set_ovp"),
        ),
        SequenceCommand(
            key="Set UVP", label="Set UVP", unit="V", minimum=0.0,
            maximum=36.0, default=0.0, decimals=3,
            settle_seconds=0.3, executor=_call("set_uvp"),
        ),
        SequenceCommand(
            key="Output On", label="Output On", requires_value=False,
            settle_seconds=0.3, executor=output_on,
        ),
        SequenceCommand(
            key="Output Off", label="Output Off", requires_value=False,
            settle_seconds=0.3, executor=output_off,
        ),
    )

    def connect(self, connection: str):
        from .driver import ZUP36_12
        return ZUP36_12(connection)


plugin = ZUP3612Plugin()
