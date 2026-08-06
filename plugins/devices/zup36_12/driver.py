import math
import re
import time

import serial


class ZUP36_12:
    _COMPLETE_STATUS_PATTERN = re.compile(
        r"^AV(?P<actual_voltage>.+?)"
        r"SV(?P<set_voltage>.+?)"
        r"AA(?P<actual_current>.+?)"
        r"SA(?P<set_current>.+?)"
        r"OS(?P<operational>[01]{8})"
        r"AL(?P<alarm>[01]{5})"
        r"PS(?P<programming_error>[01]+)$"
    )

    def __init__(
        self, port: str, baudrate: int = 9600, bytesize: int = 8,
        parity: str = "N", stopbits: float = 1, timeout: float = 2.0,
        write_timeout: float = 2.0, character_delay: float = 0.010,
        command_delay: float = 0.050, address: int = 1,
    ):
        if not 0 <= int(address) <= 31:
            raise ValueError("ZUP address must be between 0 and 31")
        if character_delay < 0:
            raise ValueError("character_delay must be zero or greater")
        if command_delay < 0:
            raise ValueError("command_delay must be zero or greater")
        self.address = int(address)
        self.character_delay = float(character_delay)
        self.command_delay = float(command_delay)
        self.ser = serial.Serial(
            port=port,
            baudrate=int(baudrate),
            bytesize=int(bytesize),
            parity=str(parity).upper(),
            stopbits=float(stopbits),
            timeout=float(timeout),
            write_timeout=float(write_timeout),
            xonxoff=True,
            rtscts=False,
            dsrdtr=False,
        )
        time.sleep(0.5)
        self.model = "Unknown"
        self.identification_error = ""
        try:
            self.model = self.identify()
        except (TimeoutError, serial.SerialException) as error:
            self.identification_error = str(error)
        self.write(":RMT1;")
        self.write(":AST0;")
        self.write(":OUT0;")

    def close(self):
        if self.ser and self.ser.is_open:
            try:
                for method, value in (
                    (self.output_off, None),
                    (self.set_voltage, 0.0),
                    (self.set_current, 0.0),
                ):
                    try:
                        method() if value is None else method(value)
                    except Exception:
                        pass
            finally:
                self.ser.close()

    @staticmethod
    def _normalize_command(command: str) -> str:
        command = str(command).strip()
        if not command:
            raise ValueError("ZUP command cannot be empty")
        if not command.endswith(";"):
            command += ";"
        return command

    def _write_characters(self, text: str):
        for character in text:
            self.ser.write(character.encode("ascii"))
            self.ser.flush()
            if self.character_delay:
                time.sleep(self.character_delay)

    def write(self, command: str):
        command = self._normalize_command(command)
        if command.startswith(":ADR"):
            self._write_characters(command)
            time.sleep(0.030)
        else:
            # The ZUP protocol requires a pause before ADR and an additional
            # 30 ms after the address before the actual command is sent.
            time.sleep(0.010)
            self._write_characters(f":ADR{self.address:02d};")
            time.sleep(0.030)
            self._write_characters(command)
        if self.command_delay:
            time.sleep(self.command_delay)

    def query(self, command: str, attempts: int = 1) -> str:
        command = self._normalize_command(command)
        attempts = max(1, int(attempts))
        for attempt in range(attempts):
            self.ser.reset_input_buffer()
            self.write(command)
            raw = self.ser.read_until(b"\n")
            if raw:
                return raw.decode("ascii", errors="replace").strip()
            if attempt + 1 < attempts:
                time.sleep(0.050)
        raise TimeoutError(f"No response to {command} after {attempts} attempts")

    def identify(self) -> str:
        return self.query(":MDL?;", attempts=2)

    def get_model(self) -> str:
        return self.model

    def get_identification_error(self) -> str:
        return self.identification_error

    @staticmethod
    def _fixed_value(value: float, name: str, minimum: float, maximum: float,
                     width: int, decimals: int) -> str:
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        if not minimum <= value <= maximum:
            raise ValueError(
                f"{name} must be between {minimum:g} and {maximum:g}"
            )
        return f"{value:0{width}.{decimals}f}"

    def set_voltage(self, voltage: float):
        # ZUP36 requires every digit in the 00.00 programming field.
        value = self._fixed_value(voltage, "Voltage", 0.0, 36.0, 5, 2)
        self.write(f":VOL{value};")

    def set_current(self, current: float):
        # ZUP36-12 requires every digit in the 00.000 programming field.
        value = self._fixed_value(current, "Current", 0.0, 12.0, 6, 3)
        self.write(f":CUR{value};")

    def output_on(self):
        self.write(":OUT1;")

    def output_off(self):
        self.write(":OUT0;")

    def set_ovp(self, voltage: float):
        value = self._fixed_value(voltage, "OVP", 1.8, 40.0, 4, 1)
        self.write(f":OVP{value};")

    def set_uvp(self, voltage: float):
        value = self._fixed_value(voltage, "UVP", 0.0, 35.9, 4, 1)
        self.write(f":UVP{value};")

    def set_foldback(self, enabled: bool):
        self.write(f":FLD{1 if enabled else 0};")

    def set_auto_restart(self, enabled: bool):
        self.write(f":AST{1 if enabled else 0};")

    @classmethod
    def parse_complete_status(cls, response: str):
        response = str(response).strip()
        match = cls._COMPLETE_STATUS_PATTERN.fullmatch(response)
        if match is None:
            raise ValueError(f"Unexpected STT response: {response!r}")
        fields = match.groupdict()
        try:
            return {
                "actual_voltage": float(fields["actual_voltage"]),
                "set_voltage": float(fields["set_voltage"]),
                "actual_current": float(fields["actual_current"]),
                "set_current": float(fields["set_current"]),
                "operational": fields["operational"],
                "alarm": fields["alarm"],
                "programming_error": fields["programming_error"],
            }
        except ValueError as error:
            raise ValueError(f"Invalid numeric value in STT response: {response!r}") from error

    def read_complete_status(self):
        return self.parse_complete_status(self.query(":STT?;", attempts=3))

    def read_monitoring(self):
        status = self.read_complete_status()
        voltage = status["actual_voltage"]
        current = status["actual_current"]
        operational = status["operational"]
        alarm = status["alarm"]
        programming_error = status["programming_error"]
        return {
            "voltage_V": voltage,
            "current_A": current,
            "power_W": voltage * current,
            "mode": "CC" if operational[0] == "1" else "CV",
            "output_on": operational[3] == "1",
            "ovp_fault": alarm[0] == "1",
            "ac_fault": alarm[1] == "1",
            "foldback_fault": alarm[2] == "1",
            "programming_fault": alarm[3] == "1",
            "otp_fault": alarm[4] == "1",
            "communication_error": "1" in programming_error,
            "operational_raw": f"OS{operational}",
            "alarm": f"AL{alarm}",
            "programming_error_raw": f"PS{programming_error}",
        }

    def read_settings(self):
        status = self.read_complete_status()
        operational = status["operational"]
        return {
            "voltage": status["set_voltage"],
            "current": status["set_current"],
            "foldback": operational[1] == "1",
            "auto_restart": operational[2] == "1",
            "output": operational[3] == "1",
        }

    def read_all(self):
        return self.read_monitoring()
