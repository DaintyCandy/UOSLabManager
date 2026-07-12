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
    
    # ==========================================
    # --- [추가] Input / Sensor Configuration ---
    # ==========================================

    def set_input_type(self, channel: str, sensor_type: int, compensation: bool):
        """
        매뉴얼 6-33 (INTYPE 명령어)
        센서 종류와 보정(Room comp 또는 Thermal EMF) 여부를 설정합니다.
        """
        channel = channel.upper()
        comp_val = 1 if compensation else 0
        self.write(f"INTYPE {channel},{sensor_type},{comp_val}")

    def get_input_type(self, channel: str):
        """현재 센서 타입과 보정 여부를 읽어옵니다."""
        channel = channel.upper()
        response = self.query(f"INTYPE? {channel}").split(",")
        # 반환값: (sensor_type, compensation_bool)
        return int(response[0]), bool(int(response[1]))

    def set_input_curve(self, channel: str, curve: int):
        """
        매뉴얼 6-32 (INCRV 명령어)
        온도 변환 곡선(Curve)을 설정합니다.
        """
        channel = channel.upper()
        # 커브 번호는 보통 2자리 숫자로 보냅니다 (예: 01, 06)
        self.write(f"INCRV {channel},{curve:02d}")

    def get_input_curve(self, channel: str) -> int:
        """현재 설정된 커브 번호를 읽어옵니다."""
        channel = channel.upper()
        return int(self.query(f"INCRV? {channel}"))

    def set_thermocouple(self, channel: str, voltage_range_mv: int, curve: int, room_compensation: bool):
        """
        열전대(Thermocouple) 전용 원클릭 셋업 함수
        """
        channel = channel.upper()
        # 25mV 범위면 타입 6, 50mV 범위면 타입 7
        sensor_type = 6 if voltage_range_mv == 25 else 7
        comp_val = 1 if room_compensation else 0
        
        # 센서 타입 설정 후 커브 설정
        self.write(f"INTYPE {channel},{sensor_type},{comp_val}")
        time.sleep(0.1) # 설정이 먹힐 시간 부여
        self.write(f"INCRV {channel},{curve:02d}")
