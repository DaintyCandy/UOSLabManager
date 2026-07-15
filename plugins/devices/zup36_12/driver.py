import time

import serial


class ZUP36_12:
    def __init__(self, port: str):
        self.ser = serial.Serial(
            port=port, baudrate=9600, bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            xonxoff=True, timeout=1,
        )
        time.sleep(0.5)
        self.write(":ADR01;")
        self.write(":RMT1;")
        self.write(":AST0;")
        self.write(":OUT0;")

    def close(self):
        if self.ser and self.ser.is_open:
            self.output_off()
            self.write(":RMT0;")
            self.ser.close()

    def write(self, command: str):
        self.ser.write((command + "\r\n").encode("ascii"))
        time.sleep(0.05)

    def query(self, command: str) -> str:
        self.ser.reset_input_buffer()
        self.write(command)
        response = self.ser.readline().decode("ascii", errors="replace").strip()
        if not response:
            raise TimeoutError(f"No response to {command}")
        return response

    def set_voltage(self, voltage: float):
        self.write(f":VOL{voltage:.2f};")

    def set_current(self, current: float):
        self.write(f":CUR{current:.3f};")

    def output_on(self):
        self.write(":OUT1;")

    def output_off(self):
        self.write(":OUT0;")

    def set_ovp(self, voltage: float):
        self.write(f":OVP{voltage:.1f};")

    def set_uvp(self, voltage: float):
        self.write(f":UVP{voltage:.1f};")

    def set_foldback(self, enabled: bool):
        self.write(f":FLD{1 if enabled else 0};")

    def set_auto_restart(self, enabled: bool):
        self.write(f":AST{1 if enabled else 0};")

    @staticmethod
    def _number(response: str, prefix: str) -> float:
        if not response.startswith(prefix):
            raise ValueError(f"Unexpected response: {response!r}")
        return float(response[len(prefix):])

    @staticmethod
    def _bits(response: str, prefix: str, width: int) -> str:
        if not response.startswith(prefix):
            raise ValueError(f"Unexpected response: {response!r}")
        return response[len(prefix):].strip().zfill(width)

    def read_monitoring(self):
        voltage = self._number(self.query(":VOL?;"), "AV")
        current = self._number(self.query(":CUR?;"), "AA")
        operational = self._bits(self.query(":STA?;"), "OS", 8)
        alarm = self._bits(self.query(":ALM?;"), "AL", 5)
        programming_error = self._bits(self.query(":STP?;"), "PS", 5)
        output_on = self.query(":OUT?;") == "OT1"
        return {
            "voltage_V": voltage,
            "current_A": current,
            "power_W": voltage * current,
            "mode": "CC" if operational[0] == "1" else "CV",
            "output_on": output_on,
            "ovp_fault": alarm[0] == "1",
            "ac_fault": alarm[1] == "1",
            "foldback_fault": alarm[2] == "1",
            "programming_fault": alarm[3] == "1",
            "otp_fault": alarm[4] == "1",
            "communication_error": programming_error != "00000",
            "operational_raw": f"OS{operational}",
            "alarm": f"AL{alarm}",
            "programming_error_raw": f"PS{programming_error}",
        }

    def read_settings(self):
        return {
            "voltage": self._number(self.query(":VOL!;"), "SV"),
            "current": self._number(self.query(":CUR!;"), "SA"),
            "ovp": self._number(self.query(":OVP?;"), "OP"),
            "uvp": self._number(self.query(":UVP?;"), "UP"),
            "foldback": self.query(":FLD?;") == "FD1",
            "auto_restart": self.query(":AST?;") == "AS1",
            "output": self.query(":OUT?;") == "OT1",
        }

    def read_all(self):
        return self.read_monitoring()
