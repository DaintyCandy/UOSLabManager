import json
import time
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .driver import GPD3303S


class GPD3303SPanel(QWidget):
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

        self.off_confirmation_pending = False
        self.off_confirmation_start = 0.0
        self.off_confirmation_warning_shown = False

    def _build_ui(self):
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self._build_connection_group(), 1)
        top.addWidget(self._build_monitor_group(), 2)
        root.addLayout(top)

        buttons = QHBoxLayout()
        for text, callback in (
            ("Read Device", self.read_device),
            ("Apply Settings", self.apply_settings),
            ("Reset", self.reset_settings),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        self.output_off_now_button = QPushButton("OUTPUT OFF NOW")
        self.output_off_now_button.setStyleSheet("color:white; background-color:#b00020; font-weight:bold;")
        self.output_off_now_button.clicked.connect(self.output_off_now)
        buttons.addWidget(self.output_off_now_button)
        buttons.addStretch()
        root.addLayout(buttons)

        self.sync_connection_status()

    def _build_connection_group(self):
        group = QGroupBox("GPD-3303S Connection")
        layout = QFormLayout(group)
        self.port_input = QLineEdit()
        self.write_terminator_input = QLineEdit("\\n")
        self.read_terminator_input = QLineEdit("\\r")
        self.output_off_on_connect = QCheckBox("Send OUT0 after connect")
        self.output_off_on_connect.setChecked(True)
        self.output_off_on_close = QCheckBox("Send OUT0 on disconnect")
        self.output_off_on_close.setChecked(True)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        self.status_label = QLabel("Disconnected")
        self.status_label.setStyleSheet("color:red; font-weight:bold;")
        layout.addRow("Port", self.port_input)
        layout.addRow("Command terminator", self.write_terminator_input)
        layout.addRow("Response terminator", self.read_terminator_input)
        layout.addRow(self.output_off_on_connect)
        layout.addRow(self.output_off_on_close)
        layout.addRow(self.connect_button, self.status_label)
        return group

    def _build_monitor_group(self):
        group = QGroupBox("GPD-3303S Control")
        layout = QGridLayout(group)
        self.ch1_voltage = QDoubleSpinBox()
        self.ch1_voltage.setRange(0, 30)
        self.ch1_voltage.setDecimals(3)
        self.ch1_voltage.setValue(0)
        self.ch1_current = QDoubleSpinBox()
        self.ch1_current.setRange(0, 3)
        self.ch1_current.setDecimals(3)
        self.ch1_current.setValue(0)
        self.ch2_voltage = QDoubleSpinBox()
        self.ch2_voltage.setRange(0, 30)
        self.ch2_voltage.setDecimals(3)
        self.ch2_voltage.setValue(0)
        self.ch2_current = QDoubleSpinBox()
        self.ch2_current.setRange(0, 3)
        self.ch2_current.setDecimals(3)
        self.ch2_current.setValue(0)
        self.output_enabled = QCheckBox("Overall Output ON")
        self.output_enabled.setChecked(False)
        self.output_enabled.toggled.connect(self.handle_output_toggle)
        self.output_status = QLabel("Output OFF")
        self.output_status.setStyleSheet("font-weight:bold;")
        self.ch1_set_button = QPushButton("Set CH1")
        self.ch1_set_button.clicked.connect(lambda: self.apply_channel_settings("CH1"))
        self.ch2_set_button = QPushButton("Set CH2")
        self.ch2_set_button.clicked.connect(lambda: self.apply_channel_settings("CH2"))
        self.device_status = QLabel("No device connected")
        self.device_status.setWordWrap(True)
        layout.addWidget(QLabel("CH1 Voltage [V]"), 0, 0)
        layout.addWidget(self.ch1_voltage, 0, 1)
        layout.addWidget(QLabel("CH1 Current [A]"), 0, 2)
        layout.addWidget(self.ch1_current, 0, 3)
        layout.addWidget(self.ch1_set_button, 0, 4)
        layout.addWidget(QLabel("CH2 Voltage [V]"), 1, 0)
        layout.addWidget(self.ch2_voltage, 1, 1)
        layout.addWidget(QLabel("CH2 Current [A]"), 1, 2)
        layout.addWidget(self.ch2_current, 1, 3)
        layout.addWidget(self.ch2_set_button, 1, 4)
        layout.addWidget(self.output_enabled, 2, 0, 1, 2)
        layout.addWidget(self.output_status, 2, 2, 1, 3)
        layout.addWidget(QLabel("Status"), 3, 0)
        layout.addWidget(self.device_status, 3, 1, 1, 4)
        return group

    def _parse_terminator(self, value: str) -> str:
        return value.replace("\\r", "\r").replace("\\n", "\n")

    def get_device(self):
        return self.manager.get_device(self.plugin.device_id)

    def toggle_connection(self):
        if self.get_device() is None:
            self.connect_device()
        else:
            self.disconnect_device()

    def connect_device(self):
        if self.get_device() is not None:
            return
        port = self.port_input.text().strip()
        if not port:
            self.show_error("Enter the GPD-3303S serial port before connecting.")
            return
        terminator = self._parse_terminator(self.write_terminator_input.text())
        response_terminator = self._parse_terminator(self.read_terminator_input.text())
        output_off_after_connect = self.output_off_on_connect.isChecked()
        output_off_on_close = self.output_off_on_close.isChecked()

        def create_identified_device():
            device = GPD3303S(
                port,
                write_termination=terminator,
                read_termination=response_terminator,
                output_off_on_connect=False,
                output_off_on_close=output_off_on_close,
            )
            try:
                device.identify()
                if output_off_after_connect:
                    device.output_off()
                return device
            except Exception:
                # Do not send OUT0 to a serial device that was not identified.
                device.output_off_on_close = False
                device.close()
                raise

        try:
            self.manager.add_device(
                self.plugin.device_id,
                create_identified_device,
            )
            self.log("Connected")
            self.monitor_timer.start()
            self.sync_connection_status()
            self.read_device()
        except Exception as error:
            self.show_error(error)

    def disconnect_device(self):
        self._cancel_off_confirmation()
        device = self.get_device()
        if device is not None and self.output_off_on_close.isChecked():
            try:
                device.output_off()
            except Exception:
                pass
        self.manager.remove_device(self.plugin.device_id)
        self.monitor_timer.stop()
        self.log("Disconnected")
        self.sync_connection_status()

    def _format_monitor_value(self, value):
        try:
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return "-"

    def refresh_monitoring(self):

        device = self.get_device()
        if device is None:
            self.monitor_timer.stop()
            self.sync_connection_status()
            return
        try:
            state = self.manager.get_latest(self.plugin.device_id)
            if not state:
                if self.off_confirmation_pending:
                    self.output_status.setText("Output OFF 확인 중...")
                    self.output_status.setStyleSheet("color:orange; font-weight:bold;")
                    return
                self.device_status.setText("Waiting for device data...")
                return
            self.device_status.setText(
                f"CH1 {self._format_monitor_value(state.get('CH1_voltage_V'))}V / {self._format_monitor_value(state.get('CH1_current_A'))}A, "
                f"CH2 {self._format_monitor_value(state.get('CH2_voltage_V'))}V / {self._format_monitor_value(state.get('CH2_current_A'))}A, "
                f"STATUS? {state.get('status_raw', '-')}"
            )
            if self.off_confirmation_pending:
                output_on = state.get("output_on")
                if output_on is False:
                    self._cancel_off_confirmation()
                    self.output_enabled.blockSignals(True)
                    self.output_enabled.setChecked(False)
                    self.output_enabled.blockSignals(False)
                    self.output_status.setText("Output OFF")
                    self.output_status.setStyleSheet("color:red; font-weight:bold;")
                else:
                    elapsed = time.monotonic() - self.off_confirmation_start
                    if elapsed > 5.0:
                        if not self.off_confirmation_warning_shown:
                            QMessageBox.warning(self, "GPD-3303S Warning", "Output OFF 확인 실패")
                            self.off_confirmation_warning_shown = True
                        self.output_status.setText("Output OFF 확인 실패")
                        self.output_status.setStyleSheet("color:red; font-weight:bold;")
                    else:
                        self.output_status.setText("Output OFF 확인 중...")
                        self.output_status.setStyleSheet("color:orange; font-weight:bold;")
                return
            self.output_status.setText("Output ON" if state.get("output_on") else "Output OFF")
            self.output_status.setStyleSheet(
                "color:green; font-weight:bold;" if state.get("output_on") else "color:red; font-weight:bold;"
            )
        except Exception as error:
            self.show_error(error)
            self.manager.remove_device(self.plugin.device_id)
            self.monitor_timer.stop()
            self.sync_connection_status()

    def read_device(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        try:
            values = device.read_settings()
            self.ch1_voltage.setValue(values.get("CH1_voltage_setpoint", 0.0))
            self.ch1_current.setValue(values.get("CH1_current_setpoint", 0.0))
            self.ch2_voltage.setValue(values.get("CH2_voltage_setpoint", 0.0))
            self.ch2_current.setValue(values.get("CH2_current_setpoint", 0.0))
            self.output_enabled.blockSignals(True)
            self.output_enabled.setChecked(values.get("output_on", False))
            self.output_enabled.blockSignals(False)
            self.log("Device settings read")
        except Exception as error:
            self.show_error(error)

    def _apply_channel_settings(self, channel: str):
        device = self.get_device()
        if device is None:
            raise RuntimeError("Connect the device first.")
        if channel == "CH1":
            voltage = self.ch1_voltage.value()
            current = self.ch1_current.value()
        else:
            voltage = self.ch2_voltage.value()
            current = self.ch2_current.value()
        if voltage > GPD3303S.MAX_VOLTAGE or current > GPD3303S.MAX_CURRENT:
            raise ValueError("Channel setting exceeds device limits")
        device.set_channel_current(channel, current)
        device.set_channel_voltage(channel, voltage)
        self.log(f"{channel} settings applied")

    def apply_channel_settings(self, channel: str):
        try:
            self._apply_channel_settings(channel)
        except Exception as error:
            self.show_error(error)

    def apply_settings(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        try:
            requested_output_on = self.output_enabled.isChecked()

            # Always establish a known-safe OFF state before changing limits.
            device.output_off()
            self._apply_channel_settings("CH1")
            self._apply_channel_settings("CH2")

            if requested_output_on:
                answer = QMessageBox.question(
                    self,
                    "Confirm GPD-3303S Output",
                    (
                        "Enable the GPD-3303S outputs with these settings?\n\n"
                        f"CH1: {self.ch1_voltage.value():.3f} V / "
                        f"{self.ch1_current.value():.3f} A\n"
                        f"CH2: {self.ch2_voltage.value():.3f} V / "
                        f"{self.ch2_current.value():.3f} A\n\n"
                        "OUT1 is global. CH3 may also become active."
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    self.output_enabled.setChecked(False)
                    self.log("Output enable cancelled; output remains OFF")
                    return
                device.output_on()
            self.log("Settings applied")
        except Exception as error:
            self.output_enabled.setChecked(False)
            try:
                device.output_off()
            except Exception:
                pass
            self.show_error(error)

    def reset_settings(self):
        self.ch1_voltage.setValue(0)
        self.ch1_current.setValue(0)
        self.ch2_voltage.setValue(0)
        self.ch2_current.setValue(0)
        self.output_enabled.setChecked(False)

    def _start_off_confirmation(self):
        self.off_confirmation_pending = True
        self.off_confirmation_start = time.monotonic()
        self.off_confirmation_warning_shown = False
        self.output_status.setText("Output OFF 확인 중...")
        self.output_status.setStyleSheet("color:orange; font-weight:bold;")

    def _cancel_off_confirmation(self):
        self.off_confirmation_pending = False
        self.off_confirmation_start = 0.0
        self.off_confirmation_warning_shown = False

    def output_off_now(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        try:
            device.output_off()
            self.output_enabled.blockSignals(True)
            self.output_enabled.setChecked(False)
            self.output_enabled.blockSignals(False)
            self._start_off_confirmation()
            self.log("Emergency OUT0 sent")
        except Exception as error:
            self._cancel_off_confirmation()
            self.output_status.setText("OUT0 전송 실패")
            self.output_status.setStyleSheet("color:red; font-weight:bold;")
            self.show_error(error)

    def handle_output_toggle(self, enabled: bool):
        if enabled:
            self.output_status.setText("Output ON requested - press Apply Settings")
        else:
            self.output_status.setText("Output OFF requested - press Apply Settings")

    def sync_connection_status(self):
        connected = self.get_device() is not None
        self.status_label.setText("Connected" if connected else "Disconnected")
        self.status_label.setStyleSheet(
            "color:green; font-weight:bold;" if connected else "color:red; font-weight:bold;"
        )

    def show_error(self, error):
        message = str(error)
        QMessageBox.critical(self, "GPD-3303S Error", message)
        self.log(message)

    def log(self, message):
        if hasattr(self.main_window, "log"):
            self.main_window.log(message)
