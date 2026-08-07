"""Optris CTvideo 3M binary serial driver.

Protocol reference: CT-CTlaser-CTvideo-commands-2018-11.pdf.
"""

from dataclasses import dataclass
import math
import threading
import time
from typing import Mapping

import serial


@dataclass(frozen=True)
class CalibrationFieldSpec:
    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    step: float
    decimals: int


@dataclass(frozen=True)
class CalibrationSnapshot:
    """Immutable identity and raw calibration values read from one device."""

    serial_number: int
    firmware_revision: int
    tweak_offset_C: float
    tweak_gain: float
    raw_offset: int
    raw_gain: int

    @property
    def identity(self) -> tuple[int, int]:
        return self.serial_number, self.firmware_revision


@dataclass(frozen=True)
class CalibrationApplyResult:
    before: CalibrationSnapshot
    requested: Mapping[str, float]
    after: CalibrationSnapshot
    statuses: Mapping[str, str]

    @property
    def verified(self) -> bool:
        return (
            self.before.identity == self.after.identity
            and all(status in {"verified", "unchanged"}
                    for status in self.statuses.values())
        )


class CalibrationStateChangedError(RuntimeError):
    """Raised when calibration changed after the user last read it."""


class CalibrationProtocolError(RuntimeError):
    """Raised when a SET echo or read-back does not match the protocol."""


class CTVideo3M:
    OBJECT_TEMP = 0x01
    HEAD_TEMP = 0x02
    BOX_TEMP = 0x03
    ACTUAL_TEMP = 0x81

    READ_TWEAK_OFFSET = 0x26
    READ_TWEAK_GAIN = 0x27
    SET_TWEAK_OFFSET = 0xA6
    SET_TWEAK_GAIN = 0xA7

    TWEAK_OFFSET_RAW_BIAS = 1000
    TWEAK_OFFSET_SCALE = 10
    TWEAK_GAIN_SCALE = 1 << 15
    CALIBRATION_FIELDS = (
        CalibrationFieldSpec(
            "tweak_offset_C", "Tweak Offset", "°C",
            -100.0, (0xFFFF - TWEAK_OFFSET_RAW_BIAS) / TWEAK_OFFSET_SCALE,
            0.1, 1,
        ),
        CalibrationFieldSpec(
            "tweak_gain", "Tweak Gain", "",
            0.0, 0xFFFF / TWEAK_GAIN_SCALE,
            1.0 / TWEAK_GAIN_SCALE, 8,
        ),
    )

    def __init__(self, port: str = "COM6"):
        self.ser = serial.Serial(
            port=port,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self._lock = threading.RLock()

    def close(self):
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.close()

    def _read_exactly(self, size: int) -> bytes:
        data = self.ser.read(size)
        if len(data) != size:
            raise TimeoutError(f"CTvideo response timed out ({len(data)}/{size} bytes)")
        return data

    def query_bytes(self, command: int, response_size: int, data: bytes = b"",
                    attempts: int = 2) -> bytes:
        attempts = max(1, int(attempts))
        with self._lock:
            last_error = None
            for attempt in range(attempts):
                self.ser.reset_input_buffer()
                self.ser.write(bytes((command,)) + data)
                self.ser.flush()
                try:
                    return self._read_exactly(response_size)
                except TimeoutError as error:
                    last_error = error
                    if attempt + 1 < attempts:
                        time.sleep(0.020)
            raise last_error

    def set_bytes(self, command: int, data: bytes, response_size: int | None = None) -> bytes:
        packet = bytes((command,)) + data
        checksum = 0
        for value in packet:
            checksum ^= value
        with self._lock:
            self.ser.reset_input_buffer()
            self.ser.write(packet + bytes((checksum,)))
            self.ser.flush()
            return self._read_exactly(len(data) if response_size is None else response_size)

    @staticmethod
    def _u16(data: bytes) -> int:
        return int.from_bytes(data, "big")

    @staticmethod
    def _encode_u16(value: int) -> bytes:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("value is outside the 16-bit protocol range")
        return value.to_bytes(2, "big")

    @classmethod
    def encode_tweak_offset(cls, value: float) -> int:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("tweak offset must be finite")
        raw = round(value * cls.TWEAK_OFFSET_SCALE + cls.TWEAK_OFFSET_RAW_BIAS)
        if not 0 <= raw <= 0xFFFF:
            minimum, maximum = cls.CALIBRATION_FIELDS[0].minimum, cls.CALIBRATION_FIELDS[0].maximum
            raise ValueError(
                f"tweak offset must be between {minimum:.1f} and {maximum:.1f} °C"
            )
        return raw

    @classmethod
    def decode_tweak_offset(cls, raw: int) -> float:
        if not 0 <= int(raw) <= 0xFFFF:
            raise ValueError("raw tweak offset is outside the 16-bit protocol range")
        return (int(raw) - cls.TWEAK_OFFSET_RAW_BIAS) / cls.TWEAK_OFFSET_SCALE

    @classmethod
    def encode_tweak_gain(cls, value: float) -> int:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("tweak gain must be finite")
        raw = round(value * cls.TWEAK_GAIN_SCALE)
        if not 0 <= raw <= 0xFFFF:
            minimum, maximum = cls.CALIBRATION_FIELDS[1].minimum, cls.CALIBRATION_FIELDS[1].maximum
            raise ValueError(
                f"tweak gain must be between {minimum:.8f} and {maximum:.8f}"
            )
        return raw

    @classmethod
    def decode_tweak_gain(cls, raw: int) -> float:
        if not 0 <= int(raw) <= 0xFFFF:
            raise ValueError("raw tweak gain is outside the 16-bit protocol range")
        return int(raw) / cls.TWEAK_GAIN_SCALE

    def read_temperature(self, command: int = OBJECT_TEMP) -> float:
        raw = self._u16(self.query_bytes(command, 2))
        return (raw - 1000) / 10.0

    def read_object_temperature(self) -> float:
        return self.read_temperature(self.OBJECT_TEMP)

    def read_head_temperature(self) -> float:
        return self.read_temperature(self.HEAD_TEMP)

    def read_box_temperature(self) -> float:
        return self.read_temperature(self.BOX_TEMP)

    def read_actual_temperature(self) -> float:
        return self.read_temperature(self.ACTUAL_TEMP)

    def read_emissivity(self) -> float:
        return self._u16(self.query_bytes(0x04, 2)) / 1000.0

    def set_emissivity(self, value: float):
        if not 0.001 <= value <= 1.0:
            raise ValueError("emissivity must be between 0.001 and 1.000")
        return self.set_bytes(0x84, self._encode_u16(round(value * 1000)))

    def read_transmission(self) -> float:
        return self._u16(self.query_bytes(0x05, 2)) / 1000.0

    def set_transmission(self, value: float):
        if not 0.001 <= value <= 1.0:
            raise ValueError("transmission must be between 0.001 and 1.000")
        return self.set_bytes(0x85, self._encode_u16(round(value * 1000)))

    def read_average_time(self) -> float:
        return self._u16(self.query_bytes(0x06, 2)) / 10.0

    def set_average_time(self, seconds: float):
        return self.set_bytes(0x86, self._encode_u16(round(seconds * 10)))

    def read_smart_averaging(self) -> bool:
        return bool(self.query_bytes(0x1C, 1)[0])

    def set_smart_averaging(self, enabled: bool):
        return self.set_bytes(0x9C, bytes((int(enabled),)))

    def read_peak_hold_time(self) -> float:
        return self._u16(self.query_bytes(0x08, 2)) / 10.0

    def set_peak_hold_time(self, seconds: float):
        return self.set_bytes(0x88, self._encode_u16(round(seconds * 10)))

    def read_functional_inputs(self) -> tuple[int, int, int]:
        data = self.query_bytes(0x75, 6)
        return tuple(self._u16(data[i:i + 2]) for i in range(0, 6, 2))

    def read_serial_number(self) -> int:
        return int.from_bytes(self.query_bytes(0x0E, 3), "big")

    def read_firmware_revision(self) -> int:
        return self._u16(self.query_bytes(0x0F, 2))

    def read_tweak_offset(self) -> float:
        raw = self._u16(self.query_bytes(self.READ_TWEAK_OFFSET, 2))
        return self.decode_tweak_offset(raw)

    def read_tweak_gain(self) -> float:
        raw = self._u16(self.query_bytes(self.READ_TWEAK_GAIN, 2))
        return self.decode_tweak_gain(raw)

    @staticmethod
    def _require_calibration_confirmation(confirmed: bool):
        if not confirmed:
            raise PermissionError(
                "pyrometer calibration writes require explicit confirmation"
            )

    def _set_calibration_raw(self, command: int, raw: int) -> int:
        payload = self._encode_u16(raw)
        echoed = self.set_bytes(command, payload, response_size=2)
        echoed_raw = self._u16(echoed)
        if echoed_raw != raw:
            raise CalibrationProtocolError(
                f"calibration SET echo mismatch: requested 0x{raw:04X}, "
                f"received 0x{echoed_raw:04X}"
            )
        return echoed_raw

    def set_tweak_offset(self, value: float, *, confirmed: bool = False) -> float:
        self._require_calibration_confirmation(confirmed)
        raw = self.encode_tweak_offset(value)
        echoed_raw = self._set_calibration_raw(self.SET_TWEAK_OFFSET, raw)
        return self.decode_tweak_offset(echoed_raw)

    def set_tweak_gain(self, value: float, *, confirmed: bool = False) -> float:
        self._require_calibration_confirmation(confirmed)
        raw = self.encode_tweak_gain(value)
        echoed_raw = self._set_calibration_raw(self.SET_TWEAK_GAIN, raw)
        return self.decode_tweak_gain(echoed_raw)

    def read_calibration(self) -> CalibrationSnapshot:
        """Read identity and calibration as one non-interleaved transaction."""
        with self._lock:
            serial_number = self.read_serial_number()
            firmware_revision = self.read_firmware_revision()
            raw_offset = self._u16(self.query_bytes(self.READ_TWEAK_OFFSET, 2))
            raw_gain = self._u16(self.query_bytes(self.READ_TWEAK_GAIN, 2))
            return CalibrationSnapshot(
                serial_number=serial_number,
                firmware_revision=firmware_revision,
                tweak_offset_C=self.decode_tweak_offset(raw_offset),
                tweak_gain=self.decode_tweak_gain(raw_gain),
                raw_offset=raw_offset,
                raw_gain=raw_gain,
            )

    def apply_calibration(
        self,
        expected: CalibrationSnapshot,
        proposed: Mapping[str, float],
        *,
        confirmed: bool = False,
    ) -> CalibrationApplyResult:
        """Compare, write changed fields once, then verify by reading the device.

        SET commands are deliberately never retried: a timeout leaves the device
        state ambiguous and the caller must read the calibration again.
        """
        self._require_calibration_confirmation(confirmed)
        if not isinstance(expected, CalibrationSnapshot):
            raise TypeError("expected must be a CalibrationSnapshot")
        allowed = {field.key for field in self.CALIBRATION_FIELDS}
        unknown = set(proposed) - allowed
        if unknown:
            raise ValueError(f"unknown calibration fields: {sorted(unknown)}")
        requested_offset = float(proposed.get("tweak_offset_C", expected.tweak_offset_C))
        requested_gain = float(proposed.get("tweak_gain", expected.tweak_gain))
        requested_raw = {
            "tweak_offset_C": self.encode_tweak_offset(requested_offset),
            "tweak_gain": self.encode_tweak_gain(requested_gain),
        }

        with self._lock:
            before = self.read_calibration()
            if (
                before.identity != expected.identity
                or before.raw_offset != expected.raw_offset
                or before.raw_gain != expected.raw_gain
            ):
                raise CalibrationStateChangedError(
                    "device identity or calibration changed since the last read; "
                    "read calibration again before writing"
                )

            original_raw = {
                "tweak_offset_C": before.raw_offset,
                "tweak_gain": before.raw_gain,
            }
            changed = [
                key for key in ("tweak_offset_C", "tweak_gain")
                if requested_raw[key] != original_raw[key]
            ]
            for key in changed:
                if key == "tweak_offset_C":
                    self._set_calibration_raw(
                        self.SET_TWEAK_OFFSET, requested_raw[key]
                    )
                else:
                    self._set_calibration_raw(
                        self.SET_TWEAK_GAIN, requested_raw[key]
                    )

            after = self.read_calibration()
            after_raw = {
                "tweak_offset_C": after.raw_offset,
                "tweak_gain": after.raw_gain,
            }
            statuses = {
                key: (
                    "verified" if key in changed and after_raw[key] == requested_raw[key]
                    else "mismatch" if key in changed
                    else "unchanged" if after_raw[key] == original_raw[key]
                    else "changed unexpectedly"
                )
                for key in ("tweak_offset_C", "tweak_gain")
            }
            return CalibrationApplyResult(
                before=before,
                requested={
                    "tweak_offset_C": self.decode_tweak_offset(
                        requested_raw["tweak_offset_C"]
                    ),
                    "tweak_gain": self.decode_tweak_gain(
                        requested_raw["tweak_gain"]
                    ),
                },
                after=after,
                statuses=statuses,
            )

    def read_settings(self):
        return {
            "emissivity": self.read_emissivity(),
            "transmission": self.read_transmission(),
            "average_time_s": self.read_average_time(),
            "smart_averaging": self.read_smart_averaging(),
            "peak_hold_s": self.read_peak_hold_time(),
        }

    def read_all(self):
        return {
            "object_temp_C": self.read_object_temperature(),
            "actual_temp_C": self.read_actual_temperature(),
            "head_temp_C": self.read_head_temperature(),
            "box_temp_C": self.read_box_temperature(),
        }
