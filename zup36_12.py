# --- START OF FILE zup36_12.py ---
import time
import serial

class ZUP36_12:
    def __init__(self, port: str):
        # 매뉴얼 5.6.4 참조: 9600, 8 data bits, None Parity, 1 Stop bit, Xon/Xoff Flow Control
        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            xonxoff=True, # ZUP 필수 설정
            timeout=1,
        )
        time.sleep(0.5)

        # 1. 초기화: 주소 01번 호출 (매뉴얼 5.6.2)
        self.write(":ADR01;")
        time.sleep(0.1)
        
        # 2. 리모트 모드 활성화 (매뉴얼 5.5.1)
        self.write(":RMT1;")
        
        # 3. 안전 설정: Auto-restart OFF, Output OFF
        self.write(":AST0;")
        self.write(":OUT0;")
        time.sleep(0.1)

    def close(self):
        if self.ser and self.ser.is_open:
            self.write(":OUT0;") # 끄기 전에 출력 차단
            self.write(":RMT0;") # 로컬 모드로 복귀
            self.ser.close()

    def write(self, cmd: str):
        self.ser.write((cmd + "\r\n").encode("ascii"))
        time.sleep(0.05) # ZUP는 명령어 사이 약간의 딜레이가 필요함

    def query(self, cmd: str) -> str:
        self.ser.flushInput() # 버퍼 비우기
        self.write(cmd)
        return self.ser.readline().decode("ascii", errors="replace").strip()

    # --- 출력 제어 ---
    def set_voltage(self, voltage: float):
        self.write(f":VOL{voltage:.3f};")

    def set_current(self, current: float):
        self.write(f":CUR{current:.3f};")

    def output_on(self):
        self.write(":OUT1;")

    def output_off(self):
        self.write(":OUT0;")

    # --- 보호 기능 설정 ---
    def set_ovp(self, voltage: float):
        self.write(f":OVP{voltage:.1f};")

    def set_uvp(self, voltage: float):
        self.write(f":UVP{voltage:.1f};")

    # --- 데이터 및 상태 읽기 ---
    def read_all(self):
        # 매뉴얼 5.5.3: :VOL? 은 AV(실제전압) 반환, :CUR? 은 AA(실제전류) 반환
        try:
            vol_str = self.query(":VOL?;") # 예: 'AV12.000'
            cur_str = self.query(":CUR?;") # 예: 'AA05.000'
            alm_str = self.query(":ALM?;") # 예: 'AL00000' (정상)

            actual_v = float(vol_str.replace("AV", "")) if "AV" in vol_str else 0.0
            actual_a = float(cur_str.replace("AA", "")) if "AA" in cur_str else 0.0
            
            return {
                "voltage_V": actual_v,
                "current_A": actual_a,
                "alarm": alm_str
            }
        except Exception as e:
            return {"error": str(e)}