from PyQt6.QtWidgets import (QWidget, QGroupBox, QGridLayout, QLabel, 
                             QPushButton, QDoubleSpinBox, QDial, QComboBox, QCheckBox, QMessageBox)

class LakeshorePanel(QWidget):
    def __init__(self, device_manager, log_callback):
        super().__init__()
        self.manager = device_manager
        self.log = log_callback
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        ls_group = QGroupBox("Lakeshore 331 Sequence / Control")
        ls_layout = QGridLayout(ls_group)

        # 1. Setpoint 제어 (Spinbox + Dial)
        self.setpoint_spin = QDoubleSpinBox()
        self.setpoint_spin.setRange(0.0, 1000.0)
        self.setpoint_spin.setValue(301.05)
        self.setpoint_spin.setDecimals(2)
        
        self.setpoint_dial = QDial()
        self.setpoint_dial.setRange(0, 1000)
        self.setpoint_dial.setValue(301)
        self.setpoint_dial.setFixedSize(60, 60)
        self.setpoint_dial.setNotchesVisible(True)
        
        self.setpoint_dial.valueChanged.connect(lambda v: self.setpoint_spin.setValue(float(v)))
        self.setpoint_spin.valueChanged.connect(lambda v: self.setpoint_dial.setValue(int(v)))

        self.setpoint_btn = QPushButton("Set LS331 Setpoint")
        self.heater_off_btn = QPushButton("LS331 Heater Off")
        
        self.setpoint_btn.clicked.connect(self.set_ls331_setpoint)
        self.heater_off_btn.clicked.connect(self.ls331_heater_off)

        ls_layout.addWidget(QLabel("Setpoint [K]:"), 0, 0)
        ls_layout.addWidget(self.setpoint_spin, 0, 1)
        ls_layout.addWidget(self.setpoint_dial, 0, 2, 2, 1)
        ls_layout.addWidget(self.setpoint_btn, 1, 0, 1, 2)
        ls_layout.addWidget(self.heater_off_btn, 2, 0, 1, 3)

        # 2. Heater Range 제어
        self.ls_range_combo = QComboBox()
        self.ls_range_combo.addItems(["Off", "Low (0.5W)", "Medium (5W)", "High (50W)"])
        self.ls_range_btn = QPushButton("Apply Heater Range")
        self.ls_range_btn.clicked.connect(self.set_ls331_heater_range)
        
        ls_layout.addWidget(QLabel("Heater Range:"), 3, 0)
        ls_layout.addWidget(self.ls_range_combo, 3, 1)
        ls_layout.addWidget(self.ls_range_btn, 3, 2)

        # 3. Ramp 제어
        self.ramp_enable_check = QCheckBox("Enable Ramp")
        self.ramp_rate_spin = QDoubleSpinBox()
        self.ramp_rate_spin.setValue(1.0)
        self.ramp_apply_btn = QPushButton("Apply Ramp")
        self.ramp_apply_btn.clicked.connect(self.set_ls331_ramp)
        
        ls_layout.addWidget(self.ramp_enable_check, 4, 0)
        ls_layout.addWidget(QLabel("Rate[K/min]:"), 4, 1)
        ls_layout.addWidget(self.ramp_rate_spin, 4, 2)
        ls_layout.addWidget(self.ramp_apply_btn, 5, 0, 1, 3)

        layout.addWidget(ls_group)

    # --- 구동 함수들 ---
    def set_ls331_setpoint(self):
        try:
            ls = self.manager.get_device("LS331")
            if ls is None: 
                self.log("LS331 is not connected.")
                return
            value = self.setpoint_spin.value()
            ls.set_setpoint(value, loop=1)
            self.log(f"LS331 setpoint set to {value} K")
        except Exception as e:
            QMessageBox.critical(self, "Setpoint Error", str(e))

    def ls331_heater_off(self):
        ls = self.manager.get_device("LS331")
        if ls is not None:
            ls.heater_off()
            self.log("LS331 heater off")

    def set_ls331_heater_range(self):
        try:
            ls = self.manager.get_device("LS331")
            if ls is None: return
            range_index = self.ls_range_combo.currentIndex()
            ls.set_heater_range(range_index) 
            self.log(f"LS331 Heater Range: {self.ls_range_combo.currentText()}")
        except Exception as e:
            QMessageBox.critical(self, "Heater Range Error", str(e))

    def set_ls331_ramp(self):
        try:
            ls = self.manager.get_device("LS331")
            if ls is None: return
            is_enabled = self.ramp_enable_check.isChecked()
            rate = self.ramp_rate_spin.value()
            ls.set_ramp(is_enabled, rate, loop=1)
            self.log(f"LS331 Ramp {'Enabled' if is_enabled else 'Disabled'} ({rate} K/min)")
        except Exception as e:
            QMessageBox.critical(self, "Ramp Error", str(e))

from PyQt6.QtWidgets import QVBoxLayout # 추가 인포트