from core.plugin_manager import DataColumn, DevicePlugin


def create_settings_panel(manager, parent):
    from .panel import StandardDevicePanel
    return StandardDevicePanel(manager, plugin, parent)


class zup36_6Plugin(DevicePlugin):
    device_id = 'zup36_6'
    display_name = 'Zup36 6'
    profile = 'standard'
    connection_label = "Connection"
    default_connection = ""
    columns = (DataColumn("value", 'zup36_6_value'),)
    settings_factory = staticmethod(create_settings_panel)

    def connect(self, connection):
        from .driver import DeviceDriver
        return DeviceDriver(connection)


plugin = zup36_6Plugin()
