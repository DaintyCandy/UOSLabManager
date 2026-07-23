import time
import serial


class GPD3303S:
    SUPPORTED_CHANNELS = ("CH1", "CH2")
    MAX_VOLTAGE = 30.0
    MAX_CURRENT = 3.0

    def __init__(
        self,
        port: str,
        timeout: float = 1.0,
        xonxoff: bool = False,
        rtscts: bool = False,
        write_termination: str = "\n",
        read_termination: str = "\r",
        command_delay: float = 0.1,
        output_off_on_connect: bool = False,
        output_off_on_close: bool = True,
    ):
        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            xonxoff=xonxoff,
            rtscts=rtscts,
        )
        self.write_termination = write_termination
        self.read_termination = read_termination
        self.command_delay = command_delay
        self.output_off_on_close = bool(output_off_on_close)
        self.channel_settings = {channel: {"voltage": None, "current": None} for channel in self.SUPPORTED_CHANNELS}

        if output_off_on_connect:
            self.output_off()

    def close(self):
        if self.ser and self.ser.is_open:
            try:
                if self.output_off_on_close:
                    self.output_off()
            finally:
                self.ser.close()

    def _validate_channel(self, channel: str) -> str:
        normalized = channel.upper().strip()
        if normalized not in self.SUPPORTED_CHANNELS:
            raise ValueError(f"Invalid channel: {channel}")
        return normalized

    @classmethod
    def _validate_voltage(cls, voltage: float) -> float:
        if not isinstance(voltage, (int, float)):
            raise TypeError("Voltage must be a number")
        if not 0.0 <= voltage <= cls.MAX_VOLTAGE:
            raise ValueError(f"Voltage must be between 0 and {cls.MAX_VOLTAGE} V")
        return float(voltage)

    @classmethod
    def _validate_current(cls, current: float) -> float:
        if not isinstance(current, (int, float)):
            raise TypeError("Current must be a number")
        if not 0.0 <= current <= cls.MAX_CURRENT:
            raise ValueError(f"Current must be between 0 and {cls.MAX_CURRENT} A")
        return float(current)

    def write(self, command: str):
        packet = (command + self.write_termination).encode("ascii")
        self.ser.write(packet)
        try:
            self.ser.flush()
        except Exception:
            pass
        time.sleep(self.command_delay)

    def reset_input_buffer(self):
        if hasattr(self.ser, "reset_input_buffer"):
            self.ser.reset_input_buffer()

    def query(self, command: str, timeout: float | None = None) -> str:
        self.reset_input_buffer()
        self.write(command)
        old_timeout = getattr(self.ser, "timeout", None)
        if timeout is not None:
            self.ser.timeout = timeout
        try:
            terminator = self.read_termination.encode("ascii") if self.read_termination else None
            response = self.ser.read_until(expected=terminator)
            if not response:
                raise TimeoutError(f"No response to {command}")
            text = response.decode("ascii", errors="replace")
            if self.read_termination and text.endswith(self.read_termination):
                text = text[: -len(self.read_termination)]
            return text.strip()
        finally:
            if timeout is not None:
                self.ser.timeout = old_timeout

    @staticmethod
    def _parse_numeric_with_unit(response: str, expected_unit: str) -> float:
        if not isinstance(response, str):
            raise TypeError(f"Response must be a string, got {type(response).__name__}")
        raw = response.strip().upper()
        if not raw.endswith(expected_unit.upper()):
            raise ValueError(f"Expected response ending with {expected_unit!r}, got {response!r}")
        numeric_part = raw[: -len(expected_unit)].strip()
        if numeric_part == "":
            raise ValueError(f"Missing numeric value before unit in {response!r}")
        try:
            return float(numeric_part)
        except ValueError as error:
            raise ValueError(f"Invalid numeric value in response {response!r}") from error

    def identify(self) -> str:
        response = self.query("*IDN?", timeout=2.0)
        normalized = response.upper()
        if "GW INSTEK" not in normalized or ("GPD-3303" not in normalized and "GPD3303" not in normalized):
            raise ValueError(f"Unexpected identity response: {response}")
        return response

    def _ensure_channel_settings(self):
        for channel, settings in self.channel_settings.items():
            if settings["voltage"] is None or settings["current"] is None:
                raise RuntimeError(f"Channel {channel} voltage and current must both be set before enabling output")

    def output_on(self):
        self._ensure_channel_settings()
        self.write("OUT1")

    def output_off(self):
        self.write("OUT0")

    def _status_for_output(self, raw: str) -> bool:
        normalized = raw.strip().upper()
        if normalized in {"1", "ON", "OUT1"}:
            return True
        if normalized in {"0", "OFF", "OUT0"}:
            return False
        if "ON" in normalized:
            return True
        if "OFF" in normalized:
            return False
        if normalized.startswith("STATUS") and "1" in normalized:
            return True
        return False

    @staticmethod
    def _decode_status(raw: str) -> dict[str, object]:
        if not isinstance(raw, str):
            raise TypeError("STATUS response must be a string")
        raw = raw.strip()
        if len(raw) != 8 or any(ch not in "01" for ch in raw):
            raise ValueError(f"STATUS? response must be exactly 8 bits, got {raw!r}")
        status_int = int(raw, 2)
        output_on = bool(status_int & (1 << 6))
        ch1_mode = "CV" if bool(status_int & (1 << 0)) else "CC"
        ch2_mode = "CV" if bool(status_int & (1 << 1)) else "CC"
        beep = bool(status_int & (1 << 4))
        bit2 = bool(status_int & (1 << 2))
        bit3 = bool(status_int & (1 << 3))
        tracking_code = f"{int(bit2)}{int(bit3)}"
        tracking_mode = {
            "01": "Independent",
            "11": "Series",
            "10": "Parallel",
        }.get(tracking_code, "Unknown")
        return {
            "status_raw": raw,
            "status_int": status_int,
            "output_on": output_on,
            "ch1_mode": ch1_mode,
            "ch2_mode": ch2_mode,
            "beep": beep,
            "tracking_mode": tracking_mode,
        }

    def read_status(self) -> dict[str, object]:
        raw = self.query("STATUS?", timeout=2.0)
        return self._decode_status(raw)

    def set_channel_voltage(self, channel: str, voltage: float):
        voltage = self._validate_voltage(voltage)
        channel = self._validate_channel(channel)
        command = "VSET1" if channel == "CH1" else "VSET2"
        self.write(f"{command}:{voltage:.3f}")
        self.channel_settings[channel]["voltage"] = voltage

    def set_channel_current(self, channel: str, current: float):
        current = self._validate_current(current)
        channel = self._validate_channel(channel)
        command = "ISET1" if channel == "CH1" else "ISET2"
        self.write(f"{command}:{current:.3f}")
        self.channel_settings[channel]["current"] = current

    def read_channel_measurement(self, channel: str) -> tuple[float, float]:
        channel = self._validate_channel(channel)
        voltage = self._parse_numeric_with_unit(
            self.query("VOUT1?" if channel == "CH1" else "VOUT2?"), "V"
        )
        current = self._parse_numeric_with_unit(
            self.query("IOUT1?" if channel == "CH1" else "IOUT2?"), "A"
        )
        return voltage, current

    def read_monitoring(self):
        ch1_voltage, ch1_current = self.read_channel_measurement("CH1")
        ch2_voltage, ch2_current = self.read_channel_measurement("CH2")
        status = self.read_status()
        return {
            "CH1_voltage_V": ch1_voltage,
            "CH1_current_A": ch1_current,
            "CH2_voltage_V": ch2_voltage,
            "CH2_current_A": ch2_current,
            "status_raw": status["status_raw"],
            "status_int": status["status_int"],
            "output_on": status["output_on"],
            "ch1_mode": status["ch1_mode"],
            "ch2_mode": status["ch2_mode"],
            "beep": status["beep"],
            "tracking_mode": status["tracking_mode"],
        }

    def read_settings(self):
        result = {
            "CH1_voltage_setpoint": self._parse_numeric_with_unit(self.query("VSET1?"), "V"),
            "CH1_current_setpoint": self._parse_numeric_with_unit(self.query("ISET1?"), "A"),
            "CH2_voltage_setpoint": self._parse_numeric_with_unit(self.query("VSET2?"), "V"),
            "CH2_current_setpoint": self._parse_numeric_with_unit(self.query("ISET2?"), "A"),
        }
        status = self.read_status()
        result["output_on"] = status["output_on"]
        result["status_raw"] = status["status_raw"]
        result["status_int"] = status["status_int"]
        result["ch1_mode"] = status["ch1_mode"]
        result["ch2_mode"] = status["ch2_mode"]
        result["beep"] = status["beep"]
        result["tracking_mode"] = status["tracking_mode"]
        return result

    def read_all(self):
        return self.read_monitoring()
