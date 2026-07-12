import json
from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from .driver import ZUP36_12


class ZUP3612Panel(QWidget):
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
        tabs.addTab(self._build_output_tab(), "Output Settings")
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
        group = QGroupBox("ZUP 36-12")
        layout = QGridLayout(group)
        self.port_input = QLineEdit("COM3")
        self.status_label = QLabel("● Disconnected")
        connect = QPushButton("Connect")
        disconnect = QPushButton("Disconnect")
        connect.clicked.connect(self.connect_device)
        disconnect.clicked.connect(self.disconnect_device)
        layout.addWidget(QLabel("Port"), 0, 0)
        layout.addWidget(self.port_input, 0, 1)
        layout.addWidget(QLabel("9600 baud"), 0, 2)
        layout.addWidget(self.status_label, 0, 3)
        layout.addWidget(connect, 0, 4)
        layout.addWidget(disconnect, 0, 5)
        self.monitor_labels = {}
        items = (
            ("voltage", "Actual Voltage"), ("current", "Actual Current"),
            ("power", "Calculated Power P=VI"), ("mode", "CV/CC Mode"),
            ("output", "Output Status"), ("faults", "OVP/OTP/Foldback Fault"),
            ("communication", "Communication Error"),
        )
        for row, (key, title) in enumerate(items, start=1):
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
    def _spin(maximum, value, decimals=3):
        control = QDoubleSpinBox()
        control.setRange(0, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        return control

    def _build_output_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.voltage_setpoint = self._spin(36, 0, 2)
        self.current_limit = self._spin(12, 1, 3)
        self.output_enabled = QCheckBox("Output ON")
        form.addRow("Set Voltage [V]", self.voltage_setpoint)
        form.addRow("Current Limit [A]", self.current_limit)
        form.addRow("Output", self.output_enabled)
        return panel

    def _build_protection_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.ovp_limit = self._spin(39.6, 38, 1)
        self.uvp_limit = self._spin(35.9, 0, 1)
        self.foldback_enabled = QCheckBox("Foldback armed")
        self.auto_restart = QCheckBox("Auto restart")
        clear_faults = QPushButton("Clear fault registers")
        clear_faults.clicked.connect(self.clear_faults)
        form.addRow("OVP [V]", self.ovp_limit)
        form.addRow("UVP [V]", self.uvp_limit)
        form.addRow("Foldback", self.foldback_enabled)
        form.addRow("Recovery Mode", self.auto_restart)
        form.addRow("Fault", clear_faults)
        return panel

    def _build_safety_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.max_voltage = self._spin(36, 36, 2)
        self.max_current = self._spin(12, 12, 3)
        self.max_power = self._spin(432, 432, 1)
        self.output_off_disconnect = QCheckBox("Turn output off on disconnect")
        self.output_off_disconnect.setChecked(True)
        self.block_output_on_fault = QCheckBox("Disable output when a fault occurs")
        self.block_output_on_fault.setChecked(True)
        form.addRow("Maximum Voltage [V]", self.max_voltage)
        form.addRow("Maximum Current [A]", self.max_current)
        form.addRow("Maximum Power [W]", self.max_power)
        form.addRow("Disconnect Safety", self.output_off_disconnect)
        form.addRow("Fault interlock", self.block_output_on_fault)
        return panel

    def get_device(self):
        return self.manager.get_device("ZUP")

    def connect_device(self):
        if self.get_device() is not None:
            return
        try:
            self.manager.add_device("ZUP", ZUP36_12(self.port_input.text().strip()))
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
        self.manager.remove_device("ZUP")
        self.monitor_timer.stop()
        self.log("Disconnected")
        self._notify_main()

    def refresh_monitoring(self):
        device = self.get_device()
        if device is None:
            return
        try:
            state = device.read_monitoring()
            self.monitor_labels["voltage"].setText(f"{state['voltage_V']:.3f} V")
            self.monitor_labels["current"].setText(f"{state['current_A']:.3f} A")
            self.monitor_labels["power"].setText(f"{state['power_W']:.3f} W")
            self.monitor_labels["mode"].setText(state["mode"])
            self.monitor_labels["output"].setText("ON" if state["output_on"] else "OFF")
            faults = [name for name, key in (("OVP", "ovp_fault"), ("OTP", "otp_fault"), ("Foldback", "foldback_fault")) if state[key]]
            self.monitor_labels["faults"].setText(", ".join(faults) if faults else "OK")
            communication = state["programming_error_raw"] if state["communication_error"] else "OK"
            self.monitor_labels["communication"].setText(communication)
            if self.block_output_on_fault.isChecked() and faults and state["output_on"]:
                device.output_off()
                self.log(f"Safety interlock: output disabled ({', '.join(faults)})")
        except Exception as error:
            self.monitor_labels["communication"].setText(str(error))
            self.log(f"Communication error: {error}")

    def read_device(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        try:
            values = device.read_settings()
            self.voltage_setpoint.setValue(values["voltage"])
            self.current_limit.setValue(values["current"])
            self.ovp_limit.setValue(values["ovp"])
            self.uvp_limit.setValue(values["uvp"])
            self.foldback_enabled.setChecked(values["foldback"])
            self.auto_restart.setChecked(values["auto_restart"])
            self.output_enabled.setChecked(values["output"])
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
        voltage = self.voltage_setpoint.value()
        current = self.current_limit.value()
        if voltage > self.max_voltage.value() or current > self.max_current.value() or voltage * current > self.max_power.value():
            self.show_error("Output setting exceeds the Safety limits.")
            return
        try:
            device.output_off()
            device.set_voltage(voltage)
            device.set_current(current)
            device.set_ovp(self.ovp_limit.value())
            device.set_uvp(self.uvp_limit.value())
            device.set_foldback(self.foldback_enabled.isChecked())
            device.set_auto_restart(self.auto_restart.isChecked())
            if self.output_enabled.isChecked():
                device.output_on()
            self.snapshot = deepcopy(self.profile_data())
            self.refresh_monitoring()
            self.log("Settings applied")
        except Exception as error:
            self.show_error(error)

    def clear_faults(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        try:
            self.get_device().write(":DCL;")
            self.refresh_monitoring()
            self.log("Fault registers cleared")
        except Exception as error:
            self.show_error(error)

    def profile_data(self):
        return {
            "port": self.port_input.text(),
            "output": {"voltage": self.voltage_setpoint.value(), "current": self.current_limit.value(), "enabled": self.output_enabled.isChecked()},
            "protection": {"ovp": self.ovp_limit.value(), "uvp": self.uvp_limit.value(), "foldback": self.foldback_enabled.isChecked(), "auto_restart": self.auto_restart.isChecked()},
            "safety": {"max_voltage": self.max_voltage.value(), "max_current": self.max_current.value(), "max_power": self.max_power.value(), "off_disconnect": self.output_off_disconnect.isChecked(), "block_on_fault": self.block_output_on_fault.isChecked()},
        }

    def load_profile_data(self, data):
        self.port_input.setText(data.get("port", self.port_input.text()))
        output = data.get("output", {})
        self.voltage_setpoint.setValue(output.get("voltage", 0)); self.current_limit.setValue(output.get("current", 1)); self.output_enabled.setChecked(output.get("enabled", False))
        protection = data.get("protection", {})
        self.ovp_limit.setValue(protection.get("ovp", 38)); self.uvp_limit.setValue(protection.get("uvp", 0)); self.foldback_enabled.setChecked(protection.get("foldback", False)); self.auto_restart.setChecked(protection.get("auto_restart", False))
        safety = data.get("safety", {})
        self.max_voltage.setValue(safety.get("max_voltage", 36)); self.max_current.setValue(safety.get("max_current", 12)); self.max_power.setValue(safety.get("max_power", 432)); self.output_off_disconnect.setChecked(safety.get("off_disconnect", True)); self.block_output_on_fault.setChecked(safety.get("block_on_fault", True))

    def revert(self):
        if self.snapshot is None:
            self.log("Nothing to revert")
            return
        self.load_profile_data(deepcopy(self.snapshot))
        self.log("Reverted to last read/applied settings")

    def save_profile(self):
        default = Path.cwd() / "config" / "zup36_12_profile.json"
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save ZUP Profile", str(default), "JSON Files (*.json)")
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

    def _notify_main(self):
        self.sync_connection_status()
        if self.main_window:
            self.main_window.update_device_status()

    def show_error(self, error):
        QMessageBox.critical(self, "ZUP36-12 Error", str(error))
        self.log(error)

    def log(self, message):
        self.log_box.append(str(message))
        if self.main_window:
            self.main_window.log(f"ZUP36-12: {message}")
