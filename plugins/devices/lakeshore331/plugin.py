import time

from core.plugin_manager import DataColumn, DevicePlugin


def create_settings_window(manager, parent):
    from .panel import LakeShore331Window
    return LakeShore331Window(manager, parent)


class LakeShore331Plugin(DevicePlugin):
    device_id = "LS331"
    display_name = "LS331"
    order = 10
    connection_label = "Port"
    default_connection = "/dev/cu.usbserial-A9EQ7W68"
    columns = (
        DataColumn("A_temp_K", "LS331_A_K"),
        DataColumn("B_temp_K", "LS331_B_K"),
        DataColumn("setpoint_K", "LS331_setpoint_K"),
    )
    settings_factory = staticmethod(create_settings_window)

    def connect(self, connection: str):
        from .driver import LakeShore331
        device = LakeShore331(connection)
        try:
            time.sleep(0.2)
            device.write("MODE 1")
            time.sleep(0.2)
            device.write("RAMP 1,0,1.0")
            return device
        except Exception:
            device.close()
            raise


plugin = LakeShore331Plugin()
