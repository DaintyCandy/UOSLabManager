from core.plugin_manager import DataColumn, DevicePlugin


def create_settings_panel(manager, parent):
    from .panel import ZUP3612Panel
    return ZUP3612Panel(manager, plugin, parent)


class ZUP3612Plugin(DevicePlugin):
    device_id = "ZUP"
    display_name = "ZUP36-12"
    order = 30
    connection_label = "Port"
    default_connection = "/dev/cu.usbserial-A9EQ7W68"
    columns = (
        DataColumn("voltage_V", "ZUP_voltage_V"),
        DataColumn("current_A", "ZUP_current_A"),
        DataColumn("power_W", "ZUP_power_W"),
    )
    settings_factory = staticmethod(create_settings_panel)

    def connect(self, connection: str):
        from .driver import ZUP36_12
        return ZUP36_12(connection)


plugin = ZUP3612Plugin()
