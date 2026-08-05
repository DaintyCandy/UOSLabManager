"""Resolve the macOS CTvideo camera through its shared USB container."""

import json
import plistlib
import subprocess

from ..d2xx_transport import CTVIDEO_PRODUCT_ID, CTVIDEO_VENDOR_ID


_IOREG_COMMAND = ("ioreg", "-a", "-p", "IOUSB")
_AVFOUNDATION_COMMAND = ("swift", "-e")
_CTVIDEO_CAMERA_VENDOR_ID = 0x093A
_CTVIDEO_CAMERA_PRODUCT_ID = 0x2900
_AVFOUNDATION_SCRIPT = r"""
import AVFoundation
import Foundation

let devices = AVCaptureDevice.devices(for: .video)
    + AVCaptureDevice.devices(for: .muxed)
let rows: [[String: Any]] = devices.enumerated().map { index, device in
    [
        "index": index,
        "name": device.localizedName,
        "unique_id": device.uniqueID,
    ]
}
let data = try! JSONSerialization.data(withJSONObject: rows)
FileHandle.standardOutput.write(data)
"""


def _camera_location_id(unique_id):
    try:
        value = int(str(unique_id).strip(), 0)
    except (TypeError, ValueError):
        return None
    if value <= 0xFFFFFFFF:
        return None
    return value >> 32


def _tree_items(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _tree_items(child)
    elif isinstance(value, list):
        for child in value:
            yield from _tree_items(child)


def _usb_devices():
    try:
        result = subprocess.run(
            _IOREG_COMMAND,
            check=True,
            capture_output=True,
            timeout=15,
        )
        report = plistlib.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException) as error:
        raise RuntimeError(f"Could not enumerate macOS USB devices: {error}") from error
    return [
        item for item in _tree_items(report)
        if "idVendor" in item and "idProduct" in item
    ]


def _cameras():
    try:
        result = subprocess.run(
            _AVFOUNDATION_COMMAND + (_AVFOUNDATION_SCRIPT,),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        report = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not enumerate AVFoundation cameras: {error}") from error
    return [
        {
            "index": int(item["index"]),
            "name": item["name"],
            "unique_id": item["unique_id"],
            "location_id": _camera_location_id(item["unique_id"]),
        }
        for item in report
    ]


def _text_property(device, *names):
    for name in names:
        value = device.get(name)
        if value is not None:
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace")
            return str(value)
    return ""


def _requested_serial(selector):
    value = str(selector or "").strip()
    if value.lower().startswith("d2xx://"):
        value = value[7:]
    if (
        not value
        or value.lower() == "auto"
        or value.startswith("/dev/")
        or (value.upper().startswith("COM") and value[3:].isdigit())
    ):
        return None
    return value


def _select_sensor(devices, selector):
    sensors = [
        device for device in devices
        if int(device.get("idVendor", -1)) == CTVIDEO_VENDOR_ID
        and int(device.get("idProduct", -1)) == CTVIDEO_PRODUCT_ID
    ]
    requested = _requested_serial(selector)
    if requested is not None:
        sensor = next(
            (
                device for device in sensors
                if _text_property(
                    device, "USB Serial Number", "kUSBSerialNumberString"
                ) == requested
            ),
            None,
        )
        if sensor is None:
            raise RuntimeError(f"CTvideo USB sensor not found: {requested}")
        return sensor
    if not sensors:
        raise RuntimeError(
            "CTvideo USB sensor not found (expected VID:PID 0403:DE33)."
        )
    if len(sensors) > 1:
        serials = ", ".join(
            _text_property(item, "USB Serial Number", "kUSBSerialNumberString")
            or "unknown"
            for item in sensors
        )
        raise RuntimeError(
            f"Multiple CTvideo USB sensors found; select a serial number: {serials}"
        )
    return sensors[0]


def _select_direct_camera_usb(devices):
    cameras = [
        device for device in devices
        if int(device.get("idVendor", -1)) == _CTVIDEO_CAMERA_VENDOR_ID
        and int(device.get("idProduct", -1)) == _CTVIDEO_CAMERA_PRODUCT_ID
    ]
    if not cameras:
        raise RuntimeError(
            "CTvideo camera USB device not found (expected VID:PID 093A:2900)."
        )
    if len(cameras) > 1:
        locations = ", ".join(
            f"0x{int(item['locationID']):08X}"
            if item.get("locationID") is not None else "unknown"
            for item in cameras
        )
        raise RuntimeError(
            "Multiple CTvideo camera USB devices found (VID:PID 093A:2900); "
            f"cannot select one safely: {locations}"
        )
    return cameras[0]


def _match_avfoundation_camera(camera_usb, cameras):
    location_id = camera_usb.get("locationID")
    if location_id is None:
        raise RuntimeError("USB location ID is unavailable for the CTvideo camera.")
    location_id = int(location_id)
    camera = next(
        (item for item in cameras if item["location_id"] == location_id),
        None,
    )
    if camera is None:
        raise RuntimeError(
            "No AVFoundation camera matches CTvideo USB location "
            f"0x{location_id:08X}."
        )
    return camera


def _camera_result(port, sensor, camera, camera_usb, container_id):
    sensor_serial = (
        _text_property(sensor, "USB Serial Number", "kUSBSerialNumberString")
        if sensor is not None else _requested_serial(port)
    )
    product_name = (
        _text_property(sensor, "USB Product Name", "kUSBProductString")
        if sensor is not None else ""
    ) or "IR Online Video Sensor"
    instance_id = f"USB VID_0403&PID_DE33\\{sensor_serial or 'unknown'}"
    return {
        "PortName": f"d2xx://{sensor_serial}" if sensor_serial else "d2xx://auto",
        "PortFriendlyName": product_name,
        "PortInstanceId": instance_id,
        "PortContainerId": container_id,
        "CameraIndex": camera["index"],
        "CameraName": camera["name"],
        "CameraInstanceId": str(camera["unique_id"]),
        "CameraLocationId": int(camera_usb["locationID"]),
        "CameraVendorId": int(camera_usb["idVendor"]),
        "CameraProductId": int(camera_usb["idProduct"]),
        "CameraContainerId": container_id,
        "CameraDevicePath": f"AVFoundation camera index {camera['index']}",
    }


def resolve_camera(port: str) -> dict:
    devices = _usb_devices()
    cameras = _cameras()
    sensor = None
    try:
        sensor = _select_sensor(devices, port)
        container_id = _text_property(sensor, "kUSBContainerID")
        if not container_id:
            raise RuntimeError(
                "USB Container ID is unavailable for the CTvideo sensor."
            )

        container_locations = {
            int(device["locationID"])
            for device in devices
            if _text_property(device, "kUSBContainerID") == container_id
            and device.get("locationID") is not None
        }
        camera = next(
            (
                item for item in cameras
                if item["location_id"] in container_locations
            ),
            None,
        )
        if camera is None:
            raise RuntimeError(
                f"No AVFoundation camera shares CTvideo USB container {container_id}."
            )
        camera_usb = next(
            (
                device for device in devices
                if device.get("locationID") is not None
                and int(device["locationID"]) == camera["location_id"]
            ),
            {},
        )
        return _camera_result(port, sensor, camera, camera_usb, container_id)
    except RuntimeError:
        camera_usb = _select_direct_camera_usb(devices)
        camera = _match_avfoundation_camera(camera_usb, cameras)
        container_id = _text_property(camera_usb, "kUSBContainerID")
        return _camera_result(port, sensor, camera, camera_usb, container_id)
