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
        self.enabled_inputs = {"A": True, "B": True}
        self.filter_windows = {"A": 10, "B": 10}
        time.sleep(0.2)

    def read_all(self):#한 번에 읽어오기
        return {
            "A_temp_K": self.read_temp("A") if self.enabled_inputs["A"] else "",
            "B_temp_K": self.read_temp("B") if self.enabled_inputs["B"] else "",
            "A_sensor": self.read_sensor("A") if self.enabled_inputs["A"] else "",
            "B_sensor": self.read_sensor("B") if self.enabled_inputs["B"] else "",
            "setpoint_K": self.get_setpoint(loop=1),
            "heater_range": self.get_heater_range(),
        }

    def set_input_enabled(self, channel: str, enabled: bool):
        self.enabled_inputs[channel.upper()] = bool(enabled)

    def get_input_enabled(self, channel: str) -> bool:
        return self.enabled_inputs.get(channel.upper(), False)
    
    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def write(self, cmd: str):
        self.ser.write((cmd + "\r\n").encode("ascii"))
        self.ser.flush()
        # The 331 can silently miss commands sent back-to-back while it is
        # committing an input or curve change.
        time.sleep(0.05)

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

    def get_control_mode(self, loop: int = 1) -> int:
        return int(self.query(f"CMODE? {loop}"))

    def set_control_mode(self, mode: int, loop: int = 1):
        if mode not in (1, 2, 3, 4, 5, 6):
            raise ValueError("control mode must be between 1 and 6")
        self.write(f"CMODE {loop},{mode}")

    def get_control_setup(self, loop: int = 1):
        input_channel, units, powerup, output_display = self.query(f"CSET? {loop}").split(",")
        return input_channel.strip().upper(), int(units), bool(int(powerup)), int(output_display)

    def set_control_setup(self, input_channel: str, units: int, powerup: bool, output_display: int, loop: int = 1):
        input_channel = input_channel.upper()
        if input_channel not in ("A", "B"):
            raise ValueError("control input must be A or B")
        if units not in (1, 2, 3) or output_display not in (1, 2):
            raise ValueError("invalid control setup value")
        self.write(f"CSET {loop},{input_channel},{units},{int(powerup)},{output_display}")

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

    def get_filter(self, channel: str):
        channel = channel.upper()
        values = self.query(f"FILTER? {channel}").split(",")
        if len(values) < 2:
            raise ValueError(f"Unexpected FILTER response for input {channel}: {','.join(values)}")
        enabled, points = values[:2]
        if len(values) >= 3:
            self.filter_windows[channel] = int(float(values[2]))
        return bool(int(enabled)), int(points)

    def set_filter(self, channel: str, enabled: bool, points: int):
        channel = channel.upper()
        if not 2 <= points <= 64:
            raise ValueError("filter points must be between 2 and 64")
        window = self.filter_windows.get(channel, 10)
        self.write(f"FILTER {channel},{int(enabled)},{points},{window}")

    def get_curve_header(self, curve: int):
        name, serial_number, data_format, limit, coefficient = self.query(f"CRVHDR? {curve}").split(",")
        return name.strip(), serial_number.strip(), int(data_format), float(limit), int(coefficient)

    def set_curve_header(self, curve: int, name: str, serial_number: str, data_format: int, limit: float, coefficient: int):
        if not 21 <= curve <= 41:
            raise ValueError("only user curves 21 through 41 can be edited")
        self.write(f"CRVHDR {curve},{name[:15]},{serial_number[:10]},{data_format},{limit},{coefficient}")

    def get_curve_point(self, curve: int, index: int):
        sensor_units, temperature = self.query(f"CRVPT? {curve},{index}").split(",")
        return float(sensor_units), float(temperature)

    def get_curve_points(self, curve: int):
        """Read programmed points, stopping at the first unused 0/0 entry."""
        points = []
        for index in range(1, 201):
            sensor_units, temperature = self.get_curve_point(curve, index)
            if sensor_units == 0.0 and temperature == 0.0:
                break
            points.append((sensor_units, temperature))
        return points

    def set_curve_point(self, curve: int, index: int, sensor_units: float, temperature: float):
        if not 21 <= curve <= 41 or not 1 <= index <= 200:
            raise ValueError("invalid user curve or point index")
        self.write(f"CRVPT {curve},{index},{sensor_units},{temperature}")

    def delete_curve(self, curve: int):
        if not 21 <= curve <= 41:
            raise ValueError("only user curves 21 through 41 can be deleted")
        self.write(f"CRVDEL {curve}")

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
