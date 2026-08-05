import math
import time

import pyqtgraph as pg
from PyQt6.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from gui.panel_ctvideo import CTVideoView
from plugins.devices.ctvideo_3m.connection import create_ctvideo, default_connection
from plugins.devices.ctvideo_3m.usb_camera import resolve_camera_for_port
from plugins.devices.zup36_12.driver import ZUP36_12


class HeatingPIDWorker(QThread):
    status_changed = pyqtSignal(str)
    output_changed = pyqtSignal(float, float)
    safety_tripped = pyqtSignal(str)

    def __init__(self, manager, config, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.config = dict(config)
        self._last_temperature_update = None

    def _safe_output(self, device):
        errors = []
        for method, value in (
            ("output_off", None), ("set_voltage", 0.0), ("set_current", 0.0),
        ):
            try:
                if value is None:
                    getattr(device, method)()
                else:
                    getattr(device, method)(value)
            except Exception as error:
                errors.append(f"{method}: {error}")
        return errors

    def _validate_safety(self, temperature, zup_values, ct_metrics, zup_metrics):
        if not math.isfinite(temperature):
            return "Invalid pyrometer temperature"
        for name, metrics in (("CTvideo", ct_metrics), ("ZUP", zup_metrics)):
            age = metrics.get("age_ms")
            if not metrics.get("connected") or age is None or age > 2000:
                return f"{name} data is unavailable or stale"
        if temperature > self.config["max_temperature"]:
            return (
                f"Over-temperature: {temperature:.1f} °C > "
                f"{self.config['max_temperature']:.1f} °C"
            )
        for key, label, limit, unit in (
            ("voltage_V", "Over-voltage", self.config["voltage_limit"], "V"),
            ("current_A", "Over-current", self.config["current_limit"], "A"),
            ("power_W", "Over-power", self.config["power_limit"], "W"),
        ):
            value = zup_values.get(key)
            if value is None or not math.isfinite(value):
                return f"Invalid ZUP {key} reading"
            if value > limit:
                return f"{label}: {value:.3f} {unit} > {limit:.3f} {unit}"
        fault_names = [
            label for key, label in (
                ("ovp_fault", "OVP"), ("otp_fault", "OTP"),
                ("foldback_fault", "Foldback"), ("ac_fault", "AC"),
                ("programming_fault", "Programming"),
                ("communication_error", "Communication"),
            ) if zup_values.get(key)
        ]
        if fault_names:
            return f"ZUP fault: {', '.join(fault_names)}"
        return ""

    def run(self):
        device = self.manager.get_device("ZUP")
        if device is None:
            self.safety_tripped.emit("ZUP is disconnected")
            return
        config = self.config
        voltage_limit = config["voltage_limit"]
        current_limit = config["current_limit"]
        power_limit = config["power_limit"]
        current_cap = min(
            current_limit,
            0.0 if voltage_limit <= 0 else power_limit / voltage_limit,
        )
        integral = 0.0
        previous_temperature = None
        commanded_current = 0.0
        ramped_power = 0.0
        previous_at = time.monotonic()
        safety_reason = ""
        try:
            ct_values = self.manager.get_latest("CTVIDEO3M")
            zup_values = self.manager.get_latest("ZUP")
            temperature = ct_values.get("actual_temp_C")
            if temperature is None:
                safety_reason = "Pyrometer temperature is unavailable"
                return
            safety_reason = self._validate_safety(
                float(temperature), zup_values,
                self.manager.get_metrics("CTVIDEO3M"),
                self.manager.get_metrics("ZUP"),
            )
            if safety_reason:
                return
            device.output_off()
            device.set_current(0.0)
            device.set_voltage(voltage_limit)
            device.output_on()
            self.status_changed.emit("Running")
            while not self.isInterruptionRequested():
                ct_values = self.manager.get_latest("CTVIDEO3M")
                zup_values = self.manager.get_latest("ZUP")
                ct_metrics = self.manager.get_metrics("CTVIDEO3M")
                zup_metrics = self.manager.get_metrics("ZUP")
                temperature = ct_values.get("actual_temp_C")
                if temperature is None:
                    safety_reason = "Pyrometer temperature is unavailable"
                    break
                safety_reason = self._validate_safety(
                    float(temperature), zup_values, ct_metrics, zup_metrics
                )
                if safety_reason:
                    break
                updated_at = ct_metrics.get("updated_at")
                if updated_at != self._last_temperature_update:
                    self._last_temperature_update = updated_at
                    now = time.monotonic()
                    elapsed = max(0.001, now - previous_at)
                    previous_at = now
                    error = config["target_temperature"] - temperature
                    derivative = 0.0
                    if previous_temperature is not None:
                        derivative = -(temperature - previous_temperature) / elapsed
                    previous_temperature = temperature

                    candidate_integral = integral + error * elapsed
                    base_output = config["p"] * error + config["d"] * derivative
                    unsaturated = base_output + config["i"] * candidate_integral
                    if (
                        0.0 < unsaturated < current_cap
                        or (unsaturated >= current_cap and error < 0)
                        or (unsaturated <= 0.0 and error > 0)
                    ):
                        integral = candidate_integral
                    desired_current = base_output + config["i"] * integral
                    desired_current = max(0.0, min(current_cap, desired_current))

                    if (
                        config["current_ramp_enabled"]
                        and desired_current > commanded_current
                    ):
                        desired_current = min(
                            desired_current,
                            commanded_current + config["current_ramp_rate"] * elapsed,
                        )
                    desired_power = desired_current * voltage_limit
                    if (
                        config["power_ramp_enabled"]
                        and desired_power > ramped_power
                    ):
                        ramped_power = min(
                            desired_power,
                            ramped_power + config["power_ramp_rate"] * elapsed,
                        )
                        desired_current = min(
                            desired_current,
                            0.0 if voltage_limit <= 0 else ramped_power / voltage_limit,
                        )
                    else:
                        ramped_power = desired_power
                    commanded_current = desired_current
                    device.set_current(commanded_current)
                    self.output_changed.emit(commanded_current, ramped_power)
                for _ in range(10):
                    if self.isInterruptionRequested():
                        break
                    self.msleep(50)
        except Exception as error:
            safety_reason = f"Control error: {error}"
        finally:
            errors = self._safe_output(device)
            if safety_reason:
                detail = safety_reason
                if errors:
                    detail += f"; safe-output errors: {'; '.join(errors)}"
                self.safety_tripped.emit(detail)
            elif errors:
                self.safety_tripped.emit(
                    f"Safe-output command failed: {'; '.join(errors)}"
                )
            self.status_changed.emit("Stopped")


class HeatingControlPanel(QWidget):
    """Four-quadrant workspace for ZUP-powered pyrometer heating."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.main_window = parent
        self.owned_devices = set()
        self.started_at = time.monotonic()
        self.last_updates = {"CTVIDEO3M": None, "ZUP": None}
        self.times = []
        self.temperature_values = []
        self.voltage_values = []
        self.current_values = []
        self.power_values = []
        self.control_active = False
        self.control_worker = None
        self.control_safety_reason = ""
        self._build_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.sync_connection_status()

    def _build_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self._build_connections_and_log(), 0, 0)
        layout.addWidget(self._build_pyrometer_view(), 0, 1)
        layout.addWidget(self._build_settings_tabs(), 1, 0)
        layout.addWidget(self._build_graph(), 1, 1)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        self.setMinimumSize(800, 600)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def _build_connections_and_log(self):
        panel = QGroupBox("Devices / Measurements")
        layout = QHBoxLayout(panel)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        connection_grid = QGridLayout()
        connection_grid.addWidget(QLabel("Device"), 0, 0)
        connection_grid.addWidget(QLabel("Port"), 0, 1)
        connection_grid.addWidget(QLabel("Status"), 0, 2)

        self.zup_port = QLineEdit("COM4")
        self.zup_status = QLabel("Disconnected")
        self.zup_button = QPushButton("Connect")
        self.zup_button.clicked.connect(self.toggle_zup)
        connection_grid.addWidget(QLabel("ZUP 36-12"), 1, 0)
        connection_grid.addWidget(self.zup_port, 1, 1)
        connection_grid.addWidget(self.zup_status, 1, 2)
        connection_grid.addWidget(self.zup_button, 1, 3)

        self.ctvideo_port = QLineEdit(default_connection())
        self.ctvideo_status = QLabel("Disconnected")
        self.ctvideo_button = QPushButton("Connect")
        self.ctvideo_button.clicked.connect(self.toggle_ctvideo)
        connection_grid.addWidget(QLabel("CTvideo 3M"), 2, 0)
        connection_grid.addWidget(self.ctvideo_port, 2, 1)
        connection_grid.addWidget(self.ctvideo_status, 2, 2)
        connection_grid.addWidget(self.ctvideo_button, 2, 3)
        connection_grid.setColumnStretch(1, 1)
        left_layout.addLayout(connection_grid)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.document().setMaximumBlockCount(2000)
        self.log_box.setStyleSheet(
            "background:#000; color:#0f0; font-family:monospace;"
        )
        left_layout.addWidget(self.log_box, 1)
        layout.addWidget(left, 1)

        measurements = QGroupBox("Live Values / Graph Selection")
        measurement_grid = QGridLayout(measurements)
        self.value_buttons = {}
        value_definitions = (
            ("temperature", "Temperature", "°C", "#ff7043"),
            ("voltage", "Voltage", "V", "#42a5f5"),
            ("current", "Current", "A", "#66bb6a"),
            ("power", "Power", "W", "#ab47bc"),
        )
        for index, (key, title, unit, color) in enumerate(value_definitions):
            button = QPushButton(f"{title}\n-")
            button.setCheckable(True)
            button.setChecked(True)
            button.setMinimumSize(95, 66)
            button.setProperty("value_title", title)
            button.setProperty("value_unit", unit)
            button.setStyleSheet(
                f"QPushButton {{ color:{color}; font-size:12pt; font-weight:700; "
                "border:1px solid #777; border-radius:5px; }"
                f"QPushButton:checked {{ background:{color}; color:#111; "
                "border:2px solid white; }"
            )
            button.setToolTip(f"Show or hide {title} on the graph")
            button.toggled.connect(
                lambda checked, name=key: self.set_curve_visible(name, checked)
            )
            measurement_grid.addWidget(button, index, 0)
            self.value_buttons[key] = button
        measurement_grid.setColumnStretch(0, 1)
        layout.addWidget(measurements, 1)
        return panel

    def _build_pyrometer_view(self):
        panel = QGroupBox("Pyrometer")
        layout = QVBoxLayout(panel)
        self.video_view = CTVideoView(self.log)
        layout.addWidget(self.video_view, 1)
        return panel

    def _build_settings_tabs(self):
        group = QGroupBox("Device Settings")
        layout = QVBoxLayout(group)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.addTab(self._build_heating_settings(), "Heating Control")
        self.settings_tabs.addTab(self._build_zup_settings(), "ZUP 36-12")
        self.settings_tabs.addTab(self._build_ctvideo_settings(), "CTvideo 3M")
        layout.addWidget(self.settings_tabs)
        return group

    def _build_heating_settings(self):
        panel = QWidget()
        layout = QGridLayout(panel)

        target_group = QGroupBox("Temperature Target")
        target_form = QFormLayout(target_group)
        self.target_temperature = self._spin(-50.0, 2000.0, 300.0, 1, " °C")
        self.max_temperature = self._spin(-50.0, 2000.0, 500.0, 1, " °C")
        target_form.addRow("Target temperature", self.target_temperature)
        target_form.addRow("Safety temperature", self.max_temperature)

        ramp_group = QGroupBox("Current / Power Ramp Up")
        ramp_form = QFormLayout(ramp_group)
        self.current_ramp_enabled = QCheckBox("Enabled")
        self.current_ramp_enabled.setChecked(True)
        self.current_ramp_rate = self._spin(0.001, 12.0, 0.1, 3, " A/s")
        self.power_ramp_enabled = QCheckBox("Enabled")
        self.power_ramp_enabled.setChecked(True)
        self.power_ramp_rate = self._spin(0.01, 432.0, 1.0, 2, " W/s")
        ramp_form.addRow("Current ramp", self.current_ramp_enabled)
        ramp_form.addRow("Current rate", self.current_ramp_rate)
        ramp_form.addRow("Power ramp", self.power_ramp_enabled)
        ramp_form.addRow("Power rate", self.power_ramp_rate)

        pid_group = QGroupBox("PID")
        pid_form = QFormLayout(pid_group)
        self.pid_p = self._spin(0.0, 1000.0, 0.02, 4)
        self.pid_i = self._spin(0.0, 1000.0, 0.001, 4)
        self.pid_d = self._spin(0.0, 1000.0, 0.0, 4)
        pid_form.addRow("P [A/°C]", self.pid_p)
        pid_form.addRow("I [A/(°C·s)]", self.pid_i)
        pid_form.addRow("D [A·s/°C]", self.pid_d)

        limit_group = QGroupBox("Output Limits")
        limit_form = QFormLayout(limit_group)
        self.control_voltage_limit = self._spin(0.0, 36.0, 12.0, 2, " V")
        self.control_current_limit = self._spin(0.0, 12.0, 1.0, 3, " A")
        self.control_power_limit = self._spin(0.0, 432.0, 12.0, 2, " W")
        limit_form.addRow("Voltage limit", self.control_voltage_limit)
        limit_form.addRow("Current limit", self.control_current_limit)
        limit_form.addRow("Power limit", self.control_power_limit)

        layout.addWidget(target_group, 0, 0)
        layout.addWidget(ramp_group, 0, 1)
        layout.addWidget(pid_group, 1, 0)
        layout.addWidget(limit_group, 1, 1)
        for column in range(2):
            layout.setColumnStretch(column, 1)

        controls = QVBoxLayout()
        self.control_status = QLabel("Stopped")
        self.control_status.setStyleSheet("font-weight:bold; color:#e74c3c;")
        self.control_output_label = QLabel("Current: - / Power command: -")
        self.start_control_button = QPushButton("Start Heating Control")
        self.start_control_button.setStyleSheet(
            "background:#1f8f4e; color:white; font-weight:bold;"
        )
        self.start_control_button.clicked.connect(self.start_control)
        self.stop_control_button = QPushButton("Stop")
        self.stop_control_button.setStyleSheet(
            "background:#c0392b; color:white; font-weight:bold;"
        )
        self.stop_control_button.clicked.connect(self.stop_control)
        self.stop_control_button.setEnabled(False)
        self.control_setting_widgets = (
            self.target_temperature, self.max_temperature,
            self.current_ramp_enabled, self.current_ramp_rate,
            self.power_ramp_enabled, self.power_ramp_rate,
            self.pid_p, self.pid_i, self.pid_d,
            self.control_voltage_limit, self.control_current_limit,
            self.control_power_limit,
        )
        controls.addWidget(self.control_status)
        controls.addWidget(self.control_output_label)
        controls.addStretch()
        controls.addWidget(self.start_control_button)
        controls.addWidget(self.stop_control_button)
        layout.addLayout(controls, 2, 0, 1, 2)
        return panel

    def _build_zup_settings(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.zup_voltage = self._spin(0.0, 36.0, 0.0, 2, " V")
        self.zup_current = self._spin(0.0, 12.0, 1.0, 3, " A")
        self.zup_ovp = self._spin(0.0, 39.6, 38.0, 1, " V")
        self.zup_uvp = self._spin(0.0, 35.9, 0.0, 1, " V")
        self.zup_output = QCheckBox("Output ON")
        apply_button = QPushButton("Apply ZUP Settings")
        apply_button.clicked.connect(self.apply_zup_settings)
        read_button = QPushButton("Read Device")
        read_button.clicked.connect(self.read_zup_settings)
        buttons = QHBoxLayout()
        buttons.addWidget(read_button)
        buttons.addWidget(apply_button)
        form.addRow("Set voltage", self.zup_voltage)
        form.addRow("Current limit", self.zup_current)
        form.addRow("OVP", self.zup_ovp)
        form.addRow("UVP", self.zup_uvp)
        form.addRow("Output", self.zup_output)
        form.addRow(buttons)
        return panel

    def _build_ctvideo_settings(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.emissivity = self._spin(0.001, 1.0, 1.0, 3)
        self.transmission = self._spin(0.001, 1.0, 1.0, 3)
        self.average_time = self._spin(0.0, 6553.5, 0.0, 1, " s")
        self.smart_averaging = QCheckBox("Enabled")
        self.peak_hold = self._spin(0.0, 6553.5, 0.0, 1, " s")
        apply_button = QPushButton("Apply CTvideo Settings")
        apply_button.clicked.connect(self.apply_ctvideo_settings)
        read_button = QPushButton("Read Device")
        read_button.clicked.connect(self.read_ctvideo_settings)
        buttons = QHBoxLayout()
        buttons.addWidget(read_button)
        buttons.addWidget(apply_button)
        form.addRow("Emissivity", self.emissivity)
        form.addRow("Transmission", self.transmission)
        form.addRow("Averaging time", self.average_time)
        form.addRow("Smart averaging", self.smart_averaging)
        form.addRow("Peak hold", self.peak_hold)
        form.addRow(buttons)
        return panel

    def _build_graph(self):
        group = QGroupBox("Heating Graph")
        layout = QVBoxLayout(group)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "Measured value")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.addLegend(offset=(-10, 10))
        self.curves = {
            "temperature": self.plot.plot(
                [], [], name="Temperature [°C]", pen=pg.mkPen("#ff7043", width=2)
            ),
            "voltage": self.plot.plot(
                [], [], name="Voltage [V]", pen=pg.mkPen("#42a5f5", width=2)
            ),
            "current": self.plot.plot(
                [], [], name="Current [A]", pen=pg.mkPen("#66bb6a", width=2)
            ),
            "power": self.plot.plot(
                [], [], name="Power [W]", pen=pg.mkPen("#ab47bc", width=2)
            ),
        }
        layout.addWidget(self.plot)
        return group

    def set_curve_visible(self, name, visible):
        curve = getattr(self, "curves", {}).get(name)
        if curve is not None:
            curve.setVisible(visible)

    def _set_live_value(self, name, value):
        button = self.value_buttons[name]
        title = button.property("value_title")
        unit = button.property("value_unit")
        text = "-" if value is None else f"{value:.2f} {unit}"
        button.setText(f"{title}\n{text}")

    @staticmethod
    def _spin(minimum, maximum, value, decimals, suffix=""):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        control.setSuffix(suffix)
        return control

    def toggle_zup(self):
        if self.manager.get_device("ZUP") is None:
            self.connect_zup()
        else:
            self.disconnect_zup()

    def connect_zup(self):
        port = self.zup_port.text().strip()
        try:
            self.manager.add_device("ZUP", lambda: ZUP36_12(port), interval=0.5)
            self.owned_devices.add("ZUP")
            self.log(f"ZUP 36-12 connected: {port}")
            self._notify_main()
        except Exception as error:
            self.show_error("ZUP 36-12", error)

    def disconnect_zup(self):
        if self.control_active:
            self.stop_control(wait=True)
        device = self.manager.get_device("ZUP")
        if device is not None:
            errors = self._reset_zup_output(device)
            if errors:
                self.log(f"ZUP safe-reset warning: {'; '.join(errors)}")
        self.manager.remove_device("ZUP")
        self.owned_devices.discard("ZUP")
        self.log("ZUP 36-12 disconnected")
        self._notify_main()

    def toggle_ctvideo(self):
        if self.manager.get_device("CTVIDEO3M") is None:
            self.connect_ctvideo()
        else:
            self.disconnect_ctvideo()

    def connect_ctvideo(self):
        port = self.ctvideo_port.text().strip()
        try:
            self.manager.add_device(
                "CTVIDEO3M",
                lambda: create_ctvideo(port, verify=True),
                interval=0.1,
            )
            self.owned_devices.add("CTVIDEO3M")
            camera = resolve_camera_for_port(port)
            self.video_view.start_preview(
                camera["CameraIndex"], camera["CameraName"],
                camera_info=camera,
            )
            self.log(f"CTvideo 3M connected: {port}")
            self._notify_main()
        except Exception as error:
            self.video_view.stop_preview()
            if "CTVIDEO3M" in self.owned_devices:
                self.manager.remove_device("CTVIDEO3M")
                self.owned_devices.discard("CTVIDEO3M")
            self.show_error("CTvideo 3M", error)

    def disconnect_ctvideo(self):
        if self.control_active:
            self.stop_control(wait=True)
        self.video_view.stop_preview()
        self.manager.remove_device("CTVIDEO3M")
        self.owned_devices.discard("CTVIDEO3M")
        self.log("CTvideo 3M disconnected")
        self._notify_main()

    def read_zup_settings(self):
        device = self.manager.get_device("ZUP")
        if device is None:
            self.show_error("ZUP 36-12", "Connect the device first.")
            return
        try:
            values = device.read_settings()
            self.zup_voltage.setValue(values["voltage"])
            self.zup_current.setValue(values["current"])
            self.zup_ovp.setValue(values["ovp"])
            self.zup_uvp.setValue(values["uvp"])
            self.zup_output.setChecked(values["output"])
            self.log("ZUP settings read")
        except Exception as error:
            self.show_error("ZUP 36-12", error)

    def apply_zup_settings(self):
        device = self.manager.get_device("ZUP")
        if device is None:
            self.show_error("ZUP 36-12", "Connect the device first.")
            return
        try:
            device.set_ovp(self.zup_ovp.value())
            device.set_uvp(self.zup_uvp.value())
            device.set_voltage(self.zup_voltage.value())
            device.set_current(self.zup_current.value())
            device.output_on() if self.zup_output.isChecked() else device.output_off()
            self.log("ZUP settings applied")
        except Exception as error:
            self.show_error("ZUP 36-12", error)

    def read_ctvideo_settings(self):
        device = self.manager.get_device("CTVIDEO3M")
        if device is None:
            self.show_error("CTvideo 3M", "Connect the device first.")
            return
        try:
            values = device.read_settings()
            self.emissivity.setValue(values["emissivity"])
            self.transmission.setValue(values["transmission"])
            self.average_time.setValue(values["average_time_s"])
            self.smart_averaging.setChecked(values["smart_averaging"])
            self.peak_hold.setValue(values["peak_hold_s"])
            self.log("CTvideo settings read")
        except Exception as error:
            self.show_error("CTvideo 3M", error)

    def apply_ctvideo_settings(self):
        device = self.manager.get_device("CTVIDEO3M")
        if device is None:
            self.show_error("CTvideo 3M", "Connect the device first.")
            return
        try:
            device.set_emissivity(self.emissivity.value())
            device.set_transmission(self.transmission.value())
            device.set_average_time(self.average_time.value())
            device.set_smart_averaging(self.smart_averaging.isChecked())
            device.set_peak_hold_time(self.peak_hold.value())
            self.log("CTvideo settings applied")
        except Exception as error:
            self.show_error("CTvideo 3M", error)

    def start_control(self):
        zup = self.manager.get_device("ZUP")
        ctvideo = self.manager.get_device("CTVIDEO3M")
        if zup is None or ctvideo is None:
            self.show_error(
                "Heating Control", "Connect both ZUP 36-12 and CTvideo 3M first."
            )
            return
        if self.control_worker is not None and self.control_worker.isRunning():
            return
        ct_metrics = self.manager.get_metrics("CTVIDEO3M")
        zup_metrics = self.manager.get_metrics("ZUP")
        if any(
            metrics.get("age_ms") is None or metrics["age_ms"] > 2000
            for metrics in (ct_metrics, zup_metrics)
        ):
            self.show_error("Heating Control", "Current CTvideo and ZUP readings are required.")
            return
        if self.target_temperature.value() > self.max_temperature.value():
            self.show_error(
                "Heating Control", "Target temperature exceeds the safety temperature."
            )
            return
        config = {
            "target_temperature": self.target_temperature.value(),
            "max_temperature": self.max_temperature.value(),
            "p": self.pid_p.value(),
            "i": self.pid_i.value(),
            "d": self.pid_d.value(),
            "voltage_limit": self.control_voltage_limit.value(),
            "current_limit": self.control_current_limit.value(),
            "power_limit": self.control_power_limit.value(),
            "current_ramp_enabled": self.current_ramp_enabled.isChecked(),
            "current_ramp_rate": self.current_ramp_rate.value(),
            "power_ramp_enabled": self.power_ramp_enabled.isChecked(),
            "power_ramp_rate": self.power_ramp_rate.value(),
        }
        self.control_safety_reason = ""
        self.control_active = True
        for widget in self.control_setting_widgets:
            widget.setEnabled(False)
        self.settings_tabs.setTabEnabled(1, False)
        self.settings_tabs.setTabEnabled(2, False)
        self.start_control_button.setEnabled(False)
        self.stop_control_button.setEnabled(True)
        self.control_worker = HeatingPIDWorker(self.manager, config, self)
        self.control_worker.status_changed.connect(self.update_control_status)
        self.control_worker.output_changed.connect(self.update_control_output)
        self.control_worker.safety_tripped.connect(self.handle_safety_trip)
        self.control_worker.finished.connect(self.control_finished)
        self.control_worker.start()
        self.log("Heating control started")

    def stop_control(self, _checked=False, wait=False):
        worker = self.control_worker
        if worker is None or not worker.isRunning():
            self.control_active = False
            self.update_control_status("Stopped")
            return
        worker.requestInterruption()
        self.control_status.setText("Stopping / Safe output reset")
        self.stop_control_button.setEnabled(False)
        if wait and not worker.wait(4000):
            self.log("Heating control thread did not stop within 4 seconds")

    def update_control_status(self, status):
        if status == "Running":
            self.control_status.setText("Running / Current PID")
            self.control_status.setStyleSheet("font-weight:bold; color:#2ecc71;")
        elif self.control_safety_reason:
            self.control_status.setText("SAFETY STOP")
            self.control_status.setStyleSheet("font-weight:bold; color:#ff1744;")
        else:
            self.control_status.setText("Stopped")
            self.control_status.setStyleSheet("font-weight:bold; color:#e74c3c;")

    def update_control_output(self, current, power):
        self.control_output_label.setText(
            f"Current command: {current:.3f} A / Power command: {power:.2f} W"
        )

    def handle_safety_trip(self, reason):
        self.control_safety_reason = reason
        self.control_status.setText("SAFETY STOP")
        self.control_status.setStyleSheet("font-weight:bold; color:#ff1744;")
        self.log(f"SAFETY STOP: {reason}; output OFF, voltage/current reset to 0")

    def control_finished(self):
        worker = self.sender()
        if worker is self.control_worker:
            self.control_worker = None
        self.control_active = False
        for widget in self.control_setting_widgets:
            widget.setEnabled(True)
        self.settings_tabs.setTabEnabled(1, True)
        self.settings_tabs.setTabEnabled(2, True)
        self.start_control_button.setEnabled(True)
        self.stop_control_button.setEnabled(False)
        self.update_control_status("Stopped")
        if not self.control_safety_reason:
            self.log("Heating control stopped; output OFF, voltage/current reset to 0")
        worker.deleteLater()

    def refresh(self):
        self._handle_lost_connections()
        self.sync_connection_status()
        ct_values = self.manager.get_latest("CTVIDEO3M")
        zup_values = self.manager.get_latest("ZUP")
        self._set_live_value("temperature", ct_values.get("actual_temp_C"))
        self._set_live_value("voltage", zup_values.get("voltage_V"))
        self._set_live_value("current", zup_values.get("current_A"))
        self._set_live_value("power", zup_values.get("power_W"))
        ct_updated = self.manager.get_metrics("CTVIDEO3M")["updated_at"]
        zup_updated = self.manager.get_metrics("ZUP")["updated_at"]
        if ct_updated is None and zup_updated is None:
            return
        if (ct_updated, zup_updated) == (
            self.last_updates["CTVIDEO3M"], self.last_updates["ZUP"]
        ):
            return
        self.last_updates["CTVIDEO3M"] = ct_updated
        self.last_updates["ZUP"] = zup_updated
        self.times.append(time.monotonic() - self.started_at)
        self.temperature_values.append(ct_values.get("actual_temp_C", float("nan")))
        self.voltage_values.append(zup_values.get("voltage_V", float("nan")))
        self.current_values.append(zup_values.get("current_A", float("nan")))
        self.power_values.append(zup_values.get("power_W", float("nan")))
        if len(self.times) > 2400:
            for values in (
                self.times, self.temperature_values, self.voltage_values,
                self.current_values, self.power_values,
            ):
                del values[:-2400]
        self.curves["temperature"].setData(self.times, self.temperature_values)
        self.curves["voltage"].setData(self.times, self.voltage_values)
        self.curves["current"].setData(self.times, self.current_values)
        self.curves["power"].setData(self.times, self.power_values)

    def _handle_lost_connections(self):
        for device_id, display_name in (
            ("ZUP", "ZUP 36-12"), ("CTVIDEO3M", "CTvideo 3M"),
        ):
            if device_id not in self.owned_devices:
                continue
            if self.manager.get_device(device_id) is not None:
                continue
            self.owned_devices.discard(device_id)
            error = self.manager.get_metrics(device_id).get("error")
            self.log(
                f"{display_name} connection lost"
                + (f": {error}" if error else "")
            )
            if self.control_active:
                self.stop_control()
            if device_id == "CTVIDEO3M":
                self.video_view.stop_preview()

    def sync_connection_status(self):
        self._sync_device_widgets(
            "ZUP", self.zup_status, self.zup_button, self.zup_port
        )
        self._sync_device_widgets(
            "CTVIDEO3M", self.ctvideo_status, self.ctvideo_button,
            self.ctvideo_port,
        )

    def _sync_device_widgets(self, device_id, status, button, port):
        connected = self.manager.get_device(device_id) is not None
        status.setText("Connected" if connected else "Disconnected")
        status.setStyleSheet(
            f"color:{'#2ecc71' if connected else '#e74c3c'}; font-weight:bold;"
        )
        button.setText("Disconnect" if connected else "Connect")
        button.setStyleSheet(
            "color:white; font-weight:bold; background:"
            + ("#c0392b;" if connected else "#1f8f4e;")
        )
        port.setEnabled(not connected)

    def emergency_stop(self):
        was_active = self.control_active
        self.stop_control(wait=True)
        device = self.manager.get_device("ZUP")
        if device is not None:
            errors = self._reset_zup_output(device)
            if errors:
                self.log(f"Emergency safe-reset warning: {'; '.join(errors)}")
        self.zup_output.setChecked(False)
        if not was_active:
            self.log("Emergency stop: output OFF, voltage/current reset to 0")

    @staticmethod
    def _reset_zup_output(device):
        errors = []
        for method, value in (
            ("output_off", None), ("set_voltage", 0.0), ("set_current", 0.0),
        ):
            try:
                if value is None:
                    getattr(device, method)()
                else:
                    getattr(device, method)(value)
            except Exception as error:
                errors.append(f"{method}: {error}")
        return errors

    def shutdown(self):
        self.refresh_timer.stop()
        self.emergency_stop()
        self.video_view.stop_preview()
        for device_id in tuple(self.owned_devices):
            self.manager.remove_device(device_id)
        self.owned_devices.clear()
        self._notify_main()

    def _notify_main(self):
        self.sync_connection_status()
        if self.main_window is not None:
            self.main_window.update_device_status()

    def show_error(self, title, error):
        QMessageBox.critical(self, f"Heating Control / {title}", str(error))
        self.log(f"{title}: {error}")

    def log(self, message):
        stamp = time.strftime("%H:%M:%S")
        self.log_box.append(f"[{stamp}] {message}")
        if self.main_window is not None:
            self.main_window.log(f"Heating Control: {message}")
