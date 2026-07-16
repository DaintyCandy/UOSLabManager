import json
import time
from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .driver import ZUP36_12


class ZUP3612Panel(QWidget):
    def __init__(self, manager, plugin, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.plugin = plugin
        self.main_window = parent
        self.snapshot = None
        self.ramp_state = None
        self.ramp_timer = QTimer(self)
        self.ramp_timer.setInterval(200)
        self.ramp_timer.timeout.connect(self.advance_output_ramp)
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
        tabs.addTab(self._build_output_protection_tab(), "Output & Protection")
        tabs.addTab(self._build_safety_tab(), "Safety")
        root.addWidget(tabs, 1)

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
        self.port_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.status_label = QLabel("● Disconnected")
        self.status_label.setStyleSheet("color:#e74c3c; font-weight:bold;")
        self.connection_button = QPushButton("Connect")
        self.connection_button.clicked.connect(self.toggle_connection)
        read_device = QToolButton()
        read_device.setText("⟳")
        read_device.setToolTip("Read Device")
        read_device.setFixedSize(34, 30)
        read_device.setStyleSheet("font-size:16pt; font-weight:bold;")
        read_device.clicked.connect(self.read_device)
        layout.addWidget(QLabel("Port"), 0, 0)
        layout.addWidget(self.port_input, 0, 1, 1, 2)
        layout.addWidget(self.status_label, 0, 3)
        self.response_label = QLabel("Response: -")
        layout.addWidget(self.response_label, 0, 4)
        layout.addWidget(read_device, 0, 5)
        layout.addWidget(self.connection_button, 0, 6)
        self.monitor_labels = {}
        items = (
            ("set_output", "Set Voltage / Current"),
            ("actual_output", "Actual Voltage / Current"),
            ("ramp", "Voltage / Current Ramp"),
            ("state", "Power / CV-CC / Output"),
            ("faults", "OVP/OTP/Foldback Fault"),
            ("communication", "Communication Error"),
        )
        for row, (key, title) in enumerate(items, start=1):
            layout.addWidget(QLabel(title), row, 0)
            label = QLabel("-")
            label.setWordWrap(True)
            layout.addWidget(label, row, 1, 1, 6)
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

    def _build_output_protection_tab(self):
        panel = QWidget()
        layout = QHBoxLayout(panel)

        output_group = QGroupBox("Output Settings")
        output_form = QFormLayout(output_group)
        self.voltage_setpoint = self._spin(36, 0, 2)
        self.current_limit = self._spin(12, 1, 3)
        self.output_enabled = QCheckBox("Output ON")
        output_form.addRow("Set Voltage [V]", self.voltage_setpoint)
        output_form.addRow("Current Limit [A]", self.current_limit)
        output_form.addRow("Output", self.output_enabled)

        protection_group = QGroupBox("Protection")
        protection_form = QFormLayout(protection_group)
        self.ovp_limit = self._spin(39.6, 38, 1)
        self.uvp_limit = self._spin(35.9, 0, 1)
        self.foldback_enabled = QCheckBox("Foldback armed")
        self.auto_restart = QCheckBox("Auto restart")
        clear_faults = QPushButton("Clear fault registers")
        clear_faults.clicked.connect(self.clear_faults)
        protection_form.addRow("OVP [V]", self.ovp_limit)
        protection_form.addRow("UVP [V]", self.uvp_limit)
        protection_form.addRow("Foldback", self.foldback_enabled)
        protection_form.addRow("Recovery Mode", self.auto_restart)
        protection_form.addRow("Fault", clear_faults)

        ramp_group = QGroupBox("Ramp Settings")
        ramp_form = QFormLayout(ramp_group)
        self.voltage_ramp_enabled = QCheckBox("Enabled")
        self.voltage_ramp_rate = self._spin(36, 1, 3)
        self.voltage_ramp_rate.setMinimum(0.001)
        self.current_ramp_enabled = QCheckBox("Enabled")
        self.current_ramp_rate = self._spin(12, 0.5, 3)
        self.current_ramp_rate.setMinimum(0.001)
        ramp_form.addRow("Voltage Ramp", self.voltage_ramp_enabled)
        ramp_form.addRow("Voltage Rate [V/s]", self.voltage_ramp_rate)
        ramp_form.addRow("Current Ramp", self.current_ramp_enabled)
        ramp_form.addRow("Current Rate [A/s]", self.current_ramp_rate)

        for widget in (self.voltage_setpoint, self.current_limit):
            widget.valueChanged.connect(self.update_summary_settings)
        for widget in (
            self.voltage_ramp_enabled, self.current_ramp_enabled,
            self.voltage_ramp_rate, self.current_ramp_rate,
        ):
            signal = widget.toggled if isinstance(widget, QCheckBox) else widget.valueChanged
            signal.connect(self.update_summary_settings)

        for group in (output_group, protection_group, ramp_group):
            group.setMinimumWidth(0)
            group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            layout.addWidget(group, 1)
        self.update_summary_settings()
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

    def toggle_connection(self):
        if self.get_device() is None:
            self.connect_device()
        else:
            self.disconnect_device()

    def connect_device(self):
        if self.get_device() is not None:
            return
        try:
            port = self.port_input.text().strip()
            self.manager.add_device("ZUP", lambda: ZUP36_12(port))
            self.log("Connected")
            self.monitor_timer.start()
            self._notify_main()
            self.read_device()
        except Exception as error:
            self.show_error(error)

    def disconnect_device(self):
        self.ramp_timer.stop()
        self.ramp_state = None
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
            self.monitor_timer.stop()
            self.sync_connection_status()
            return
        try:
            state = self.manager.get_latest("ZUP")
            if not state:
                self.update_realtime_status()
                return
            self.monitor_labels["actual_output"].setText(
                f"{state['voltage_V']:.3f} V  |  {state['current_A']:.3f} A"
            )
            self.monitor_labels["state"].setText(
                f"{state['power_W']:.3f} W  |  {state['mode']}  |  "
                f"Output {'ON' if state['output_on'] else 'OFF'}"
            )
            faults = [name for name, key in (("OVP", "ovp_fault"), ("OTP", "otp_fault"), ("Foldback", "foldback_fault")) if state[key]]
            self.monitor_labels["faults"].setText(", ".join(faults) if faults else "OK")
            communication = state["programming_error_raw"] if state["communication_error"] else "OK"
            self.monitor_labels["communication"].setText(communication)
            self.update_summary_settings()
            if self.block_output_on_fault.isChecked() and faults and state["output_on"]:
                self.ramp_timer.stop()
                self.ramp_state = None
                device.output_off()
                self.log(f"Safety interlock: output disabled ({', '.join(faults)})")
                self.update_summary_settings()
            self.update_realtime_status()
        except Exception as error:
            self.monitor_labels["communication"].setText(str(error))
            self.monitor_timer.stop()
            self.manager.remove_device("ZUP")
            self.sync_connection_status()
            self.log(f"Connection lost; changed to Disconnected: {error}")
            if self.main_window:
                self.main_window.update_device_status()

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
            self.update_summary_settings()
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
            self.ramp_timer.stop()
            self.ramp_state = None
            current_settings = device.read_settings()
            device.set_ovp(self.ovp_limit.value())
            device.set_uvp(self.uvp_limit.value())
            device.set_foldback(self.foldback_enabled.isChecked())
            device.set_auto_restart(self.auto_restart.isChecked())
            ramp_voltage = self.output_enabled.isChecked() and self.voltage_ramp_enabled.isChecked()
            ramp_current = self.output_enabled.isChecked() and self.current_ramp_enabled.isChecked()
            start_voltage = current_settings["voltage"] if current_settings["output"] else 0.0
            start_current = current_settings["current"] if current_settings["output"] else 0.0
            if not ramp_voltage:
                device.set_voltage(voltage)
            elif not current_settings["output"]:
                device.set_voltage(start_voltage)
            if not ramp_current:
                device.set_current(current)
            elif not current_settings["output"]:
                device.set_current(start_current)
            if self.output_enabled.isChecked():
                device.output_on()
                if ramp_voltage or ramp_current:
                    self.start_output_ramp(
                        start_voltage, start_current,
                        voltage, current, ramp_voltage, ramp_current,
                    )
            else:
                device.output_off()
                device.set_voltage(voltage)
                device.set_current(current)
            self.snapshot = deepcopy(self.profile_data())
            self.refresh_monitoring()
            self.update_summary_settings()
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

    def start_output_ramp(self, voltage, current, target_voltage, target_current,
                          ramp_voltage, ramp_current):
        self.ramp_state = {
            "voltage": voltage, "current": current,
            "target_voltage": target_voltage, "target_current": target_current,
            "ramp_voltage": ramp_voltage, "ramp_current": ramp_current,
            "updated_at": time.monotonic(),
        }
        self.ramp_timer.start()
        self.update_summary_settings()
        self.log("Output ramp started")

    @staticmethod
    def _approach(value, target, step):
        if value < target:
            return min(target, value + step)
        return max(target, value - step)

    def advance_output_ramp(self):
        device = self.get_device()
        if device is None or self.ramp_state is None:
            self.ramp_timer.stop()
            self.ramp_state = None
            return
        state = self.ramp_state
        now = time.monotonic()
        elapsed = max(0.001, now - state["updated_at"])
        state["updated_at"] = now
        try:
            if state["ramp_voltage"]:
                state["voltage"] = self._approach(
                    state["voltage"], state["target_voltage"],
                    self.voltage_ramp_rate.value() * elapsed,
                )
                device.set_voltage(state["voltage"])
            if state["ramp_current"]:
                state["current"] = self._approach(
                    state["current"], state["target_current"],
                    self.current_ramp_rate.value() * elapsed,
                )
                device.set_current(state["current"])
        except Exception as error:
            self.ramp_timer.stop()
            self.ramp_state = None
            self.show_error(error)
            return
        voltage_done = not state["ramp_voltage"] or state["voltage"] == state["target_voltage"]
        current_done = not state["ramp_current"] or state["current"] == state["target_current"]
        if voltage_done and current_done:
            self.ramp_timer.stop()
            self.ramp_state = None
            self.log("Output ramp completed")
        self.update_summary_settings()

    def update_summary_settings(self, _value=None):
        if not hasattr(self, "monitor_labels") or not hasattr(self, "voltage_setpoint"):
            return
        self.monitor_labels["set_output"].setText(
            f"{self.voltage_setpoint.value():.3f} V  |  {self.current_limit.value():.3f} A"
        )
        voltage_text = (
            f"ON ({self.voltage_ramp_rate.value():g} V/s)"
            if self.voltage_ramp_enabled.isChecked() else "OFF"
        )
        current_text = (
            f"ON ({self.current_ramp_rate.value():g} A/s)"
            if self.current_ramp_enabled.isChecked() else "OFF"
        )
        running = "  |  RUNNING" if self.ramp_state is not None else ""
        self.monitor_labels["ramp"].setText(
            f"Voltage {voltage_text}  |  Current {current_text}{running}"
        )

    def profile_data(self):
        return {
            "port": self.port_input.text(),
            "output": {"voltage": self.voltage_setpoint.value(), "current": self.current_limit.value(), "enabled": self.output_enabled.isChecked()},
            "protection": {"ovp": self.ovp_limit.value(), "uvp": self.uvp_limit.value(), "foldback": self.foldback_enabled.isChecked(), "auto_restart": self.auto_restart.isChecked()},
            "ramp": {
                "voltage_enabled": self.voltage_ramp_enabled.isChecked(),
                "voltage_rate": self.voltage_ramp_rate.value(),
                "current_enabled": self.current_ramp_enabled.isChecked(),
                "current_rate": self.current_ramp_rate.value(),
            },
            "safety": {"max_voltage": self.max_voltage.value(), "max_current": self.max_current.value(), "max_power": self.max_power.value(), "off_disconnect": self.output_off_disconnect.isChecked(), "block_on_fault": self.block_output_on_fault.isChecked()},
        }

    def load_profile_data(self, data):
        self.port_input.setText(data.get("port", self.port_input.text()))
        output = data.get("output", {})
        self.voltage_setpoint.setValue(output.get("voltage", 0)); self.current_limit.setValue(output.get("current", 1)); self.output_enabled.setChecked(output.get("enabled", False))
        protection = data.get("protection", {})
        self.ovp_limit.setValue(protection.get("ovp", 38)); self.uvp_limit.setValue(protection.get("uvp", 0)); self.foldback_enabled.setChecked(protection.get("foldback", False)); self.auto_restart.setChecked(protection.get("auto_restart", False))
        ramp = data.get("ramp", {})
        self.voltage_ramp_enabled.setChecked(ramp.get("voltage_enabled", False))
        self.voltage_ramp_rate.setValue(ramp.get("voltage_rate", 1.0))
        self.current_ramp_enabled.setChecked(ramp.get("current_enabled", False))
        self.current_ramp_rate.setValue(ramp.get("current_rate", 0.5))
        safety = data.get("safety", {})
        self.max_voltage.setValue(safety.get("max_voltage", 36)); self.max_current.setValue(safety.get("max_current", 12)); self.max_power.setValue(safety.get("max_power", 432)); self.output_off_disconnect.setChecked(safety.get("off_disconnect", True)); self.block_output_on_fault.setChecked(safety.get("block_on_fault", True))
        self.update_summary_settings()

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
        self.connection_button.setText("Disconnect" if connected else "Connect")
        color = "#c0392b" if connected else "#1f8f4e"
        hover = "#e74c3c" if connected else "#27ae60"
        self.connection_button.setStyleSheet(
            f"QPushButton {{ background:{color}; color:white; font-weight:bold; }}"
            f"QPushButton:hover {{ background:{hover}; }}"
        )
        self.port_input.setEnabled(not connected)
        if connected and not self.monitor_timer.isActive():
            self.monitor_timer.start()
        elif not connected:
            self.monitor_timer.stop()
        self.update_realtime_status()

    def update_realtime_status(self):
        metrics = self.manager.get_metrics("ZUP")
        response = metrics["response_ms"]
        self.response_label.setText("Response: -" if response is None else f"Response: {response:.1f} ms")

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
