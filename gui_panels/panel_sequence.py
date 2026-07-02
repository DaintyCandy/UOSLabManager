import time
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, 
                             QLabel, QPushButton, QListWidget, QDoubleSpinBox, 
                             QStackedWidget, QMessageBox, QSpacerItem, QSizePolicy)
from PyQt6.QtCore import QThread, pyqtSignal

# gui_panels/panel_sequence.py 내의 SequenceWorker 클래스 부분만 수정

class SequenceWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, sequence_list, manager):
        super().__init__()
        self.sequence_list = sequence_list
        self.manager = manager
        self.is_running = True

    def run(self):
        self.log_signal.emit("▶ SEQUENCE START")
        
        for step, cmd in enumerate(self.sequence_list, 1):
            if not self.is_running: break
            self.log_signal.emit(f"--- Step {step} ---")
            
            if cmd["device"] == "LS331":
                ls = self.manager.get_device("LS331")
                if not ls:
                    self.log_signal.emit("❌ LS331 Not Connected")
                    break
                    
                if cmd["type"] == "smart_temp":
                    # 1. 설정값 전송
                    ls.set_ramp(cmd["ramp"] > 0, cmd["ramp"])
                    ls.set_setpoint(cmd["temp"])
                    self.log_signal.emit(f"✅ Target: {cmd['temp']}K Set.")
                    
                    # 2. 도달 대기
                    self.log_signal.emit(f"⏳ Waiting for {cmd['temp']}K...")
                    while self.is_running:
                        # 통신 충돌을 줄이기 위해 메인 타이머와 엇박자로 읽음
                        time.sleep(1.1) 
                        
                        data = self.manager.read_all().get("LS331", {})
                        
                        # 에러가 들어오면 건너뛰고 재시도
                        if "error" in data or not data:
                            continue
                            
                        current_temp = data.get("A_temp_K")
                        if current_temp is not None and current_temp != "":
                            try:
                                curr = float(current_temp)
                                if abs(curr - cmd["temp"]) <= 0.5:
                                    self.log_signal.emit(f"🎯 Reached: {curr}K")
                                    break
                            except: continue
                    
                    # 3. 유지 시간
                    if cmd["hold"] > 0 and self.is_running:
                        self.log_signal.emit(f"⏱ Holding for {cmd['hold']} min...")
                        for _ in range(int(cmd["hold"] * 60)):
                            if not self.is_running: break
                            time.sleep(1)
                        self.log_signal.emit("✅ Hold finished.")

        self.log_signal.emit("🏁 SEQUENCE FINISHED")
        self.finished_signal.emit()

class SequencePanel(QWidget):
    def __init__(self, device_manager, log_callback):
        super().__init__()
        self.manager = device_manager
        self.log = log_callback
        self.sequence_list = []
        self.worker = None
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        self.combo_device = QComboBox()
        self.combo_device.addItems(["Lakeshore 331", "Keithley 2400", "System (Wait)"])
        self.combo_device.currentTextChanged.connect(self.update_function_combo)
        
        self.combo_function = QComboBox()
        self.combo_function.currentTextChanged.connect(self.update_input_widget)

        self.stacked_inputs = QStackedWidget()
        self.setup_input_widgets()

        self.btn_add = QPushButton("Add")
        self.btn_add.setStyleSheet("background-color: #66b3ff; font-weight: bold;")
        self.btn_add.clicked.connect(self.add_sequence)

        top_layout.addWidget(self.combo_device)
        top_layout.addWidget(self.combo_function)
        top_layout.addWidget(self.stacked_inputs)
        top_layout.addWidget(self.btn_add)

        self.list_widget = QListWidget()
        
        bottom_layout = QHBoxLayout()
        self.btn_clear = QPushButton("Clear Sequence")
        self.btn_clear.clicked.connect(self.clear_sequence)
        
        spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        
        self.btn_execute = QPushButton("Execute Sequence")
        self.btn_execute.setMinimumSize(130, 40)
        self.btn_execute.setStyleSheet("background-color: #ff9999; font-weight: bold;")
        self.btn_execute.clicked.connect(self.toggle_execute)
        
        bottom_layout.addWidget(self.btn_clear)
        bottom_layout.addItem(spacer)
        bottom_layout.addWidget(self.btn_execute)

        main_layout.addLayout(top_layout)
        main_layout.addWidget(self.list_widget)
        main_layout.addLayout(bottom_layout)

        self.update_function_combo(self.combo_device.currentText())

    def setup_input_widgets(self):
        # [0] Set Temp
        self.w_ls_temp = QWidget()
        l = QHBoxLayout(self.w_ls_temp); l.setContentsMargins(0,0,0,0)
        self.spin_ls_temp = QDoubleSpinBox(); self.spin_ls_temp.setRange(0, 1000); self.spin_ls_temp.setValue(300)
        self.spin_ls_ramp = QDoubleSpinBox(); self.spin_ls_ramp.setRange(0, 100); self.spin_ls_ramp.setValue(0)
        l.addWidget(QLabel("Temp[K]:")); l.addWidget(self.spin_ls_temp)
        l.addWidget(QLabel("Ramp[K/min]:")); l.addWidget(self.spin_ls_ramp)

        # [1] Wait Temp (여기서 Tol 싹 지우고 직관적으로 만들었습니다!)
        self.w_ls_wait = QWidget()
        l = QHBoxLayout(self.w_ls_wait); l.setContentsMargins(0,0,0,0)
        self.spin_ls_wtarget = QDoubleSpinBox(); self.spin_ls_wtarget.setRange(0, 1000); self.spin_ls_wtarget.setValue(300)
        l.addWidget(QLabel("Wait until reach [K]:")); l.addWidget(self.spin_ls_wtarget)

        # [2] System Wait Time
        self.w_sys_wait = QWidget()
        l = QHBoxLayout(self.w_sys_wait); l.setContentsMargins(0,0,0,0)
        self.spin_sys_time = QDoubleSpinBox(); self.spin_sys_time.setRange(0.1, 1000); self.spin_sys_time.setValue(2.0)
        l.addWidget(QLabel("Wait Minutes:")); l.addWidget(self.spin_sys_time)

        self.stacked_inputs.addWidget(self.w_ls_temp)
        self.stacked_inputs.addWidget(self.w_ls_wait)
        self.stacked_inputs.addWidget(self.w_sys_wait)

    def update_function_combo(self, device):
        self.combo_function.blockSignals(True)
        self.combo_function.clear()
        if device == "Lakeshore 331":
            self.combo_function.addItems(["Set Temp & Ramp", "Wait until Temp Reached"])
        elif device == "System (Wait)":
            self.combo_function.addItems(["Wait for Time (Min)"])
        self.combo_function.blockSignals(False)
        self.update_input_widget(self.combo_function.currentText())

    def update_input_widget(self, func):
        if func == "Set Temp & Ramp": self.stacked_inputs.setCurrentIndex(0)
        elif func == "Wait until Temp Reached": self.stacked_inputs.setCurrentIndex(1)
        elif func == "Wait for Time (Min)": self.stacked_inputs.setCurrentIndex(2)

    def add_sequence(self):
        device = self.combo_device.currentText()
        func = self.combo_function.currentText()
        
        if func == "Set Temp & Ramp":
            t = self.spin_ls_temp.value(); r = self.spin_ls_ramp.value()
            r_str = f"{r}K/min" if r > 0 else "No Ramp"
            val_str = f"Target: {t}K, Ramp: {r_str}"
            cmd = {"device": "LS331", "type": "temp", "temp": t, "ramp": r}
            
        elif func == "Wait until Temp Reached":
            t = self.spin_ls_wtarget.value()
            val_str = f"Target: {t}K"  # 복잡한 말 지우고 깔끔하게!
            cmd = {"device": "LS331", "type": "wait_temp", "target": t}

        elif func == "Wait for Time (Min)":
            m = self.spin_sys_time.value()
            val_str = f"{m} Minutes"
            cmd = {"device": "System", "type": "wait_time", "min": m}

        self.list_widget.addItem(f"{self.list_widget.count()+1}. [{device}] {func} ➔ {val_str}")
        self.sequence_list.append(cmd)

    def clear_sequence(self):
        self.list_widget.clear()
        self.sequence_list.clear()

    def toggle_execute(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.btn_execute.setText("Stopping...")
            self.btn_execute.setEnabled(False)
            return

        if not self.sequence_list:
            QMessageBox.warning(self, "Warning", "No sequence to execute!")
            return

        self.worker = SequenceWorker(self.sequence_list, self.manager)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_sequence_finished)
        
        self.btn_execute.setText("STOP ABORT")
        self.btn_execute.setStyleSheet("background-color: #ff3333; color: white; font-weight: bold;")
        self.worker.start()

    def on_sequence_finished(self):
        self.btn_execute.setText("Execute Sequence")
        self.btn_execute.setStyleSheet("background-color: #ff9999; font-weight: bold;")
        self.btn_execute.setEnabled(True)