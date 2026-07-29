from core.plugin_manager import DataColumn, DevicePlugin


def create_settings_panel(manager, parent):
    from .panel import CTVideo3MPanel
    return CTVideo3MPanel(manager, plugin, parent)


class CTVideo3MPlugin(DevicePlugin):
    device_id = "CTVIDEO3M"
    display_name = "CTvideo 3M"
    order = 40
    connection_label = "Port"
    default_connection = "COM6"
    columns = (
        DataColumn("actual_temp_C", "CTvideo_actual_C"),
    )
    settings_factory = staticmethod(create_settings_panel)

    def connect(self, connection: str):
        from .driver import CTVideo3M
        return CTVideo3M(connection)


plugin = CTVideo3MPlugin()
