import json
import math
from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .driver import Keithley2400


class Keithley2400Panel(QWidget):
    def __init__(self, manager, plugin, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.plugin = plugin
        self.main_window = parent
        self.snapshot = None
        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(1000)
        self.monitor_timer.timeout.connect(self.refresh_monitoring)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self._build_monitor(), 3)
        top.addWidget(self._build_log(), 2)
        root.addLayout(top)
        tabs = QTabWidget()
        tabs.addTab(self._build_source_tab(), "Source Settings")
        tabs.addTab(self._build_measurement_tab(), "Measurement Settings")
        tabs.addTab(self._build_protection_tab(), "Protection")
        tabs.addTab(self._build_safety_tab(), "Safety")
        root.addWidget(tabs)
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

    def _build_monitor(self):
        group = QGroupBox("Keithley 2400")
        layout = QGridLayout(group)
        self.address_input = QLineEdit("GPIB0::24::INSTR")
        self.status_label = QLabel("● Disconnected")
        connect = QPushButton("Connect")
        disconnect = QPushButton("Disconnect")
        connect.clicked.connect(self.connect_device)
        disconnect.clicked.connect(self.disconnect_device)
        layout.addWidget(QLabel("Resource"), 0, 0)
        layout.addWidget(self.address_input, 0, 1, 1, 2)
        layout.addWidget(self.status_label, 0, 3)
        layout.addWidget(connect, 0, 4)
        layout.addWidget(disconnect, 0, 5)
        self.response_label = QLabel("Response: -")
        layout.addWidget(self.response_label, 1, 0, 1, 2)
        self.monitor_labels = {}
        for row, (key, title) in enumerate((
            ("voltage", "Actual Voltage"), ("current", "Actual Current"),
            ("power", "Calculated Power P=VI"), ("resistance", "Calculated Resistance V/I"),
            ("source", "Source Mode"), ("output", "Output Status"),
            ("compliance", "Compliance / OVP"), ("communication", "Communication Error"),
        ), start=2):
            layout.addWidget(QLabel(title), row, 0, 1, 2)
            label = QLabel("-")
            layout.addWidget(label, row, 2, 1, 4)
            self.monitor_labels[key] = label
        return group

    def _build_log(self):
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(190)
        self.log_box.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        layout.addWidget(self.log_box)
        return group

    @staticmethod
    def _spin(minimum, maximum, value, decimals=6):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        return control

    def _build_source_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.source_mode = QComboBox()
        self.source_mode.addItem("Voltage", "VOLT")
        self.source_mode.addItem("Current", "CURR")
        self.source_level = self._spin(-210, 210, 0)
        self.output_enabled = QCheckBox("Output ON")
        self.source_mode.currentIndexChanged.connect(self.update_source_limits)
        form.addRow("Source mode", self.source_mode)
        form.addRow("Source level [V/A]", self.source_level)
        form.addRow("Output", self.output_enabled)
        return panel

    def _build_measurement_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.nplc = self._spin(0.01, 10, 1, 2)
        self.remote_sense = QCheckBox("4-wire remote sense")
        self.auto_range = QCheckBox("Measurement auto range")
        self.auto_range.setChecked(True)
        form.addRow("Integration time [NPLC]", self.nplc)
        form.addRow("Sense mode", self.remote_sense)
        form.addRow("Range", self.auto_range)
        return panel

    def _build_protection_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.compliance_limit = self._spin(0, 210, 0.01)
        self.high_impedance_off = QCheckBox("High-impedance output-off mode")
        self.high_impedance_off.setChecked(True)
        clear_errors = QPushButton("Clear status / error queue")
        clear_errors.clicked.connect(self.clear_errors)
        form.addRow("Compliance limit [A/V]", self.compliance_limit)
        form.addRow("Output OFF state", self.high_impedance_off)
        form.addRow("Status", clear_errors)
        return panel

    def _build_safety_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.max_voltage = self._spin(0, 210, 20)
        self.max_current = self._spin(0, 1.05, 0.1)
        self.max_power = self._spin(0, 220, 2)
        self.output_off_disconnect = QCheckBox("Turn output off on disconnect")
        self.output_off_disconnect.setChecked(True)
        self.block_on_compliance = QCheckBox("Disable output when compliance occurs")
        form.addRow("Maximum Voltage [V]", self.max_voltage)
        form.addRow("Maximum Current [A]", self.max_current)
        form.addRow("Maximum Power [W]", self.max_power)
        form.addRow("Disconnect Safety", self.output_off_disconnect)
        form.addRow("Compliance interlock", self.block_on_compliance)
        return panel

    def update_source_limits(self, _index=None):
        if self.source_mode.currentData() == "VOLT":
            self.source_level.setRange(-210, 210)
            self.compliance_limit.setRange(0, 1.05)
        else:
            self.source_level.setRange(-1.05, 1.05)
            self.compliance_limit.setRange(0, 210)

    def get_device(self):
        return self.manager.get_device("K2400")

    def connect_device(self):
        if self.get_device() is not None:
            return
        try:
            address = self.address_input.text().strip()
            self.manager.add_device("K2400", lambda: Keithley2400(address))
            self.log("Connected")
            self.monitor_timer.start()
            self._notify_main()
            self.read_device()
        except Exception as error:
            self.show_error(error)

    def disconnect_device(self):
        device = self.get_device()
        if device and self.output_off_disconnect.isChecked():
            device.output_off()
        self.manager.remove_device("K2400")
        self.monitor_timer.stop()
        self.log("Disconnected")
        self._notify_main()

    def refresh_monitoring(self):
        device = self.get_device()
        if device is None:
            self.monitor_timer.stop()
            self.sync_connection_status()
            return
        try:
            state = self.manager.get_latest("K2400")
            if not state:
                self.update_realtime_status()
                return
            self.monitor_labels["voltage"].setText(f"{state['voltage_V']:.6g} V")
            self.monitor_labels["current"].setText(f"{state['current_A']:.6g} A")
            self.monitor_labels["power"].setText(f"{state['power_W']:.6g} W")
            resistance = state["resistance_Ohm"]
            if not math.isfinite(resistance) and state["current_A"] != 0:
                resistance = state["voltage_V"] / state["current_A"]
            self.monitor_labels["resistance"].setText(f"{resistance:.6g} Ω")
            self.monitor_labels["source"].setText(state["source_mode"])
            self.monitor_labels["output"].setText("ON" if state["output_on"] else "OFF")
            flags = [name for name, active in (("Compliance", state["compliance"]), ("OVP", state["ovp"])) if active]
            self.monitor_labels["compliance"].setText(", ".join(flags) if flags else "OK")
            self.monitor_labels["communication"].setText(state["error"] or "OK")
            if state["compliance"] and self.block_on_compliance.isChecked() and state["output_on"]:
                device.output_off()
                self.log("Safety interlock: output disabled by compliance")
            self.update_realtime_status()
        except Exception as error:
            self.monitor_labels["communication"].setText(str(error))
            self.monitor_timer.stop()
            self.manager.remove_device("K2400")
            self.sync_connection_status()
            self.log(f"Connection lost; changed to Disconnected: {error}")
            if self.main_window:
                self.main_window.update_device_status()

    def read_device(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        try:
            values = self.get_device().read_settings()
            self.source_mode.setCurrentIndex(max(0, self.source_mode.findData(values["source_mode"])))
            self.update_source_limits()
            self.source_level.setValue(values["source_level"])
            self.compliance_limit.setValue(values["compliance"])
            self.output_enabled.setChecked(values["output"])
            self.nplc.setValue(values["nplc"])
            self.remote_sense.setChecked(values["remote_sense"])
            self.snapshot = deepcopy(self.profile_data())
            self.refresh_monitoring()
            self.log("Device settings read")
        except Exception as error:
            self.show_error(error)

    def apply_settings(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        mode = self.source_mode.currentData()
        level = self.source_level.value()
        compliance = self.compliance_limit.value()
        source_voltage = abs(level) if mode == "VOLT" else compliance
        source_current = compliance if mode == "VOLT" else abs(level)
        if source_voltage > self.max_voltage.value() or source_current > self.max_current.value() or source_voltage * source_current > self.max_power.value():
            self.show_error("Source setting exceeds the Safety limits.")
            return
        try:
            device.output_off()
            if self.high_impedance_off.isChecked():
                device.write(":OUTP:SMOD HIMP")
            if mode == "VOLT":
                device.set_voltage_source(level, compliance)
            else:
                device.set_current_source(level, compliance)
            device.set_nplc(self.nplc.value())
            device.set_remote_sense(self.remote_sense.isChecked())
            sense = "CURR" if mode == "VOLT" else "VOLT"
            device.write(f":SENS:{sense}:RANG:AUTO {'ON' if self.auto_range.isChecked() else 'OFF'}")
            if self.output_enabled.isChecked():
                device.output_on()
            self.snapshot = deepcopy(self.profile_data())
            self.refresh_monitoring()
            self.log("Settings applied")
        except Exception as error:
            self.show_error(error)

    def clear_errors(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        self.get_device().write("*CLS")
        self.log("Status and error queue cleared")

    def profile_data(self):
        return {
            "resource": self.address_input.text(),
            "source": {"mode": self.source_mode.currentData(), "level": self.source_level.value(), "output": self.output_enabled.isChecked()},
            "measurement": {"nplc": self.nplc.value(), "remote_sense": self.remote_sense.isChecked(), "auto_range": self.auto_range.isChecked()},
            "protection": {"compliance": self.compliance_limit.value(), "high_impedance_off": self.high_impedance_off.isChecked()},
            "safety": {"max_voltage": self.max_voltage.value(), "max_current": self.max_current.value(), "max_power": self.max_power.value(), "off_disconnect": self.output_off_disconnect.isChecked(), "block_on_compliance": self.block_on_compliance.isChecked()},
        }

    def load_profile_data(self, data):
        self.address_input.setText(data.get("resource", self.address_input.text()))
        source = data.get("source", {})
        self.source_mode.setCurrentIndex(max(0, self.source_mode.findData(source.get("mode", "VOLT")))); self.update_source_limits(); self.source_level.setValue(source.get("level", 0)); self.output_enabled.setChecked(source.get("output", False))
        measurement = data.get("measurement", {})
        self.nplc.setValue(measurement.get("nplc", 1)); self.remote_sense.setChecked(measurement.get("remote_sense", False)); self.auto_range.setChecked(measurement.get("auto_range", True))
        protection = data.get("protection", {})
        self.compliance_limit.setValue(protection.get("compliance", 0.01)); self.high_impedance_off.setChecked(protection.get("high_impedance_off", True))
        safety = data.get("safety", {})
        self.max_voltage.setValue(safety.get("max_voltage", 20)); self.max_current.setValue(safety.get("max_current", 0.1)); self.max_power.setValue(safety.get("max_power", 2)); self.output_off_disconnect.setChecked(safety.get("off_disconnect", True)); self.block_on_compliance.setChecked(safety.get("block_on_compliance", False))

    def revert(self):
        if self.snapshot is None:
            self.log("Nothing to revert")
            return
        self.load_profile_data(deepcopy(self.snapshot))
        self.log("Reverted to last read/applied settings")

    def save_profile(self):
        default = Path.cwd() / "config" / "keithley2400_profile.json"
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save K2400 Profile", str(default), "JSON Files (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.profile_data(), indent=2), encoding="utf-8")
            self.log(f"Profile saved: {path}")

    def sync_connection_status(self):
        connected = self.get_device() is not None
        self.status_label.setText("● Connected" if connected else "● Disconnected")
        self.status_label.setStyleSheet(f"color:{'#2ecc71' if connected else '#e74c3c'}; font-weight:bold;")
        if connected and not self.monitor_timer.isActive():
            self.monitor_timer.start()
        elif not connected:
            self.monitor_timer.stop()
        self.update_realtime_status()

    def update_realtime_status(self):
        metrics = self.manager.get_metrics("K2400")
        response = metrics["response_ms"]
        self.response_label.setText("Response: -" if response is None else f"Response: {response:.1f} ms")

    def _notify_main(self):
        self.sync_connection_status()
        if self.main_window:
            self.main_window.update_device_status()

    def show_error(self, error):
        QMessageBox.critical(self, "K2400 Error", str(error))
        self.log(error)

    def log(self, message):
        self.log_box.append(str(message))
        if self.main_window:
            self.main_window.log(f"K2400: {message}")
