import time
import serial


class LakeShore331:
    #RS-232 기본연결설정
    def __init__(self, port: str):
        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.SEVENBITS,
            parity=serial.PARITY_ODD,
            stopbits=serial.STOPBITS_ONE,
            timeout=1,
        )
        time.sleep(0.2)

    def read_all(self):#한 번에 읽어오기
        return {
            "A_temp_K": self.read_temp("A"),
            "B_temp_K": self.read_temp("B"),
            "setpoint_K": self.get_setpoint(loop=1),
            "heater_range": self.get_heater_range(),
        }
    
    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def write(self, cmd: str):
        self.ser.write((cmd + "\r\n").encode("ascii"))

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self.ser.readline().decode("ascii", errors="replace").strip()

    def read_temp(self, channel: str = "A") -> float:
        channel = channel.upper()
        if channel not in ("A", "B"):
            raise ValueError("channel must be 'A' or 'B'")
        return float(self.query(f"KRDG? {channel}"))

    def read_sensor(self, channel: str = "A") -> float:
        channel = channel.upper()
        return float(self.query(f"SRDG? {channel}"))

    def get_setpoint(self, loop: int = 1) -> float:
        return float(self.query(f"SETP? {loop}"))

    def set_setpoint(self, value: float, loop: int = 1):
        self.write(f"SETP {loop},{value}")

    def get_pid(self, loop: int = 1):
        p, i, d = self.query(f"PID? {loop}").split(",")
        return float(p), float(i), float(d)

    def set_pid(self, p: float, i: float, d: float = 0, loop: int = 1):
        self.write(f"PID {loop},{p},{i},{d}")

    def get_manual_output(self, loop: int = 1) -> float:
        return float(self.query(f"MOUT? {loop}"))

    def set_manual_output(self, value: float, loop: int = 1):
        if not 0 <= value <= 100:
            raise ValueError("manual output must be 0–100 %")
        self.write(f"MOUT {loop},{value}")

    def get_heater_range(self) -> int:
        return int(self.query("RANGE?"))

    def set_heater_range(self, range_value: int):
        """
        0: Off
        1: Low
        2: Medium
        3: High
        """
        if range_value not in (0, 1, 2, 3):
            raise ValueError("range_value must be 0, 1, 2, or 3")
        self.write(f"RANGE {range_value}")

    def heater_off(self):
        self.set_heater_range(0)

    def get_ramp(self, loop: int = 1):
        enabled, rate = self.query(f"RAMP? {loop}").split(",")
        return bool(int(enabled)), float(rate)

    def set_ramp(self, enabled: bool, rate: float, loop: int = 1):
        self.write(f"RAMP {loop},{int(enabled)},{rate}")

    def is_ramping(self, loop: int = 1) -> bool:
        return bool(int(self.query(f"RAMPST? {loop}")))

    def input_status(self, channel: str = "A") -> int:
        channel = channel.upper()
        return int(self.query(f"RDGST? {channel}"))