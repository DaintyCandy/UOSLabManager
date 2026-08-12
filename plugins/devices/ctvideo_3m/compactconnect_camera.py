"""CompactConnect vendor camera settings for CTvideo cameras on Windows.

OpenCV owns frame capture.  CompactConnect's two camera-side video settings
use a vendor Extension Unit exposed through DirectShow ``IKsControl``:

* Video Gain is the EEPROM-backed ``YTarget`` byte.
* Anti-flicker is CompactConnect's ``Indoor`` EEPROM byte.

Neither setting is a standard UVC VideoProcAmp property.  Reads use the
vendor address-latch protocol; persistent writes require explicit caller
acknowledgement and are never retried.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from dataclasses import dataclass
from typing import Mapping

from . import ks_probe as _ks


S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = 0x80010106
COINIT_MULTITHREADED = 0

COMPACTCONNECT_XU_GUID = _ks.GUID.from_string(
    "d13577f0-8d89-4700-812e-7dd5e2fdb898"
)
KSNODETYPE_DEV_SPECIFIC = "941c7ac0-c559-11d0-8a2b-00a0c9255ac1"
KSPROPERTY_TYPE_GET = 0x00000001
KSPROPERTY_TYPE_SET = 0x00000002
KSPROPERTY_TYPE_TOPOLOGY = 0x10000000

EEPROM_VIDEO_0 = 0x0800
EEPROM_VIDEO_1 = 0x0808
EEPROM_VIDEO_2 = 0x0810
EEPROM_VIDEO_7 = 0x0838
_VIDEO_GAIN_ADDRESSES = (
    EEPROM_VIDEO_0,
    EEPROM_VIDEO_1,
    EEPROM_VIDEO_2,
    EEPROM_VIDEO_7,
)
_EEPROM_BLOCK_SIZE = 8
_EEPROM_READ_SIZE = 10

VIDEO_GAIN_MINIMUM = 1
VIDEO_GAIN_MAXIMUM = 255
ANTI_FLICKER_MODES = {0: "Off", 1: "50 Hz", 2: "60 Hz"}
_ANTI_FLICKER_RAW = {0: 25, 1: 25, 2: 30}


class CompactConnectCameraError(RuntimeError):
    """Base error for DirectShow discovery and vendor camera access."""


class CompactConnectCallError(CompactConnectCameraError):
    """A native COM or IKsControl call returned a failing HRESULT."""

    def __init__(self, operation: str, hr: int):
        self.operation = operation
        self.hr = ctypes.c_ulong(hr).value
        super().__init__(f"{operation} failed: 0x{self.hr:08X}")


class UnsupportedCompactConnectCamera(CompactConnectCameraError):
    """The selected source does not expose CompactConnect's vendor node."""


@dataclass(frozen=True)
class CompactConnectVideoGainSnapshot:
    value: int
    complement: int
    blocks: tuple[tuple[int, bytes], ...]

    @property
    def expected_complement(self) -> int:
        return max(255 - self.value, 10)

    @property
    def internally_consistent(self) -> bool:
        return self.complement == self.expected_complement

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "complement": self.complement,
            "expected_complement": self.expected_complement,
            "internally_consistent": self.internally_consistent,
            "blocks": {
                f"0x{address:04X}": data.hex(" ")
                for address, data in self.blocks
            },
        }


@dataclass(frozen=True)
class CompactConnectVideoGainWriteResult:
    requested: int
    before: CompactConnectVideoGainSnapshot
    after: CompactConnectVideoGainSnapshot
    verified: bool


@dataclass(frozen=True)
class CompactConnectAntiFlickerSnapshot:
    raw_value: int
    block: bytes

    @property
    def possible_modes(self) -> tuple[int, ...]:
        return tuple(
            mode for mode, raw in _ANTI_FLICKER_RAW.items()
            if raw == self.raw_value
        )

    @property
    def description(self) -> str:
        if not self.possible_modes:
            return f"Unknown raw value {self.raw_value}"
        labels = "/".join(ANTI_FLICKER_MODES[mode] for mode in self.possible_modes)
        return f"{labels} (raw {self.raw_value})"

    def to_dict(self) -> dict:
        return {
            "raw_value": self.raw_value,
            "possible_modes": list(self.possible_modes),
            "description": self.description,
            "block": self.block.hex(" "),
        }


@dataclass(frozen=True)
class CompactConnectAntiFlickerWriteResult:
    requested_mode: int
    requested_raw: int
    before: CompactConnectAntiFlickerSnapshot
    after: CompactConnectAntiFlickerSnapshot
    verified: bool


def _same_text(left: str | None, right: str | None) -> bool:
    return bool(
        left and right
        and left.strip().casefold() == right.strip().casefold()
    )


class CompactConnectCameraController:
    """Access CompactConnect vendor settings on one DirectShow camera filter.

    COM pointers are thread-affine.  Open, use and close an instance on the
    same thread; the CTvideo capture worker follows this rule.
    """

    def __init__(
        self,
        *,
        device_path: str | None = None,
        friendly_name: str | None = None,
        camera_info: Mapping[str, object] | None = None,
    ):
        if camera_info:
            device_path = device_path or str(
                camera_info.get("CameraDevicePath") or ""
            ).strip() or None
            friendly_name = friendly_name or str(
                camera_info.get("CameraName") or ""
            ).strip() or None
        if not device_path and not friendly_name:
            raise ValueError("device_path or friendly_name is required.")

        self.requested_device_path = device_path
        self.requested_friendly_name = friendly_name
        self.device_path: str | None = None
        self.friendly_name: str | None = None
        self.vendor_node_id: int | None = None

        self._owner_thread: int | None = None
        self._com_initialized = False
        self._filter = None
        self._topology = None
        self._ks_control = None

    @classmethod
    def from_camera_info(
        cls, camera_info: Mapping[str, object]
    ) -> "CompactConnectCameraController":
        return cls(camera_info=camera_info)

    @property
    def is_open(self) -> bool:
        return self._filter is not None

    def __enter__(self) -> "CompactConnectCameraController":
        return self.open()

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def open(self) -> "CompactConnectCameraController":
        if sys.platform != "win32":
            raise CompactConnectCameraError(
                "CompactConnect camera controls are available only on Windows."
            )
        if self.is_open:
            self._check_thread()
            return self

        self._owner_thread = threading.get_ident()
        hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        unsigned_hr = ctypes.c_ulong(hr).value
        if hr in (S_OK, S_FALSE):
            self._com_initialized = True
        elif unsigned_hr != RPC_E_CHANGED_MODE:
            self._owner_thread = None
            raise CompactConnectCallError("CoInitializeEx", hr)

        try:
            selected = self._find_filter()
            self._filter = selected["filter"]
            self.device_path = selected["device_path"]
            self.friendly_name = selected["name"]
            self._topology = _ks._query_interface(
                self._filter, _ks.IID_IKS_TOPOLOGY_INFO
            )
            self._ks_control = _ks._query_interface(
                self._filter, _ks.IID_IKS_CONTROL
            )
            if not self._topology or not self._ks_control:
                raise UnsupportedCompactConnectCamera(
                    f"{self.friendly_name!r} does not expose IKsTopologyInfo/IKsControl."
                )
            self.vendor_node_id = self._find_vendor_node()
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        if self._owner_thread is not None:
            self._check_thread()
        _ks._release(self._ks_control)
        _ks._release(self._topology)
        _ks._release(self._filter)
        self._ks_control = None
        self._topology = None
        self._filter = None
        self.vendor_node_id = None
        if self._com_initialized:
            ctypes.windll.ole32.CoUninitialize()
        self._com_initialized = False
        self._owner_thread = None

    def _check_thread(self):
        if self._owner_thread != threading.get_ident():
            raise CompactConnectCameraError(
                "CompactConnectCameraController must be used on its opening thread."
            )

    def _require_open(self):
        if not self.is_open:
            raise CompactConnectCameraError(
                "CompactConnectCameraController is not open."
            )
        self._check_thread()

    def _find_filter(self) -> dict:
        path_matches = []
        name_matches = []
        all_filters = []
        try:
            for item in _ks._enumerate_video_filters():
                all_filters.append(item)
                if _same_text(item["device_path"], self.requested_device_path):
                    path_matches.append(item)
                if _same_text(item["name"], self.requested_friendly_name):
                    name_matches.append(item)

            matches = path_matches or name_matches
            if not matches:
                found = ", ".join(
                    f"{item['name']!r} ({item['device_path']})"
                    for item in all_filters
                )
                raise CompactConnectCameraError(
                    "DirectShow camera filter was not found for "
                    f"path={self.requested_device_path!r}, "
                    f"name={self.requested_friendly_name!r}. Found: {found or 'none'}"
                )
            if len(matches) > 1:
                raise CompactConnectCameraError(
                    "Camera friendly name is ambiguous; provide CameraDevicePath."
                )
            selected = matches[0]
            for item in all_filters:
                if item is not selected:
                    _ks._release(item["filter"])
            return selected
        except Exception:
            for item in all_filters:
                _ks._release(item["filter"])
            raise

    def _find_vendor_node(self) -> int:
        count = _ks.DWORD()
        hr = _ks._method(
            self._topology, 8, _ks.HRESULT, ctypes.POINTER(_ks.DWORD)
        )(self._topology, ctypes.byref(count))
        if _ks._failed(hr):
            raise CompactConnectCallError("IKsTopologyInfo.get_NumNodes", hr)
        for node_id in range(count.value):
            node_type = _ks.GUID()
            hr = _ks._method(
                self._topology, 9, _ks.HRESULT,
                _ks.DWORD, ctypes.POINTER(_ks.GUID),
            )(self._topology, node_id, ctypes.byref(node_type))
            if not _ks._failed(hr) and str(node_type) == KSNODETYPE_DEV_SPECIFIC:
                return node_id
        raise UnsupportedCompactConnectCamera(
            f"{self.friendly_name!r} has no KSNODETYPE_DEV_SPECIFIC node."
        )

    def _xu_property(
        self,
        property_id: int,
        request_type: int,
        *,
        payload: bytes = b"",
        output_size: int = 0,
    ) -> bytes:
        self._require_open()
        if self.vendor_node_id is None:
            raise UnsupportedCompactConnectCamera("Vendor node is unavailable.")

        request = _ks.KSP_NODE()
        request.Property.Set = COMPACTCONNECT_XU_GUID
        request.Property.Id = property_id
        request.Property.Flags = request_type | KSPROPERTY_TYPE_TOPOLOGY
        request.NodeId = self.vendor_node_id
        request.Reserved = 0
        if ctypes.sizeof(request) != 32:
            raise CompactConnectCameraError(
                f"Unexpected KSP_NODE size: {ctypes.sizeof(request)} bytes."
            )

        if output_size:
            data = (ctypes.c_ubyte * output_size)()
            data_size = output_size
        else:
            data_size = len(payload)
            data = (ctypes.c_ubyte * data_size).from_buffer_copy(payload)
        returned = _ks.ULONG()
        hr = _ks._method(
            self._ks_control, 3, _ks.HRESULT,
            ctypes.c_void_p, _ks.ULONG, ctypes.c_void_p, _ks.ULONG,
            ctypes.POINTER(_ks.ULONG),
        )(
            self._ks_control,
            ctypes.byref(request), ctypes.sizeof(request),
            ctypes.byref(data), data_size, ctypes.byref(returned),
        )
        if _ks._failed(hr):
            operation = "GET" if request_type == KSPROPERTY_TYPE_GET else "SET"
            raise CompactConnectCallError(
                f"CompactConnect XU property {property_id} {operation}", hr
            )
        if output_size:
            if returned.value < _EEPROM_BLOCK_SIZE:
                raise CompactConnectCameraError(
                    f"Vendor XU returned {returned.value} bytes; expected at least 8."
                )
            return bytes(data[:returned.value])
        return b""

    def _read_eeprom_block(self, address: int) -> bytes:
        if address not in _VIDEO_GAIN_ADDRESSES:
            raise ValueError(f"Unsupported EEPROM address 0x{address:04X}.")
        self._xu_property(
            5, KSPROPERTY_TYPE_SET, payload=address.to_bytes(4, "little")
        )
        result = self._xu_property(
            7, KSPROPERTY_TYPE_GET, output_size=_EEPROM_READ_SIZE
        )
        return result[:_EEPROM_BLOCK_SIZE]

    def _write_eeprom_block(self, address: int, block: bytes) -> None:
        if address not in _VIDEO_GAIN_ADDRESSES:
            raise ValueError(f"Unsupported EEPROM address 0x{address:04X}.")
        if len(block) != _EEPROM_BLOCK_SIZE:
            raise ValueError("EEPROM blocks must contain exactly 8 bytes.")
        relative_address = address - EEPROM_VIDEO_0
        first_payload = bytes(block) + relative_address.to_bytes(2, "little")
        self._xu_property(8, KSPROPERTY_TYPE_SET, payload=first_payload)

        commit_payload = bytearray(_EEPROM_READ_SIZE)
        commit_payload[7] = block[7]
        commit_payload[8:10] = b"\x00\x08"
        self._xu_property(8, KSPROPERTY_TYPE_SET, payload=bytes(commit_payload))

    def read_compactconnect_video_gain(self) -> CompactConnectVideoGainSnapshot:
        self._require_open()
        blocks = tuple(
            (address, self._read_eeprom_block(address))
            for address in _VIDEO_GAIN_ADDRESSES
        )
        values = dict(blocks)
        return CompactConnectVideoGainSnapshot(
            value=values[EEPROM_VIDEO_0][1],
            complement=values[EEPROM_VIDEO_7][3],
            blocks=blocks,
        )

    @staticmethod
    def _patched_video_gain_blocks(
        snapshot: CompactConnectVideoGainSnapshot, value: int
    ) -> tuple[tuple[int, bytes], ...]:
        blocks = {address: bytearray(data) for address, data in snapshot.blocks}
        blocks[EEPROM_VIDEO_0][1] = value
        blocks[EEPROM_VIDEO_7][3] = max(255 - value, 10)
        blocks[EEPROM_VIDEO_1][5] = 16
        blocks[EEPROM_VIDEO_1][7] = 32
        blocks[EEPROM_VIDEO_2][1] = 192
        blocks[EEPROM_VIDEO_2][2] = 5
        blocks[EEPROM_VIDEO_2][4] = 5
        blocks[EEPROM_VIDEO_2][6] = 5
        return tuple(
            (address, bytes(blocks[address]))
            for address in _VIDEO_GAIN_ADDRESSES
        )

    def set_compactconnect_video_gain(
        self, value: int, *, acknowledged: bool = False
    ) -> CompactConnectVideoGainWriteResult:
        if acknowledged is not True:
            raise PermissionError(
                "Writing CompactConnect Video Gain requires acknowledged=True."
            )
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("CompactConnect Video Gain must be an integer.")
        if not VIDEO_GAIN_MINIMUM <= value <= VIDEO_GAIN_MAXIMUM:
            raise ValueError("CompactConnect Video Gain must be in range 1..255.")
        self._require_open()

        before = self.read_compactconnect_video_gain()
        if before.value == value:
            return CompactConnectVideoGainWriteResult(
                requested=value, before=before, after=before, verified=True
            )
        expected_blocks = self._patched_video_gain_blocks(before, value)
        try:
            for address, block in expected_blocks:
                self._write_eeprom_block(address, block)
            after = self.read_compactconnect_video_gain()
        except Exception as error:
            raise CompactConnectCameraError(
                "Video Gain EEPROM update did not complete. The camera may be "
                "partially changed; reconnect and read before another write."
            ) from error
        return CompactConnectVideoGainWriteResult(
            requested=value,
            before=before,
            after=after,
            verified=after.blocks == expected_blocks,
        )

    def read_compactconnect_anti_flicker(
        self,
    ) -> CompactConnectAntiFlickerSnapshot:
        self._require_open()
        block = self._read_eeprom_block(EEPROM_VIDEO_7)
        return CompactConnectAntiFlickerSnapshot(raw_value=block[2], block=block)

    def set_compactconnect_anti_flicker(
        self, mode: int, *, acknowledged: bool = False
    ) -> CompactConnectAntiFlickerWriteResult:
        if acknowledged is not True:
            raise PermissionError(
                "Writing CompactConnect Anti-flicker requires acknowledged=True."
            )
        if isinstance(mode, bool) or not isinstance(mode, int):
            raise TypeError("Anti-flicker mode must be an integer.")
        if mode not in ANTI_FLICKER_MODES:
            raise ValueError("Anti-flicker mode must be 0 (Off), 1 (50 Hz), or 2 (60 Hz).")
        self._require_open()

        before = self.read_compactconnect_anti_flicker()
        requested_raw = _ANTI_FLICKER_RAW[mode]
        if before.raw_value == requested_raw:
            return CompactConnectAntiFlickerWriteResult(
                requested_mode=mode,
                requested_raw=requested_raw,
                before=before,
                after=before,
                verified=True,
            )
        block = bytearray(before.block)
        block[2] = requested_raw
        try:
            self._write_eeprom_block(EEPROM_VIDEO_7, bytes(block))
            after = self.read_compactconnect_anti_flicker()
        except Exception as error:
            raise CompactConnectCameraError(
                "Anti-flicker EEPROM update did not complete. Reconnect and "
                "read the current value before another write."
            ) from error
        return CompactConnectAntiFlickerWriteResult(
            requested_mode=mode,
            requested_raw=requested_raw,
            before=before,
            after=after,
            verified=after.raw_value == requested_raw,
        )


__all__ = [
    "ANTI_FLICKER_MODES",
    "KSPROPERTY_TYPE_GET",
    "KSPROPERTY_TYPE_SET",
    "CompactConnectAntiFlickerSnapshot",
    "CompactConnectAntiFlickerWriteResult",
    "CompactConnectCallError",
    "CompactConnectCameraController",
    "CompactConnectCameraError",
    "CompactConnectVideoGainSnapshot",
    "CompactConnectVideoGainWriteResult",
    "UnsupportedCompactConnectCamera",
]
