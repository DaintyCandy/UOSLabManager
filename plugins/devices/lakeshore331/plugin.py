from core.plugin_manager import DataColumn, DevicePlugin, SequenceCommand


def create_settings_window(manager, parent):
    from .panel import LakeShore331Window
    return LakeShore331Window(manager, parent)


def set_temperature(device, value, context):
    device.set_setpoint(value, loop=1)
    if not context.get_runtime("LS331.ramp_active", False):
        return
    context.log(f"Ramping to {value:g} K...")
    while not context.stopped:
        if (
            not device.is_ramping(loop=1)
            or abs(device.read_temp("A") - value) < 2.5
        ):
            device.set_ramp(False, 1.0, loop=1)
            context.set_runtime("LS331.ramp_active", False)
            context.log(">>> Target reached. Ramp Auto-OFF.")
            return
        if not context.wait(0.5):
            return


def set_heater(device, value, _context):
    device.set_heater_range(int(value))


def apply_ramp(device, value, context):
    device.set_ramp(True, value, loop=1)
    context.set_runtime("LS331.ramp_active", True)


def disable_ramp(device, _value, context):
    device.set_ramp(False, 1.0, loop=1)
    context.set_runtime("LS331.ramp_active", False)


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
    sequence_commands = (
        SequenceCommand(
            key="Set Temp", label="Set Temp", unit="K", minimum=0.0,
            maximum=1000.0, default=300.0, decimals=2,
            settle_seconds=0.3, executor=set_temperature,
        ),
        SequenceCommand(
            key="Heater", label="Heater", minimum=0, maximum=3, default=0,
            decimals=0, choices=("Off", "Low", "Medium", "High"),
            settle_seconds=0.3, executor=set_heater,
        ),
        SequenceCommand(
            key="Apply Ramp", label="Apply Ramp", unit="K/min", minimum=0.0,
            maximum=1000.0, default=1.0, decimals=3,
            settle_seconds=0.3, executor=apply_ramp,
        ),
        SequenceCommand(
            key="Ramp Off", label="Ramp Off", requires_value=False,
            settle_seconds=0.3, executor=disable_ramp,
        ),
    )

    def connect(self, connection: str):
        from .driver import LakeShore331
        # Opening a connection must not change the controller's mode, ramp,
        # setpoint, heater range, or any other persisted device setting.
        return LakeShore331(connection)


plugin = LakeShore331Plugin()
