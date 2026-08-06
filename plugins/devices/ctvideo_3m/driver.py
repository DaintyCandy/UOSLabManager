"""Optris CTvideo 3M binary serial driver.

Protocol reference: CT-CTlaser-CTvideo-commands-2018-11.pdf.
"""

import threading
import time

import serial


class CTVideo3M:
    OBJECT_TEMP = 0x01
    HEAD_TEMP = 0x02
    BOX_TEMP = 0x03
    ACTUAL_TEMP = 0x81

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
