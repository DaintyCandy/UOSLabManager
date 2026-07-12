from core.plugin_manager import DataColumn, DevicePlugin


def create_settings_panel(manager, parent):
    from .panel import Keithley2400Panel
    return Keithley2400Panel(manager, plugin, parent)


class Keithley2400Plugin(DevicePlugin):
    device_id = "K2400"
    display_name = "K2400"
    order = 20
    connection_label = "Address"
    default_connection = "GPIB0::24::INSTR"
    columns = (
        DataColumn("voltage_V", "K2400_voltage_V"),
        DataColumn("current_A", "K2400_current_A"),
        DataColumn("power_W", "K2400_power_W"),
        DataColumn("resistance_Ohm", "K2400_resistance_Ohm"),
    )
    settings_factory = staticmethod(create_settings_panel)

    def connect(self, connection: str):
        from .driver import Keithley2400
        return Keithley2400(connection)


plugin = Keithley2400Plugin()
