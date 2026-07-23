from core.plugin_manager import DataColumn, DevicePlugin


def create_settings_panel(manager, parent):
    from .panel import GPD3303SPanel
    return GPD3303SPanel(manager, plugin, parent)


class GPD3303SPlugin(DevicePlugin):
    device_id = "GPD3303S"
    display_name = "GPD-3303S"
    order = 40
    connection_label = "Port"
    default_connection = "/dev/cu.usbserial-0000"
    columns = (
        DataColumn("CH1_voltage_V", "GPD3303S_CH1_V"),
        DataColumn("CH1_current_A", "GPD3303S_CH1_A"),
        DataColumn("CH2_voltage_V", "GPD3303S_CH2_V"),
        DataColumn("CH2_current_A", "GPD3303S_CH2_A"),
    )
    settings_factory = staticmethod(create_settings_panel)

    def connect(self, connection: str):
        from .driver import GPD3303S
        device = GPD3303S(connection)
        try:
            device.identify()
            return device
        except Exception:
            try:
                device.close()
            except Exception:
                pass
            raise


plugin = GPD3303SPlugin()
