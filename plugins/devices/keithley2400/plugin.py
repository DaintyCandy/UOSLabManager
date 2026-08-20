from core.plugin_manager import DataColumn, DevicePlugin, SafeAction, SequenceCommand


def create_settings_panel(manager, parent):
    from .panel import Keithley2400Panel
    return Keithley2400Panel(manager, plugin, parent)


def set_voltage(device, value, _context):
    device.set_voltage_source(value)


def output_on(device, _value, _context):
    device.output_on()


def output_off(device, _value, _context):
    device.output_off()


class Keithley2400Plugin(DevicePlugin):
    device_id = "K2400"
    display_name = "K2400"
    order = 20
    connection_label = "Address"
    default_connection = "GPIB0::24::INSTR"
    columns = (
        DataColumn(
            "voltage_V", "K2400_voltage_V", unit="V",
            condition_label="K2400 Voltage",
        ),
        DataColumn(
            "current_A", "K2400_current_A", unit="A",
            condition_label="K2400 Current",
        ),
        DataColumn(
            "power_W", "K2400_power_W", unit="W",
            condition_label="K2400 Power",
        ),
        DataColumn("resistance_Ohm", "K2400_resistance_Ohm"),
    )
    safe_actions = (SafeAction("output_off"),)
    settings_factory = staticmethod(create_settings_panel)
    sequence_commands = (
        SequenceCommand(
            key="Set Voltage", label="Set Voltage", unit="V", minimum=-200.0,
            maximum=200.0, default=0.0, decimals=4,
            settle_seconds=0.3, executor=set_voltage,
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
        from .driver import Keithley2400
        return Keithley2400(connection)


plugin = Keithley2400Plugin()
