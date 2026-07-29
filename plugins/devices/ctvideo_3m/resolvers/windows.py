"""Resolve a CTvideo camera by the Windows Container ID of its COM port."""

import ctypes
import winreg


_ENUM_PATH = r"SYSTEM\CurrentControlSet\Enum"


def _value(key, name, default=None):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return default


def _subkeys(key):
    index = 0
    while True:
        try:
            yield winreg.EnumKey(key, index)
        except OSError:
            return
        index += 1


def _is_present(instance_id: str) -> bool:
    device_node = ctypes.c_ulong()
    locate = ctypes.windll.cfgmgr32.CM_Locate_DevNodeW
    locate.argtypes = [ctypes.POINTER(ctypes.c_ulong), ctypes.c_wchar_p, ctypes.c_ulong]
    locate.restype = ctypes.c_ulong
    return locate(ctypes.byref(device_node), instance_id, 0) == 0


def _devices(bus_names):
    devices = []
    access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _ENUM_PATH, 0, access) as enum_key:
        available_buses = set(_subkeys(enum_key))
        for bus in bus_names:
            if bus not in available_buses:
                continue
            with winreg.OpenKey(enum_key, bus) as bus_key:
                for device_name in _subkeys(bus_key):
                    with winreg.OpenKey(bus_key, device_name) as device_key:
                        for instance_name in _subkeys(device_key):
                            instance_id = f"{bus}\\{device_name}\\{instance_name}"
                            if not _is_present(instance_id):
                                continue
                            with winreg.OpenKey(device_key, instance_name) as instance_key:
                                port_name = None
                                try:
                                    with winreg.OpenKey(instance_key, "Device Parameters") as parameters:
                                        port_name = _value(parameters, "PortName")
                                except OSError:
                                    pass
                                devices.append({
                                    "instance_id": instance_id,
                                    "class": _value(instance_key, "Class", ""),
                                    "class_guid": str(_value(instance_key, "ClassGUID", "")).lower(),
                                    "friendly_name": _value(instance_key, "FriendlyName", device_name),
                                    "container_id": _normalize_container(_value(instance_key, "ContainerID")),
                                    "port_name": port_name,
                                })
    return devices


def _normalize_container(value):
    if value is None:
        return None
    return str(value).strip().strip("{}").upper()


def _is_capture_camera(device):
    """Exclude Windows Hello IR sensors that OpenCV does not enumerate."""
    return "ir camera" not in str(device["friendly_name"]).lower()


def resolve_camera(port: str) -> dict:
    port = str(port).strip().upper()
    if not port:
        raise ValueError("COM port must not be empty.")

    serial_devices = _devices(("FTDIBUS", "USB"))
    serial = next(
        (device for device in serial_devices if str(device["port_name"] or "").upper() == port),
        None,
    )
    if serial is None:
        raise RuntimeError(f"Present Windows serial device not found: {port}")
    container_id = serial["container_id"]
    if not container_id:
        raise RuntimeError(f"Container ID is unavailable for {port}")

    cameras = [
        device for device in _devices(("USB", "SWD"))
        if str(device["class"]).lower() in ("camera", "image")
        or device["class_guid"] in (
            "{ca3e7ab9-b4c3-4ae6-8251-579ef933890f}",  # Camera
            "{6bdd1fc6-810f-11d0-bec7-08002be2092f}",  # Image
        )
    ]
    camera = next(
        (device for device in cameras if device["container_id"] == container_id), None
    )
    if camera is None:
        raise RuntimeError(f"No camera has Container ID {container_id} ({port})")
    capture_cameras = [device for device in cameras if _is_capture_camera(device)]
    try:
        camera_index = capture_cameras.index(camera)
    except ValueError as error:
        raise RuntimeError("The Container-ID camera is not exposed as an OpenCV capture device.") from error
    return {
        "PortName": port,
        "PortFriendlyName": serial["friendly_name"],
        "PortInstanceId": serial["instance_id"],
        "PortContainerId": container_id,
        "CameraIndex": camera_index,
        "CameraName": camera["friendly_name"],
        "CameraInstanceId": camera["instance_id"],
        "CameraContainerId": camera["container_id"],
        "CameraDevicePath": f"PnP camera index {camera_index}",
    }
