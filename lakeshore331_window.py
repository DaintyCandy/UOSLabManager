import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox,
    QTextEdit, QMessageBox
)
from PyQt6.QtCore import Qt

from lakeshore331 import LakeShore331


class LakeShore331Window(QWidget):
    SENSOR_TYPES = [
        ("Silicon Diode", 0),
        ("GaAlAs Diode", 1),
        ("100 ohm Platinum/250", 2),
        ("100 ohm Platinum/500", 3),
        ("1000 ohm Platinum", 4),
        ("NTC RTD", 5),
        ("Thermocouple 25 mV", 6),
        ("Thermocouple 50 mV", 7),
        ("2.5 V, 1 mA", 8),
        ("7.5 V, 1 mA", 9),
    ]

    CURVE_OPTIONS = [
        ("None", 0),
        ("Type K", 12),
        ("Type E", 13),
        ("Type T", 14),
        ("AuFe 0.03%", 15),
        ("AuFe 0.07%", 16),
    ]

    HEATER_RANGES = [
        ("Off", 0),
        ("Low", 1),
        ("Medium", 2),
        ("High", 3),
    ]

    def __init__(self, manager, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.manager = manager
        self.main_window = parent
        self.setWindowTitle("LakeShore 331 Control")
        self.resize(640, 820)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("LS331 Port"))
        self.port_input = QLineEdit("/dev/cu.usbserial-A9EQ7W68")
        top_bar.addWidget(self.port_input)
        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")
        top_bar.addWidget(self.connect_btn)
        top_bar.addWidget(self.disconnect_btn)
        self.status_label = QLabel("Disconnected")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        top_bar.addWidget(self.status_label)
        layout.addLayout(top_bar)

        self.connect_btn.clicked.connect(self.connect_ls331)
        self.disconnect_btn.clicked.connect(self.disconnect_ls331)

        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(self.refresh_status)
        layout.addWidget(self.refresh_btn)

        readout_grid = QGridLayout()
        readout_grid.setColumnStretch(1, 1)
        readout_grid.setColumnStretch(3, 1)

        readout_grid.addWidget(QLabel("A Temperature [K]"), 0, 0)
        self.temp_a_label = QLabel("-")
        readout_grid.addWidget(self.temp_a_label, 0, 1)

        readout_grid.addWidget(QLabel("B Temperature [K]"), 0, 2)
        self.temp_b_label = QLabel("-")
        readout_grid.addWidget(self.temp_b_label, 0, 3)

        readout_grid.addWidget(QLabel("Setpoint [K]"), 1, 0)
        self.setpoint_label = QLabel("-")
        readout_grid.addWidget(self.setpoint_label, 1, 1)

        readout_grid.addWidget(QLabel("Heater Range"), 1, 2)
        self.heater_range_label = QLabel("-")
        readout_grid.addWidget(self.heater_range_label, 1, 3)

        readout_grid.addWidget(QLabel("Manual Output [%]"), 2, 0)
        self.manual_output_label = QLabel("-")
        readout_grid.addWidget(self.manual_output_label, 2, 1)

        readout_grid.addWidget(QLabel("Ramp Enabled"), 2, 2)
        self.ramp_enabled_label = QLabel("-")
        readout_grid.addWidget(self.ramp_enabled_label, 2, 3)

        readout_grid.addWidget(QLabel("Ramp Rate [K/min]"), 3, 0)
        self.ramp_rate_label = QLabel("-")
        readout_grid.addWidget(self.ramp_rate_label, 3, 1)

        readout_grid.addWidget(QLabel("RAMP Status"), 3, 2)
        self.ramp_state_label = QLabel("-")
        readout_grid.addWidget(self.ramp_state_label, 3, 3)

        readout_grid.addWidget(QLabel("Input Status"), 4, 0)
        self.input_status_label = QLabel("-")
        readout_grid.addWidget(self.input_status_label, 4, 1)

        layout.addLayout(readout_grid)

        layout.addWidget(QLabel("Input / Sensor Configuration"))
        config_grid = QGridLayout()
        config_grid.addWidget(QLabel("Channel"), 0, 0)
        self.channel_combo = QComboBox()
        self.channel_combo.addItems(["A", "B"])
        config_grid.addWidget(self.channel_combo, 0, 1)

        config_grid.addWidget(QLabel("Sensor Type"), 1, 0)
        self.sensor_type_combo = QComboBox()
        for label, data in self.SENSOR_TYPES:
            self.sensor_type_combo.addItem(label, data)
        config_grid.addWidget(self.sensor_type_combo, 1, 1)

        config_grid.addWidget(QLabel("Curve"), 2, 0)
        self.curve_combo = QComboBox()
        for label, data in self.CURVE_OPTIONS:
            self.curve_combo.addItem(label, data)
        config_grid.addWidget(self.curve_combo, 2, 1)

        config_grid.addWidget(QLabel("Compensation"), 3, 0)
        self.comp_check = QCheckBox("Enabled")
        self.comp_check.setChecked(True)
        config_grid.addWidget(self.comp_check, 3, 1)

        layout.addLayout(config_grid)

        config_buttons = QHBoxLayout()
        self.apply_input_btn = QPushButton("Apply Input Settings")
        self.read_input_btn = QPushButton("Read Input Settings")
        self.read_sensor_btn = QPushButton("Read Sensor Value")
        self.set_thermocouple_btn = QPushButton("Configure Thermocouple")
        config_buttons.addWidget(self.apply_input_btn)
        config_buttons.addWidget(self.read_input_btn)
        config_buttons.addWidget(self.read_sensor_btn)
        config_buttons.addWidget(self.set_thermocouple_btn)
        layout.addLayout(config_buttons)

        self.apply_input_btn.clicked.connect(self.apply_input_config)
        self.read_input_btn.clicked.connect(self.read_input_config)
        self.read_sensor_btn.clicked.connect(self.read_sensor_value)
        self.set_thermocouple_btn.clicked.connect(self.set_thermocouple)

        layout.addWidget(QLabel("Setpoint and PID"))
        setpoint_layout = QHBoxLayout()
        setpoint_layout.addWidget(QLabel("Setpoint [K]"))
        self.setpoint_input = QLineEdit("301.0")
        setpoint_layout.addWidget(self.setpoint_input)
        self.set_setpoint_btn = QPushButton("Set Setpoint")
        setpoint_layout.addWidget(self.set_setpoint_btn)
        layout.addLayout(setpoint_layout)
        self.set_setpoint_btn.clicked.connect(self.set_setpoint)

        pid_grid = QGridLayout()
        pid_grid.addWidget(QLabel("P"), 0, 0)
        self.pid_p_input = QLineEdit("1.0")
        pid_grid.addWidget(self.pid_p_input, 0, 1)
        pid_grid.addWidget(QLabel("I"), 0, 2)
        self.pid_i_input = QLineEdit("0.1")
        pid_grid.addWidget(self.pid_i_input, 0, 3)
        pid_grid.addWidget(QLabel("D"), 0, 4)
        self.pid_d_input = QLineEdit("0.0")
        pid_grid.addWidget(self.pid_d_input, 0, 5)

        pid_buttons = QHBoxLayout()
        self.set_pid_btn = QPushButton("Set PID")
        self.get_pid_btn = QPushButton("Read PID")
        pid_buttons.addWidget(self.set_pid_btn)
        pid_buttons.addWidget(self.get_pid_btn)
        layout.addLayout(pid_grid)
        layout.addLayout(pid_buttons)

        self.set_pid_btn.clicked.connect(self.set_pid)
        self.get_pid_btn.clicked.connect(self.get_pid)

        layout.addWidget(QLabel("Manual Output"))
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(QLabel("Output [%]"))
        self.manual_output_input = QLineEdit("0.0")
        manual_layout.addWidget(self.manual_output_input)
        self.set_manual_btn = QPushButton("Set Manual Output")
        manual_layout.addWidget(self.set_manual_btn)
        self.manual_read_btn = QPushButton("Read Manual Output")
        manual_layout.addWidget(self.manual_read_btn)
        layout.addLayout(manual_layout)
        self.set_manual_btn.clicked.connect(self.set_manual_output)
        self.manual_read_btn.clicked.connect(self.read_manual_output)

        layout.addWidget(QLabel("Heater Range"))
        heater_layout = QHBoxLayout()
        self.heater_range_combo = QComboBox()
        for label, data in self.HEATER_RANGES:
            self.heater_range_combo.addItem(label, data)
        heater_layout.addWidget(self.heater_range_combo)
        self.set_heater_btn = QPushButton("Set Heater Range")
        self.heater_off_btn = QPushButton("Heater OFF")
        heater_layout.addWidget(self.set_heater_btn)
        heater_layout.addWidget(self.heater_off_btn)
        layout.addLayout(heater_layout)
        self.set_heater_btn.clicked.connect(self.set_heater_range)
        self.heater_off_btn.clicked.connect(self.heater_off)

        layout.addWidget(QLabel("Ramp Control"))
        ramp_layout = QHBoxLayout()
        self.ramp_enable_check = QCheckBox("Enable")
        ramp_layout.addWidget(self.ramp_enable_check)
        ramp_layout.addWidget(QLabel("Rate [K/min]"))
        self.ramp_rate_input = QLineEdit("0.5")
        ramp_layout.addWidget(self.ramp_rate_input)
        self.set_ramp_btn = QPushButton("Set Ramp")
        self.get_ramp_btn = QPushButton("Read Ramp")
        ramp_layout.addWidget(self.set_ramp_btn)
        ramp_layout.addWidget(self.get_ramp_btn)
        layout.addLayout(ramp_layout)
        self.set_ramp_btn.clicked.connect(self.set_ramp)
        self.get_ramp_btn.clicked.connect(self.get_ramp)

        self.status_buttons_layout = QHBoxLayout()
        self.sensor_status_btn = QPushButton("Read Input Status")
        self.sensor_status_btn.clicked.connect(self.read_input_status)
        self.status_buttons_layout.addWidget(self.sensor_status_btn)
        layout.addLayout(self.status_buttons_layout)

        layout.addWidget(QLabel("Log"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        self.refresh_status()

    def get_device(self):
        return self.manager.get_device("LS331")

    def connect_ls331(self):
        if self.get_device() is not None:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.log("LS331 already connected")
            return

        port = self.port_input.text().strip()
        if not port:
            self.show_error("Port is required to connect.")
            return

        try:
            self.manager.add_device("LS331", LakeShore331(port))
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.log(f"Connected LS331 on {port}")
            self.refresh_status()
            if hasattr(self.main_window, "update_device_status"):
                self.main_window.update_device_status()
        except Exception as exc:
            self.show_error(str(exc))

    def disconnect_ls331(self):
        # [수정] 상태가 어떻든 간에 버튼을 누르면 라벨은 무조건 빨간색으로 변경
        self.status_label.setText("Disconnected")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

        if self.get_device() is None:
            self.log("LS331 is already disconnected")
            return
        
        self.manager.remove_device("LS331")
        self.log("Disconnected LS331")
        self.refresh_status()
        if hasattr(self.main_window, "update_device_status"):
            self.main_window.update_device_status()

    def refresh_status(self):
        dev = self.get_device()
        if dev is None:
            self.temp_a_label.setText("-")
            self.temp_b_label.setText("-")
            self.setpoint_label.setText("-")
            self.heater_range_label.setText("-")
            self.manual_output_label.setText("-")
            self.ramp_enabled_label.setText("-")
            self.ramp_rate_label.setText("-")
            self.ramp_state_label.setText("-")
            self.input_status_label.setText("-")
            return

        self.refresh_label("A temperature", self.temp_a_label, lambda: f"{dev.read_temp('A'):.6g}")
        self.refresh_label("B temperature", self.temp_b_label, lambda: f"{dev.read_temp('B'):.6g}")
        self.refresh_label("setpoint", self.setpoint_label, lambda: f"{dev.get_setpoint():.6g}")
        self.refresh_label("heater range", self.heater_range_label, lambda: str(dev.get_heater_range()))
        self.refresh_label("manual output", self.manual_output_label, lambda: f"{dev.get_manual_output():.6g}")

        try:
            enabled, rate = dev.get_ramp()
            self.ramp_enabled_label.setText("Yes" if enabled else "No")
            self.ramp_rate_label.setText(f"{rate:.6g}")
        except Exception as exc:
            self.ramp_enabled_label.setText("N/A")
            self.ramp_rate_label.setText("N/A")
            self.log(f"Could not refresh ramp: {exc}")

        self.refresh_label("ramp status", self.ramp_state_label, lambda: "Ramping" if dev.is_ramping() else "Stopped")
        self.refresh_label(
            "input status",
            self.input_status_label,
            lambda: str(dev.input_status(self.channel_combo.currentText())),
        )

    def refresh_label(self, name: str, label: QLabel, reader):
        try:
            label.setText(reader())
        except Exception as exc:
            label.setText("N/A")
            self.log(f"Could not refresh {name}: {exc}")

    def apply_input_config(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        channel = self.channel_combo.currentText()
        sensor_type = self.sensor_type_combo.currentData()
        curve = self.curve_combo.currentData()
        compensation = self.comp_check.isChecked()

        try:
            dev.set_input_type(channel, sensor_type, compensation)
            dev.set_input_curve(channel, curve)
            self.log(f"Applied input config on {channel}: type={sensor_type}, curve={curve}, comp={'ON' if compensation else 'OFF'}")
            import time
            time.sleep(1.0)
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def read_input_config(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            channel = self.channel_combo.currentText()
            sensor_type, compensation = dev.get_input_type(channel)
            curve = dev.get_input_curve(channel)
            self.set_combo_by_value(self.sensor_type_combo, sensor_type)
            self.set_combo_by_value(self.curve_combo, curve)
            self.comp_check.setChecked(compensation)
            self.log(f"Read input config on {channel}: type={sensor_type}, curve={curve}, comp={'ON' if compensation else 'OFF'}")
        except Exception as exc:
            self.show_error(str(exc))

    def set_thermocouple(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        channel = self.channel_combo.currentText()
        curve = self.curve_combo.currentData()
        compensation = self.comp_check.isChecked()

        try:
            voltage = 25 if curve in (12, 13, 14, 15, 16) and self.curve_combo.currentText().startswith("Type") else 25
            # Keep existing curve selection in the UI for thermocouple options.
            dev.set_thermocouple(channel=channel, voltage_range_mv=25, curve=curve, room_compensation=compensation)
            self.log(f"Configured thermocouple on {channel}: curve={curve}, compensation={'ON' if compensation else 'OFF'}")
            import time
            time.sleep(1.0)
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def set_setpoint(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            value_text = self.setpoint_input.text().strip()
            if not value_text:
                self.show_error("Setpoint is required.")
                return
            value = float(value_text)
            dev.set_setpoint(value)
            self.log(f"Set setpoint to {value} K")
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def get_pid(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            p, i, d = dev.get_pid()
            self.pid_p_input.setText(str(p))
            self.pid_i_input.setText(str(i))
            self.pid_d_input.setText(str(d))
            self.log(f"Read PID: P={p}, I={i}, D={d}")
        except Exception as exc:
            self.show_error(str(exc))

    def set_pid(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            if not all(
                text.strip()
                for text in [
                    self.pid_p_input.text(),
                    self.pid_i_input.text(),
                    self.pid_d_input.text(),
                ]
            ):
                self.show_error("PID P, I, and D values are required.")
                return
            p = float(self.pid_p_input.text())
            i = float(self.pid_i_input.text())
            d = float(self.pid_d_input.text())
            dev.set_pid(p, i, d)
            self.log(f"Set PID: P={p}, I={i}, D={d}")
        except Exception as exc:
            self.show_error(str(exc))

    def read_sensor_value(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            channel = self.channel_combo.currentText()
            value = dev.read_sensor(channel)
            self.log(f"Sensor reading {channel}: {value:.6g}")
        except Exception as exc:
            self.show_error(str(exc))

    def read_input_status(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            channel = self.channel_combo.currentText()
            status = dev.input_status(channel)
            self.input_status_label.setText(str(status))
            self.log(f"Input status {channel}: {status}")
        except Exception as exc:
            self.show_error(str(exc))

    def read_manual_output(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            value = dev.get_manual_output()
            self.manual_output_input.setText(str(value))
            self.log(f"Manual output: {value:.6g}")
        except Exception as exc:
            self.show_error(str(exc))

    def set_manual_output(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            value_text = self.manual_output_input.text().strip()
            if not value_text:
                self.show_error("Manual output is required.")
                return
            value = float(value_text)
            dev.set_manual_output(value)
            self.log(f"Set manual output to {value}%")
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def set_heater_range(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            value = self.heater_range_combo.currentData()
            dev.set_heater_range(value)
            self.log(f"Set heater range to {value}")
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def heater_off(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            dev.heater_off()
            self.log("Heater turned off")
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def get_ramp(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            enabled, rate = dev.get_ramp()
            self.ramp_enable_check.setChecked(enabled)
            self.ramp_rate_input.setText(str(rate))
            self.log(f"Read ramp: enabled={enabled}, rate={rate}")
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def set_ramp(self):
        dev = self.get_device()
        if dev is None:
            self.show_error("Connect LS331 first.")
            return

        try:
            enabled = self.ramp_enable_check.isChecked()
            rate_text = self.ramp_rate_input.text().strip()
            if not rate_text:
                self.show_error("Ramp rate is required.")
                return
            rate = float(rate_text)
            dev.set_ramp(enabled, rate)
            self.log(f"Set ramp: enabled={enabled}, rate={rate}")
            self.refresh_status()
        except Exception as exc:
            self.show_error(str(exc))

    def set_combo_by_value(self, combo: QComboBox, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def show_error(self, message: str):
        QMessageBox.critical(self, "LS331 Error", message)
        self.log(message)

    def log(self, message: str):
        self.log_box.append(message)
        
    def sync_connection_status(self):
        if self.get_device() is not None:
            # 매니저에 장비가 존재하면 강제로 초록색 'Connected'로 변경
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            self.refresh_status() # 화면의 온도/설정값도 최신으로 불러옴
        else:
            # 없으면 빨간색 'Disconnected'로 변경
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.refresh_status() # 값들을 '-' 로 초기화
