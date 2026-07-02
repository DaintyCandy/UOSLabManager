from PyQt6.QtWidgets import QWidget, QGroupBox, QGridLayout, QLabel, QPushButton, QDoubleSpinBox, QMessageBox
from datetime import datetime

class KeithleyPanel(QWidget):
    def __init__(self, device_manager, log_callback):
        super().__init__()
        self.manager = device_manager  # 장비 연결 매니저를 메인에서 넘겨받음
        self.log = log_callback        # 로그 박스에 글을 쓰는 함수를 메인에서 넘겨받음
        
        self.init_ui()

    def init_ui(self):
        # 1. UI 디자인 (main_gui_3.py에 있던 내용 그대로 가져옴)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0) # 여백 제거

        k_group = QGroupBox("Keithley 2400 Control")
        k_layout = QGridLayout(k_group)

        self.k_voltage_spin = QDoubleSpinBox()
        self.k_voltage_spin.setRange(-200.0, 200.0)
        self.k_voltage_spin.setValue(0.0)
        self.k_set_voltage_btn = QPushButton("Set K2400 Voltage")
        self.k_output_on_btn = QPushButton("Output ON")
        self.k_output_off_btn = QPushButton("Output OFF")

        k_layout.addWidget(QLabel("Voltage [V]:"), 0, 0)
        k_layout.addWidget(self.k_voltage_spin, 0, 1)
        k_layout.addWidget(self.k_set_voltage_btn, 0, 2)
        k_layout.addWidget(self.k_output_on_btn, 1, 0, 1, 1)
        k_layout.addWidget(self.k_output_off_btn, 1, 1, 1, 2)
        
        layout.addWidget(k_group)

        # 2. 버튼 클릭 시 함수 연결
        self.k_set_voltage_btn.clicked.connect(self.set_k2400_voltage)
        self.k_output_on_btn.clicked.connect(self.k2400_output_on)
        self.k_output_off_btn.clicked.connect(self.k2400_output_off)

    # 3. K2400 제어 함수들 (역시 main_gui_3.py에서 이사 옴)
    def set_k2400_voltage(self):
        try:
            smu = self.manager.get_device("K2400")
            if smu is None:
                self.log("K2400 is not connected!")
                return
            voltage = self.k_voltage_spin.value()
            smu.set_voltage_source(voltage=voltage, current_limit=0.01)
            self.log(f"K2400 voltage set to {voltage} V")
        except Exception as e:
            QMessageBox.critical(self, "K2400 Error", str(e))

    def k2400_output_on(self):
        smu = self.manager.get_device("K2400")
        if smu is not None:
            smu.output_on()
            self.log("K2400 output ON")

    def k2400_output_off(self):
        smu = self.manager.get_device("K2400")
        if smu is not None:
            smu.output_off()
            self.log("K2400 output OFF")