import json
from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .driver import LakeShore331


class LakeShore331Window(QWidget):
    SENSOR_TYPES = (
        ("Silicon Diode", 0), ("GaAlAs Diode", 1), ("PT-100 / 250", 2),
        ("PT-100 / 500", 3), ("PT-1000", 4), ("NTC RTD", 5),
        ("Thermocouple 25 mV", 6), ("Thermocouple 50 mV", 7),
        ("2.5 V / 1 mA", 8), ("7.5 V / 1 mA", 9),
    )
    HEATER_RANGES = (("Off", 0), ("Low", 1), ("Medium", 2), ("High", 3))

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.main_window = parent
        self.snapshot = None
        self.input_controls = {}
        self.loop_controls = {}
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self._build_summary(), 3)
        top.addWidget(self._build_log(), 2)
        root.addLayout(top)

        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(self._build_input_tab("A"), "Input A")
        self.settings_tabs.addTab(self._build_input_tab("B"), "Input B")
        self.settings_tabs.addTab(self._build_loop_tab(1), "Loop 1")
        self.settings_tabs.addTab(self._build_loop_tab(2), "Loop 2")
        self.settings_tabs.addTab(self._build_ramp_tab(), "Ramp")
        self.settings_tabs.addTab(self._build_safety_tab(), "Safety")
        root.addWidget(self.settings_tabs)

        buttons = QHBoxLayout()
        for text, callback in (
            ("Read Device", self.read_device), ("Revert", self.revert),
            ("Save Profile", self.save_profile), ("Apply", self.apply_settings),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        root.addLayout(buttons)
        self.sync_connection_status()

    def _build_summary(self):
        group = QGroupBox("Lake Shore 331S")
        layout = QGridLayout(group)
        self.port_input = QLineEdit("COM3")
        self.baud_label = QLabel("9600")
        self.status_label = QLabel("● Disconnected")
        self.status_label.setStyleSheet("color:#e74c3c; font-weight:bold;")
        connect = QPushButton("Connect")
        disconnect = QPushButton("Disconnect")
        connect.clicked.connect(self.connect_device)
        disconnect.clicked.connect(self.disconnect_device)
        layout.addWidget(QLabel("Port"), 0, 0)
        layout.addWidget(self.port_input, 0, 1)
        layout.addWidget(QLabel("Baud"), 0, 2)
        layout.addWidget(self.baud_label, 0, 3)
        layout.addWidget(self.status_label, 0, 4)
        layout.addWidget(connect, 0, 5)
        layout.addWidget(disconnect, 0, 6)
        self.summary_labels = {}
        for row, (key, title) in enumerate((
            ("input_a", "Input A"), ("input_b", "Input B"),
            ("loop_1", "Loop 1"), ("ramp", "Ramp"), ("safety", "Safety"),
        ), start=1):
            layout.addWidget(QLabel(title), row, 0)
            label = QLabel("-")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label, row, 1, 1, 6)
            self.summary_labels[key] = label
        return group

    def _build_log(self):
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(180)
        self.log_box.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        layout.addWidget(self.log_box)
        return group

    def _build_input_tab(self, channel):
        panel = QWidget()
        form = QFormLayout(panel)
        sensor = QComboBox()
        for name, value in self.SENSOR_TYPES:
            sensor.addItem(name, value)
        curve = QSpinBox()
        curve.setRange(0, 99)
        compensation = QCheckBox("Enabled")
        temperature = QLabel("-")
        sensor_reading = QLabel("-")
        form.addRow("Sensor type", sensor)
        form.addRow("Curve number", curve)
        form.addRow("Compensation", compensation)
        form.addRow("Temperature", temperature)
        form.addRow("Sensor reading", sensor_reading)
        self.input_controls[channel] = {
            "sensor": sensor, "curve": curve, "compensation": compensation,
            "temperature": temperature, "reading": sensor_reading,
        }
        return panel

    def _spin(self, minimum, maximum, value, decimals=3):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        return control

    def _build_loop_tab(self, loop):
        panel = QWidget()
        form = QFormLayout(panel)
        controls = {
            "setpoint": self._spin(0, 1000, 300), "p": self._spin(0, 1000, 10),
            "i": self._spin(0, 1000, 20), "d": self._spin(0, 1000, 0),
            "manual": self._spin(0, 100, 0), "range": QComboBox(),
        }
        for name, value in self.HEATER_RANGES:
            controls["range"].addItem(name, value)
        form.addRow("Setpoint [K]", controls["setpoint"])
        form.addRow("PID P", controls["p"])
        form.addRow("PID I", controls["i"])
        form.addRow("PID D", controls["d"])
        form.addRow("Manual output [%]", controls["manual"])
        form.addRow("Heater range", controls["range"])
        self.loop_controls[loop] = controls
        return panel

    def _build_ramp_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.ramp_loop = QComboBox()
        self.ramp_loop.addItems(("1", "2"))
        self.ramp_enabled = QCheckBox("Enabled")
        self.ramp_rate = self._spin(0.001, 100, 1.0)
        form.addRow("Control loop", self.ramp_loop)
        form.addRow("Ramp", self.ramp_enabled)
        form.addRow("Rate [K/min]", self.ramp_rate)
        return panel

    def _build_safety_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.max_temperature = self._spin(0, 1000, 400)
        self.max_manual_output = self._spin(0, 100, 80)
        self.heater_off_disconnect = QCheckBox("Force heater off when disconnecting")
        self.heater_off_disconnect.setChecked(True)
        form.addRow("Maximum temperature [K]", self.max_temperature)
        form.addRow("Maximum manual output [%]", self.max_manual_output)
        form.addRow("Disconnect safety", self.heater_off_disconnect)
        return panel

    def get_device(self):
        return self.manager.get_device("LS331")

    def connect_device(self):
        if self.get_device() is not None:
            return
        try:
            self.manager.add_device("LS331", LakeShore331(self.port_input.text().strip()))
            self.log("Connected")
            self._notify_main()
            self.read_device()
        except Exception as error:
            self.show_error(error)

    def disconnect_device(self):
        device = self.get_device()
        try:
            if device and self.heater_off_disconnect.isChecked():
                device.heater_off()
        finally:
            self.manager.remove_device("LS331")
        self.log("Disconnected")
        self._notify_main()

    def read_device(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        try:
            for channel in ("A", "B"):
                controls = self.input_controls[channel]
                sensor_type, compensation = device.get_input_type(channel)
                controls["sensor"].setCurrentIndex(max(0, controls["sensor"].findData(sensor_type)))
                controls["curve"].setValue(device.get_input_curve(channel))
                controls["compensation"].setChecked(compensation)
                controls["temperature"].setText(f"{device.read_temp(channel):.3f} K")
                controls["reading"].setText(f"{device.read_sensor(channel):.3f} Ω")
            for loop, controls in self.loop_controls.items():
                controls["setpoint"].setValue(device.get_setpoint(loop))
                p, i, d = device.get_pid(loop)
                controls["p"].setValue(p); controls["i"].setValue(i); controls["d"].setValue(d)
                controls["manual"].setValue(device.get_manual_output(loop))
            heater_range = device.get_heater_range()
            for controls in self.loop_controls.values():
                controls["range"].setCurrentIndex(max(0, controls["range"].findData(heater_range)))
            enabled, rate = device.get_ramp(int(self.ramp_loop.currentText()))
            self.ramp_enabled.setChecked(enabled)
            self.ramp_rate.setValue(rate)
            self.snapshot = deepcopy(self.profile_data())
            self.update_summary()
            self.log("Device settings read")
        except Exception as error:
            self.show_error(error)

    def apply_settings(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        try:
            temperatures = [device.read_temp(channel) for channel in ("A", "B")]
            if max(temperatures) > self.max_temperature.value():
                device.heater_off()
                raise ValueError("Safety temperature exceeded; heater forced OFF.")
            for channel, controls in self.input_controls.items():
                device.set_input_type(channel, controls["sensor"].currentData(), controls["compensation"].isChecked())
                device.set_input_curve(channel, controls["curve"].value())
            for loop, controls in self.loop_controls.items():
                manual = min(controls["manual"].value(), self.max_manual_output.value())
                device.set_setpoint(controls["setpoint"].value(), loop)
                device.set_pid(controls["p"].value(), controls["i"].value(), controls["d"].value(), loop)
                device.set_manual_output(manual, loop)
            device.set_heater_range(self.loop_controls[1]["range"].currentData())
            device.set_ramp(self.ramp_enabled.isChecked(), self.ramp_rate.value(), int(self.ramp_loop.currentText()))
            self.snapshot = deepcopy(self.profile_data())
            self.update_summary()
            self.log("Settings applied")
        except Exception as error:
            self.show_error(error)

    def profile_data(self):
        return {
            "port": self.port_input.text(),
            "inputs": {channel: {"sensor": c["sensor"].currentData(), "curve": c["curve"].value(), "compensation": c["compensation"].isChecked()} for channel, c in self.input_controls.items()},
            "loops": {str(loop): {"setpoint": c["setpoint"].value(), "p": c["p"].value(), "i": c["i"].value(), "d": c["d"].value(), "manual": c["manual"].value(), "range": c["range"].currentData()} for loop, c in self.loop_controls.items()},
            "ramp": {"loop": int(self.ramp_loop.currentText()), "enabled": self.ramp_enabled.isChecked(), "rate": self.ramp_rate.value()},
            "safety": {"max_temperature": self.max_temperature.value(), "max_manual_output": self.max_manual_output.value(), "heater_off_disconnect": self.heater_off_disconnect.isChecked()},
        }

    def load_profile_data(self, data):
        self.port_input.setText(data.get("port", self.port_input.text()))
        for channel, values in data.get("inputs", {}).items():
            controls = self.input_controls[channel]
            controls["sensor"].setCurrentIndex(max(0, controls["sensor"].findData(values["sensor"])))
            controls["curve"].setValue(values["curve"])
            controls["compensation"].setChecked(values["compensation"])
        for loop_text, values in data.get("loops", {}).items():
            controls = self.loop_controls[int(loop_text)]
            for key in ("setpoint", "p", "i", "d", "manual"):
                controls[key].setValue(values[key])
            controls["range"].setCurrentIndex(max(0, controls["range"].findData(values["range"])))
        ramp = data.get("ramp", {})
        self.ramp_loop.setCurrentText(str(ramp.get("loop", 1)))
        self.ramp_enabled.setChecked(ramp.get("enabled", False))
        self.ramp_rate.setValue(ramp.get("rate", 1.0))
        safety = data.get("safety", {})
        self.max_temperature.setValue(safety.get("max_temperature", 400))
        self.max_manual_output.setValue(safety.get("max_manual_output", 80))
        self.heater_off_disconnect.setChecked(safety.get("heater_off_disconnect", True))
        self.update_summary()

    def revert(self):
        if self.snapshot is None:
            self.log("Nothing to revert")
            return
        self.load_profile_data(deepcopy(self.snapshot))
        self.log("Reverted to last read/applied settings")

    def save_profile(self):
        default = Path.cwd() / "config" / "lakeshore331_profile.json"
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save LS331 Profile", str(default), "JSON Files (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.profile_data(), indent=2), encoding="utf-8")
            self.log(f"Profile saved: {path}")

    def update_summary(self):
        for channel, key in (("A", "input_a"), ("B", "input_b")):
            controls = self.input_controls[channel]
            self.summary_labels[key].setText(
                f"Sensor: {controls['sensor'].currentText()}  |  Curve: {controls['curve'].value()}  |  Reading: {controls['temperature'].text()} / {controls['reading'].text()}"
            )
        loop = self.loop_controls[1]
        self.summary_labels["loop_1"].setText(f"Setpoint: {loop['setpoint'].value():.3f} K  |  PID: {loop['p'].value():g}, {loop['i'].value():g}, {loop['d'].value():g}")
        self.summary_labels["ramp"].setText(f"Loop {self.ramp_loop.currentText()}  |  {'Enabled' if self.ramp_enabled.isChecked() else 'Disabled'}  |  {self.ramp_rate.value():g} K/min")
        self.summary_labels["safety"].setText(f"Max temperature: {self.max_temperature.value():g} K  |  Max output: {self.max_manual_output.value():g} %")

    def sync_connection_status(self):
        connected = self.get_device() is not None
        self.status_label.setText("● Connected" if connected else "● Disconnected")
        self.status_label.setStyleSheet(f"color:{'#2ecc71' if connected else '#e74c3c'}; font-weight:bold;")

    def _notify_main(self):
        self.sync_connection_status()
        if self.main_window:
            self.main_window.update_device_status()

    def show_error(self, error):
        message = str(error)
        QMessageBox.critical(self, "LS331 Error", message)
        self.log(message)

    def log(self, message):
        self.log_box.append(str(message))
        if self.main_window:
            self.main_window.log(f"LS331: {message}")
