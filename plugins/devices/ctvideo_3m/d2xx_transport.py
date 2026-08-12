"""Minimal FTDI D2XX serial adapter for the macOS CTvideo interface."""

import ctypes
import ctypes.util
import glob
import os


FT_OK = 0
FT_OPEN_BY_SERIAL_NUMBER = 1
FT_PURGE_RX = 1
FT_PURGE_TX = 2
FT_FLOW_NONE = 0
FT_BITS_8 = 8
FT_STOP_BITS_1 = 0
FT_PARITY_NONE = 0

CTVIDEO_VENDOR_ID = 0x0403
CTVIDEO_PRODUCT_ID = 0xDE33

_STATUS_NAMES = {
    1: "invalid handle",
    2: "device not found",
    3: "device not opened",
    4: "I/O error",
    5: "insufficient resources",
    6: "invalid parameter",
    7: "invalid baud rate",
    8: "device not opened for erase",
    9: "device not opened for write",
    10: "failed to write device",
    11: "EEPROM read failed",
    12: "EEPROM write failed",
    13: "EEPROM erase failed",
    14: "EEPROM not present",
    15: "EEPROM not programmed",
    16: "invalid arguments",
    17: "unsupported operation",
    18: "other error",
    19: "device list not ready",
}


class D2XXError(RuntimeError):
    pass


class D2XXLibraryError(D2XXError):
    pass


def _library_candidates():
    configured = os.environ.get("FTD2XX_LIBRARY", "").strip()
    discovered = ctypes.util.find_library("ftd2xx")
    candidates = [
        configured,
        discovered,
        "/usr/local/lib/libftd2xx.dylib",
        "/usr/local/lib/libftd2xx.1.4.35.dylib",
        "/usr/local/lib/libftd2xx.1.4.30.dylib",
        "/opt/homebrew/lib/libftd2xx.dylib",
        "libftd2xx.dylib",
    ]
    for pattern in (
        "/Volumes/*/release/build/libftd2xx.dylib",
        "/Volumes/*/release/build/libftd2xx.*.dylib",
    ):
        candidates.extend(sorted(glob.glob(pattern)))
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate


def load_d2xx_library():
    errors = []
    for candidate in _library_candidates():
        try:
            return ctypes.CDLL(str(candidate))
        except OSError as error:
            errors.append(f"{candidate}: {error}")
    detail = errors[-1] if errors else "no library candidates"
    raise D2XXLibraryError(
        "FTDI D2XX library is required for CTvideo pyrometer access on macOS. "
        "Install the FTDI macOS ARM64 D2XX library (libftd2xx.dylib), or set "
        f"FTD2XX_LIBRARY to its full path. Last loader error: {detail}"
    )


def _configure_signatures(library):
    dword = ctypes.c_uint32
    handle = ctypes.c_void_p
    signatures = {
        "FT_SetVIDPID": ([dword, dword], dword),
        "FT_CreateDeviceInfoList": ([ctypes.POINTER(dword)], dword),
        "FT_GetDeviceInfoDetail": (
            [
                dword, ctypes.POINTER(dword), ctypes.POINTER(dword),
                ctypes.POINTER(dword), ctypes.POINTER(dword), ctypes.c_void_p,
                ctypes.c_void_p, ctypes.POINTER(handle),
            ],
            dword,
        ),
        "FT_OpenEx": ([ctypes.c_void_p, dword, ctypes.POINTER(handle)], dword),
        "FT_ResetDevice": ([handle], dword),
        "FT_SetBaudRate": ([handle, dword], dword),
        "FT_SetDataCharacteristics": (
            [handle, ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte], dword,
        ),
        "FT_SetFlowControl": (
            [handle, ctypes.c_ushort, ctypes.c_ubyte, ctypes.c_ubyte], dword,
        ),
        "FT_SetTimeouts": ([handle, dword, dword], dword),
        "FT_SetLatencyTimer": ([handle, ctypes.c_ubyte], dword),
        "FT_Purge": ([handle, dword], dword),
        "FT_Read": (
            [handle, ctypes.c_void_p, dword, ctypes.POINTER(dword)], dword,
        ),
        "FT_Write": (
            [handle, ctypes.c_void_p, dword, ctypes.POINTER(dword)], dword,
        ),
        "FT_Close": ([handle], dword),
    }
    for name, (argument_types, return_type) in signatures.items():
        try:
            function = getattr(library, name)
        except AttributeError as error:
            raise D2XXLibraryError(f"D2XX library is missing required symbol: {name}") from error
        function.argtypes = argument_types
        function.restype = return_type


def _status_error(operation, status):
    label = _STATUS_NAMES.get(int(status), "unknown status")
    return D2XXError(f"{operation} failed: {label} (FT_STATUS={int(status)})")


def _selector_serial(selector):
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


class D2XXSerialAdapter:
    """Expose the small pyserial surface used by :class:`CTVideo3M`."""

    def __init__(
        self,
        selector="auto",
        baudrate=115200,
        timeout=0.5,
        library=None,
    ):
        self._library = library or load_d2xx_library()
        _configure_signatures(self._library)
        self._handle = ctypes.c_void_p()
        self.is_open = False
        self.timeout = float(timeout)
        self.write_timeout = float(timeout)
        self.serial_number = None
        self.description = None

        self._call("FT_SetVIDPID", CTVIDEO_VENDOR_ID, CTVIDEO_PRODUCT_ID)
        device = self._select_device(selector)
        self.serial_number = device["serial_number"]
        self.description = device["description"]
        self.port = f"d2xx://{self.serial_number}"
        encoded_serial = self.serial_number.encode("ascii")
        self._call(
            "FT_OpenEx",
            ctypes.c_char_p(encoded_serial),
            FT_OPEN_BY_SERIAL_NUMBER,
            ctypes.byref(self._handle),
        )
        self.is_open = True
        try:
            self._call("FT_ResetDevice", self._handle)
            self._call("FT_SetBaudRate", self._handle, int(baudrate))
            self._call(
                "FT_SetDataCharacteristics",
                self._handle,
                FT_BITS_8,
                FT_STOP_BITS_1,
                FT_PARITY_NONE,
            )
            self._call(
                "FT_SetFlowControl", self._handle, FT_FLOW_NONE, 0, 0,
            )
            timeout_ms = max(1, round(self.timeout * 1000.0))
            write_timeout_ms = max(1, round(self.write_timeout * 1000.0))
            self._call(
                "FT_SetTimeouts", self._handle, timeout_ms, write_timeout_ms,
            )
            self._call("FT_SetLatencyTimer", self._handle, 2)
            self._call("FT_Purge", self._handle, FT_PURGE_RX | FT_PURGE_TX)
        except Exception:
            self.close()
            raise

    def _call(self, name, *arguments):
        status = getattr(self._library, name)(*arguments)
        if status != FT_OK:
            raise _status_error(name, status)

    def _devices(self):
        count = ctypes.c_uint32()
        self._call("FT_CreateDeviceInfoList", ctypes.byref(count))
        devices = []
        for index in range(count.value):
            flags = ctypes.c_uint32()
            device_type = ctypes.c_uint32()
            device_id = ctypes.c_uint32()
            location_id = ctypes.c_uint32()
            serial_number = ctypes.create_string_buffer(16)
            description = ctypes.create_string_buffer(64)
            handle = ctypes.c_void_p()
            self._call(
                "FT_GetDeviceInfoDetail",
                index,
                ctypes.byref(flags),
                ctypes.byref(device_type),
                ctypes.byref(device_id),
                ctypes.byref(location_id),
                serial_number,
                description,
                ctypes.byref(handle),
            )
            devices.append({
                "serial_number": serial_number.value.decode("ascii", "replace"),
                "description": description.value.decode("utf-8", "replace"),
                "location_id": location_id.value,
                "device_id": device_id.value,
            })
        return devices

    def _select_device(self, selector):
        expected_id = (CTVIDEO_VENDOR_ID << 16) | CTVIDEO_PRODUCT_ID
        devices = [
            item for item in self._devices()
            if item["device_id"] == expected_id
            or item["serial_number"].startswith("CTLV_")
            or item["description"] == "IR Online Video Sensor"
        ]
        requested = _selector_serial(selector)
        if requested is not None:
            device = next(
                (item for item in devices if item["serial_number"] == requested),
                None,
            )
            if device is None:
                available = ", ".join(item["serial_number"] for item in devices) or "none"
                raise D2XXError(
                    f"CTvideo D2XX device not found: {requested}; available: {available}"
                )
            return device
        if not devices:
            raise D2XXError(
                "No CTvideo D2XX device found (expected VID:PID 0403:DE33)."
            )
        if len(devices) > 1:
            available = ", ".join(item["serial_number"] for item in devices)
            raise D2XXError(
                f"Multiple CTvideo D2XX devices found; select a serial number: {available}"
            )
        return devices[0]

    def reset_input_buffer(self):
        self._require_open()
        self._call("FT_Purge", self._handle, FT_PURGE_RX)

    def write(self, data):
        self._require_open()
        payload = bytes(data)
        if not payload:
            return 0
        buffer = ctypes.create_string_buffer(payload, len(payload))
        written = ctypes.c_uint32()
        self._call(
            "FT_Write", self._handle, buffer, len(payload), ctypes.byref(written),
        )
        if written.value != len(payload):
            raise D2XXError(
                f"D2XX short write ({written.value}/{len(payload)} bytes)"
            )
        return written.value

    def flush(self):
        self._require_open()

    def read(self, size=1):
        self._require_open()
        size = max(0, int(size))
        if size == 0:
            return b""
        buffer = ctypes.create_string_buffer(size)
        received = ctypes.c_uint32()
        self._call(
            "FT_Read", self._handle, buffer, size, ctypes.byref(received),
        )
        return buffer.raw[:received.value]

    def close(self):
        if not self.is_open:
            return
        handle = self._handle
        self.is_open = False
        self._handle = ctypes.c_void_p()
        self._call("FT_Close", handle)

    def _require_open(self):
        if not self.is_open:
            raise D2XXError("CTvideo D2XX device is closed")


def d2xx_library_available():
    try:
        load_d2xx_library()
    except D2XXLibraryError:
        return False
    return True
