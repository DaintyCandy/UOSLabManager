import time
from PyQt6.QtWidgets import (QWidget, QGroupBox, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QComboBox, QDoubleSpinBox, 
                             QListWidget, QListWidgetItem, QStackedWidget, 
                             QMessageBox, QAbstractItemView)
from PyQt6.QtCore import Qt, QTimer

class SequencePanel(QWidget):
    def __init__(self, device_manager, log_callback):
        super().__init__()
        self.manager = device_manager
        self.log = log_callback
        
        self.sequence_steps = []
        self.current_step_idx = 0
        self.is_running = False
        
        self.state = "IDLE" 
        self.target_temp = 0.0
        self.wait_until = 0.0
        self.ramp_active_flag = False # Ramp가 켜져 있는지 추적

        self.engine_timer = QTimer()
        self.engine_timer.setInterval(1000)
        self.engine_timer.timeout.connect(self.run_engine)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        group = QGroupBox("Sequence Builder")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        # 1. 상단 입력부
        input_box = QHBoxLayout()
        input_box.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.dev_combo = QComboBox()
        self.dev_combo.addItems(["LS331", "K2400", "ZUP36-12"])
        self.dev_combo.setFixedWidth(80)
        self.dev_combo.currentTextChanged.connect(self.on_dev_changed)
        
        self.cmd_combo = QComboBox()
        self.cmd_combo.setFixedWidth(110)
        self.cmd_combo.currentTextChanged.connect(self.on_cmd_changed)
        
        self.val_stack = QStackedWidget()
        self.val_stack.setFixedSize(90, 25)
        
        self.val_spin = QDoubleSpinBox()
        self.val_spin.setRange(-200, 1000)
        self.val_spin.setValue(300.0)
        
        self.heater_combo = QComboBox()
        self.heater_combo.addItems(["Off", "Low", "Medium", "High"])
        
        self.val_stack.addWidget(self.val_spin)
        self.val_stack.addWidget(self.heater_combo)
        
        self.unit_label = QLabel("K")
        self.unit_label.setFixedWidth(30)
        
        self.add_btn = QPushButton("Add")
        self.add_btn.setFixedSize(50, 28)
        self.add_btn.clicked.connect(self.add_to_stack)

        input_box.addWidget(self.dev_combo)
        input_box.addWidget(self.cmd_combo)
        input_box.addWidget(self.val_stack)
        input_box.addWidget(self.unit_label)
        input_box.addWidget(self.add_btn)
        layout.addLayout(input_box)

        # 2. 시퀀스 리스트 (드래그 앤 드롭 순서 변경)
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("background-color: #F0F0F0; font-weight: bold; font-size: 10pt;")
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDropIndicatorShown(True)
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.model().rowsMoved.connect(self.sync_sequence_after_drag)
        
        layout.addWidget(self.list_widget)

        # 3. 하단 버튼부
        bottom_box = QHBoxLayout()
        self.del_btn = QPushButton("Delete")
        self.del_btn.setFixedSize(70, 28)
        self.del_btn.clicked.connect(self.delete_step)
        
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setFixedSize(70, 28)
        self.clear_btn.clicked.connect(self.clear_all)
        
        self.exec_btn = QPushButton("Execute ▶")
        self.exec_btn.setFixedHeight(35)
        self.exec_btn.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; font-size: 11pt;")
        self.exec_btn.clicked.connect(self.toggle_execution)

        bottom_box.addWidget(self.del_btn)
        bottom_box.addWidget(self.clear_btn)
        bottom_box.addStretch(1)
        bottom_box.addWidget(self.exec_btn, 2)

        layout.addLayout(bottom_box)
        main_layout.addWidget(group)
        self.on_dev_changed()

    def on_dev_changed(self):
        dev = self.dev_combo.currentText()
        self.cmd_combo.clear()
        if dev == "LS331":
            # "Wait for Temp" 삭제 (Set Temp에 통합됨)
            self.cmd_combo.addItems(["Set Temp", "Heater", "Apply Ramp", "Ramp Off", "Wait Time"])
        elif dev == "K2400":
            self.cmd_combo.addItems(["Set Voltage", "Output On", "Output Off"])
        elif dev == "ZUP36-12":
            self.cmd_combo.addItems(["Set Volt", "Set Amp", "Set OVP", "Set UVP", "Output On", "Output Off"])

    def on_cmd_changed(self):
        cmd = self.cmd_combo.currentText()
        dev = self.dev_combo.currentText()
        
        no_val_cmds = ["Output On", "Output Off", "Ramp Off"]
        needs_input = cmd not in no_val_cmds
        self.val_stack.setVisible(needs_input)
        self.unit_label.setVisible(needs_input)

        if cmd == "Heater":
            self.val_stack.setCurrentIndex(1)
        else:
            self.val_stack.setCurrentIndex(0)
            if dev == "LS331":
                self.val_spin.setRange(0, 1000)
                units = {"Set Temp": "K", "Apply Ramp": "K/m", "Wait Time": "min"}
                self.unit_label.setText(units.get(cmd, ""))
            elif dev == "K2400":
                self.val_spin.setRange(-200, 200)
                self.unit_label.setText("V")
            elif dev == "ZUP36-12":
                self.unit_label.setText("A" if "Amp" in cmd else "V")
                self.val_spin.setRange(0, 12.0 if "Amp" in cmd else 36.0)

    def add_to_stack(self):
        dev = self.dev_combo.currentText()
        cmd = self.cmd_combo.currentText()
        
        if cmd in ["Output On", "Output Off", "Ramp Off"]:
            val, disp_val, arrow = 0, "", ""
        elif cmd == "Heater":
            val = self.heater_combo.currentIndex()
            disp_val = self.heater_combo.currentText()
            arrow = " -> "
        else:
            val = self.val_spin.value()
            disp_val = f"{val} {self.unit_label.text()}".strip()
            arrow = " -> "

        step_text = f"{self.list_widget.count() + 1}. [{dev}] {cmd}{arrow}{disp_val}"
        step_data = {'dev': dev, 'cmd': cmd, 'val': val}
        
        item = QListWidgetItem(step_text)
        item.setData(Qt.ItemDataRole.UserRole, step_data)
        self.list_widget.addItem(item)

    def sync_sequence_after_drag(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            old_text = item.text()
            if ". " in old_text:
                desc = old_text.split(". ", 1)[1]
                item.setText(f"{i+1}. {desc}")

    def delete_step(self):
        row = self.list_widget.currentRow()
        if row >= 0 and not self.is_running:
            self.list_widget.takeItem(row)
            self.sync_sequence_after_drag()

    def clear_all(self):
        if not self.is_running: self.list_widget.clear()

    def toggle_execution(self):
        if self.list_widget.count() == 0: return
        if not self.is_running:
            ls = self.manager.get_device("LS331")
            zup = self.manager.get_device("ZUP")
            if ls: ls.write("MODE 1"); time.sleep(0.3); ls.write("RAMP 1,0,1.0")
            if zup: zup.write(":RMT1;")
            
            self.is_running = True
            self.current_step_idx = 0
            self.state = "NEXT"
            self.ramp_active_flag = False
            self.exec_btn.setText("Stop ⏹")
            self.exec_btn.setStyleSheet("background-color: #E74C3C; color: white; font-weight: bold; font-size: 11pt;")
            self.engine_timer.start()
        else:
            self.finish_seq("Aborted.")

    def finish_seq(self, msg):
        self.is_running = False
        self.engine_timer.stop()
        self.exec_btn.setText("Execute ▶")
        self.exec_btn.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; font-size: 11pt;")
        self.log(f">>> {msg}")

    def run_engine(self):
        if not self.is_running: return
        if self.state == "NEXT":
            if self.current_step_idx >= self.list_widget.count():
                self.finish_seq("Sequence Complete.")
                return

            item = self.list_widget.item(self.current_step_idx)
            self.list_widget.setCurrentRow(self.current_step_idx)
            step = item.data(Qt.ItemDataRole.UserRole)
            
            dev_name = "ZUP" if step['dev'] == "ZUP36-12" else step['dev']
            dev = self.manager.get_device(dev_name)
            if not dev: self.finish_seq(f"Error: {step['dev']} disconnected."); return
            
            cmd, val = step['cmd'], step['val']
            self.log(f"Step {self.current_step_idx+1}: {cmd}")

            if step['dev'] == "LS331":
                if cmd == "Heater": dev.set_heater_range(int(val)); time.sleep(0.3); self.go_next()
                elif cmd == "Apply Ramp": 
                    dev.set_ramp(True, val, loop=1)
                    self.ramp_active_flag = True # 램프 활성화 상태 기억
                    time.sleep(0.3); self.go_next()
                elif cmd == "Ramp Off": 
                    dev.set_ramp(False, 1.0, loop=1)
                    self.ramp_active_flag = False # 램프 비활성화 상태 기억
                    time.sleep(0.3); self.go_next()
                elif cmd == "Set Temp":
                    dev.set_setpoint(val, loop=1)
                    self.target_temp = val
                    # [핵심] 램프가 켜져 있으면 도착할 때까지 대기 상태로 전환
                    if self.ramp_active_flag:
                        self.state = "WAIT_FOR_TEMP"
                        self.log(f"Ramping to {val}K... Please wait.")
                    else:
                        time.sleep(0.3); self.go_next()
                elif cmd == "Wait Time":
                    self.wait_until = time.time() + (val * 60); self.state = "WAIT_FOR_TIME"
            
            elif step['dev'] == "ZUP36-12":
                if cmd == "Set Volt": dev.set_voltage(val)
                elif cmd == "Set Amp": dev.set_current(val)
                elif cmd == "Set OVP": dev.set_ovp(val)
                elif cmd == "Set UVP": dev.set_uvp(val)
                elif cmd == "Output On": dev.output_on()
                elif cmd == "Output Off": dev.output_off()
                time.sleep(0.3); self.go_next()

            elif step['dev'] == "K2400":
                if cmd == "Set Voltage": dev.set_voltage_source(val)
                elif cmd == "Output On": dev.output_on()
                elif cmd == "Output Off": dev.output_off()
                time.sleep(0.3); self.go_next()

        elif self.state == "WAIT_FOR_TEMP":
            try:
                ls = self.manager.get_device("LS331")
                # 장비가 램프 동작을 마쳤거나(RAMPST), 온도 오차가 작으면 통과
                if not ls.is_ramping(loop=1) or (abs(ls.read_temp("A") - self.target_temp) < 2.5):
                    # 도착하면 안전을 위해 램프를 끄고 다음으로 넘어감
                    ls.set_ramp(False, 1.0, loop=1)
                    self.ramp_active_flag = False 
                    self.log(">>> Target reached. Ramp Auto-OFF.")
                    time.sleep(0.5); self.go_next()
            except: pass
            
        elif self.state == "WAIT_FOR_TIME":
            if time.time() >= self.wait_until: self.go_next()

    def go_next(self):
        self.current_step_idx += 1
        self.state = "NEXT"
