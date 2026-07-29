import json
import time
from copy import deepcopy
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from gui.panel_ctvideo import CTVideoView
from .driver import CTVideo3M
from .usb_camera import resolve_camera_for_port


class CTVideo3MPanel(QWidget):
    COLORS = {"actual_temp_C": "#ffb74d"}

    def __init__(self, manager, plugin, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.plugin = plugin
        self.main_window = parent
        self.snapshot = None
        self.plot_started_at = time.monotonic()
        self.plot_times = []
        self.plot_values = {key: [] for key in self.COLORS}
        self.last_plotted_update = None
        self.camera_gain_supported = False
        self.camera_brightness_supported = False
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.refresh_monitoring)
        self._build_ui()
        self._apply_refresh_rate()
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _build_ui(self):
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(self._build_monitor(), 3)
        top.addWidget(self._build_log(), 2)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_pyrometer_tab(), "Pyrometer")
        self.tabs.addTab(self._build_settings(), "Settings")
        self.tabs.addTab(self._build_connect_tab(), "Connection")
        root.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        for text, callback in (("Read Device", self.read_device), ("Revert", self.revert),
                               ("Save Profile", self.save_profile), ("Apply", self.apply_settings)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        root.addLayout(buttons)
        self.sync_connection_status()

    def _build_monitor(self):
        group = QGroupBox("CTvideo 3M")
        layout = QGridLayout(group)
        self.port_input = QLineEdit("COM6")
        self.status_label = QLabel("Disconnected")
        self.response_label = QLabel("Response: -")
        self.connection_button = QPushButton("Connect")
        self.connection_button.clicked.connect(self.toggle_connection)
        layout.addWidget(QLabel("Port"), 0, 0)
        layout.addWidget(self.port_input, 0, 1)
        layout.addWidget(self.status_label, 0, 2)
        layout.addWidget(self.connection_button, 0, 3)
        self.monitor_labels = {}
        items = (("object", "Object temperature"), ("actual", "Actual temperature"),
                 ("head", "Sensor head temperature"), ("box", "Electronics box temperature"))
        for row, (key, title) in enumerate(items, start=1):
            layout.addWidget(QLabel(title), row, 0)
            label = QLabel("-")
            layout.addWidget(label, row, 1, 1, 2)
            self.monitor_labels[key] = label
        layout.addWidget(self.response_label, 1, 3)
        return group

    def _build_log(self):
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(150)
        self.log_box.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        layout.addWidget(self.log_box)
        return group

    def _build_pyrometer_tab(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        graph_group = QGroupBox("Temperature Tracking")
        graph_layout = QVBoxLayout(graph_group)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "Temperature", units="°C")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.addLegend()
        self.curves = {}
        for key, color in self.COLORS.items():
            self.curves[key] = self.plot.plot(
                [], [], name="Actual", pen=pg.mkPen(color, width=2)
            )
        graph_layout.addWidget(self.plot)
        splitter.addWidget(graph_group)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.video_view = CTVideoView(self.log)
        self.video_view.camera_properties.connect(self.update_camera_properties)
        right_layout.addWidget(self.video_view, 1)
        measurement = QGroupBox("Measured Temperature")
        measurement_layout = QHBoxLayout(measurement)
        self.measured_temperature = QLabel("- °C")
        self.measured_temperature.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.measured_temperature.setStyleSheet("font-size:22pt; font-weight:700;")
        measurement_layout.addWidget(self.measured_temperature, 1)
        right_layout.addWidget(measurement)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([600, 600])
        layout.addWidget(splitter)
        return panel

    def _build_connect_tab(self):
        panel = QWidget()
        form = QFormLayout(panel)
        self.refresh_rate = self._spin(0.1, 100.0, 10.0, 1)
        self.refresh_rate.setSuffix(" Hz")
        self.refresh_rate.valueChanged.connect(self._apply_refresh_rate)
        self.port_address_label = QLabel("-")
        self.port_address_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.port_container_label = QLabel("-")
        self.port_container_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.camera_address_label = QLabel("-")
        self.camera_address_label.setWordWrap(True)
        self.camera_address_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.camera_container_label = QLabel("-")
        self.camera_container_label.setWordWrap(True)
        self.camera_container_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Serial port", QLabel("Set in the summary panel above"))
        form.addRow("Baud rate", QLabel("115200 baud, 8-N-1, timeout 0.5 s"))
        form.addRow("Data update rate", self.refresh_rate)
        form.addRow("Port address", self.port_address_label)
        form.addRow("Port Container ID", self.port_container_label)
        form.addRow("Camera address", self.camera_address_label)
        form.addRow("Camera Container ID", self.camera_container_label)
        return panel

    def _build_settings(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        pyrometer_group = QGroupBox("Pyrometer Settings")
        form = QFormLayout(pyrometer_group)
        self.emissivity = self._spin(0.001, 1.0, 1.0, 3)
        self.transmission = self._spin(0.001, 1.0, 1.0, 3)
        self.average_time = self._spin(0.0, 6553.5, 0.0, 1)
        self.smart_averaging = QCheckBox("Enabled")
        self.peak_hold = self._spin(0.0, 6553.5, 0.0, 1)
        form.addRow("Emissivity", self.emissivity)
        form.addRow("Transmission", self.transmission)
        form.addRow("Averaging time [s]", self.average_time)
        form.addRow("Smart averaging", self.smart_averaging)
        form.addRow("Peak hold [s]", self.peak_hold)
        splitter.addWidget(pyrometer_group)

        camera_group = QGroupBox("Camera Settings / UVC Initialization")
        camera_form = QFormLayout(camera_group)
        self.camera_brightness = self._integer_spin(-128, 255, -12)
        self.camera_contrast = self._integer_spin(0, 255, 25)
        self.camera_gain = self._integer_spin(0, 255, 4)
        self.camera_power_line = QComboBox()
        self.camera_power_line.addItem("Disabled", 0)
        self.camera_power_line.addItem("50 Hz", 1)
        self.camera_power_line.addItem("60 Hz", 2)
        self.camera_power_line.setCurrentIndex(2)
        self.camera_hue = self._integer_spin(-180, 180, 0)
        self.camera_saturation = self._integer_spin(0, 255, 64)
        self.camera_sharpness = self._integer_spin(0, 255, 0)
        self.camera_gamma = self._integer_spin(1, 500, 100)
        self.camera_ae_mode = QComboBox()
        for label, value in (("Manual", 1), ("Auto", 2),
                             ("Shutter priority", 4), ("Aperture priority", 8)):
            self.camera_ae_mode.addItem(label, value)
        self.camera_exposure = self._integer_spin(1, 10000, 312)
        self.camera_ae_priority = QCheckBox("Allow variable frame rate")
        self.camera_ae_priority.setChecked(True)
        self.camera_roi = QLineEdit("")
        self.camera_roi.setPlaceholderText("10 bytes hex, e.g. 00 01 ...")
        self.auto_exposure_label = QLabel("Auto exposure: -")
        for label, widget in (
            ("Brightness", self.camera_brightness), ("Contrast", self.camera_contrast),
            ("Gain", self.camera_gain), ("Power line", self.camera_power_line),
            ("Hue", self.camera_hue), ("Saturation", self.camera_saturation),
            ("Sharpness", self.camera_sharpness), ("Gamma", self.camera_gamma),
            ("Auto exposure mode", self.camera_ae_mode),
            ("Exposure absolute", self.camera_exposure),
            ("Auto exposure priority", self.camera_ae_priority),
            ("ROI", self.camera_roi), ("Camera status", self.auto_exposure_label),
        ):
            camera_form.addRow(label, widget)
        splitter.addWidget(camera_group)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 1])
        pyrometer_group.setMinimumWidth(0)
        camera_group.setMinimumWidth(0)
        layout.addWidget(splitter)
        return panel

    @staticmethod
    def _spin(minimum, maximum, value, decimals):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        return control

    @staticmethod
    def _integer_spin(minimum, maximum, value):
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        return control

    def _apply_refresh_rate(self, _value=None):
        interval_ms = max(10, round(1000.0 / self.refresh_rate.value()))
        self.monitor_timer.setInterval(interval_ms)

    def get_device(self):
        return self.manager.get_device("CTVIDEO3M")

    def toggle_connection(self):
        self.disconnect_device() if self.get_device() else self.connect_device()

    def connect_device(self):
        try:
            port = self.port_input.text().strip()
            interval = 1.0 / self.refresh_rate.value()
            self.manager.add_device("CTVIDEO3M", lambda: CTVideo3M(port), interval=interval)
            device_info = resolve_camera_for_port(port)
            self._show_connection_addresses(device_info)
            self.video_view.start_preview(
                device_info["CameraIndex"], device_info["CameraName"],
                self.camera_settings(),
            )
            self.monitor_timer.start()
            self.log(
                f"Pyrometer and sibling camera connected: {port}, "
                f"{device_info['CameraName']} [{device_info['CameraIndex']}]"
            )
            self._notify_main()
            self.read_device()
        except Exception as error:
            self.video_view.stop_preview()
            if self.get_device() is not None:
                self.manager.remove_device("CTVIDEO3M")
            self._notify_main()
            self.show_error(error)

    def disconnect_device(self):
        self.manager.remove_device("CTVIDEO3M")
        self.monitor_timer.stop()
        self.stop_video()
        self.log("Pyrometer communication disconnected")
        self._notify_main()

    def stop_video(self):
        self.video_view.stop_preview()

    def update_camera_properties(self, properties):
        raw = properties.get("auto_exposure_raw", 0.0)
        enabled = properties.get("auto_exposure", False)
        if enabled is None:
            self.auto_exposure_label.setText("Auto exposure: unsupported")
        else:
            self.auto_exposure_label.setText(
                f"Auto exposure: {'ON' if enabled else 'OFF'} (flags {raw})"
            )
        gain_supported = properties.get("gain_supported", False)
        self.camera_gain_supported = gain_supported
        gain_min = int(properties.get("gain_min") or 0)
        gain_max = int(properties.get("gain_max") or 4)
        gain_step = max(1, int(properties.get("gain_step") or 1))
        self.camera_gain.setRange(gain_min, gain_max)
        self.camera_gain.setSingleStep(gain_step)
        self.camera_gain.setTickInterval(gain_step)
        gain = properties.get("gain")
        self.camera_gain.setToolTip(
            f"Read-back: {gain}; range {gain_min}..{gain_max}, step {gain_step}"
        )
        brightness_supported = properties.get("brightness_supported", False)
        self.camera_brightness_supported = brightness_supported
        brightness_min = int(properties.get("brightness_min") or 0)
        brightness_max = int(properties.get("brightness_max") or 255)
        brightness_step = max(1, int(properties.get("brightness_step") or 1))
        self.camera_brightness.setRange(brightness_min, brightness_max)
        self.camera_brightness.setSingleStep(brightness_step)
        self.camera_brightness.setTickInterval(brightness_step)
        brightness = properties.get("brightness")
        self.camera_brightness.setToolTip(
            f"Read-back: {brightness}; range {brightness_min}..{brightness_max}, step {brightness_step}"
        )

    def _show_connection_addresses(self, info):
        self.port_address_label.setText(info.get("PortInstanceId") or "-")
        self.port_container_label.setText(info.get("PortContainerId") or "-")
        camera = info.get("CameraInstanceId") or "-"
        name = info.get("CameraName") or "Camera"
        index = info.get("CameraIndex")
        device_path = info.get("CameraDevicePath") or "-"
        self.camera_address_label.setText(f"{name} [{index}]\n{camera}\n{device_path}")
        self.camera_container_label.setText(info.get("CameraContainerId") or "-")

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        self.stop_video()

    def refresh_monitoring(self):
        if self.get_device() is None:
            self.monitor_timer.stop()
            self.sync_connection_status()
            return
        values = self.manager.get_latest("CTVIDEO3M")
        if values:
            actual = values["actual_temp_C"]
            for key, field in (("object", "object_temp_C"), ("actual", "actual_temp_C"),
                               ("head", "head_temp_C"), ("box", "box_temp_C")):
                self.monitor_labels[key].setText(f"{values[field]:.1f} °C")
            self.measured_temperature.setText(f"{actual:.1f} °C")
            updated = self.manager.get_metrics("CTVIDEO3M").get("updated_at")
            if updated == self.last_plotted_update:
                self.update_realtime_status()
                return
            self.last_plotted_update = updated
            elapsed = time.monotonic() - self.plot_started_at
            self.plot_times.append(elapsed)
            for key in self.COLORS:
                self.plot_values[key].append(values[key])
                self.curves[key].setData(self.plot_times, self.plot_values[key])
            self._trim_plot_history(elapsed)
        self.update_realtime_status()

    def _trim_plot_history(self, now, window_s=600.0):
        first = 0
        while first < len(self.plot_times) and self.plot_times[first] < now - window_s:
            first += 1
        if first:
            self.plot_times = self.plot_times[first:]
            for key in self.plot_values:
                self.plot_values[key] = self.plot_values[key][first:]

    def read_device(self):
        if self.get_device() is None:
            self.show_error("Connect the pyrometer first.")
            return
        try:
            values = self.get_device().read_settings()
            self.emissivity.setValue(values["emissivity"])
            self.transmission.setValue(values["transmission"])
            self.average_time.setValue(values["average_time_s"])
            self.smart_averaging.setChecked(values["smart_averaging"])
            self.peak_hold.setValue(values["peak_hold_s"])
            self.snapshot = deepcopy(self.profile_data())
            self.log("Device settings read")
        except Exception as error:
            self.show_error(error)

    def apply_settings(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the pyrometer first.")
            return
        try:
            camera_settings = self.camera_settings()
            device.set_emissivity(self.emissivity.value())
            device.set_transmission(self.transmission.value())
            device.set_average_time(self.average_time.value())
            device.set_smart_averaging(self.smart_averaging.isChecked())
            device.set_peak_hold_time(self.peak_hold.value())
            self.video_view.set_uvc_settings(camera_settings)
            self.snapshot = deepcopy(self.profile_data())
            self.log("Device settings applied")
        except Exception as error:
            self.show_error(error)

    def profile_data(self):
        return {"port": self.port_input.text(),
                "refresh_rate_Hz": self.refresh_rate.value(),
                "emissivity": self.emissivity.value(), "transmission": self.transmission.value(),
                "average_time_s": self.average_time.value(),
                "smart_averaging": self.smart_averaging.isChecked(),
                "peak_hold_s": self.peak_hold.value(),
                "camera": self.camera_settings_serializable()}

    def camera_settings(self):
        roi_text = self.camera_roi.text().replace(",", " ").strip()
        try:
            roi = bytes.fromhex(roi_text) if roi_text else bytes(10)
        except ValueError as error:
            raise ValueError("ROI must contain hexadecimal bytes.") from error
        if len(roi) != 10:
            raise ValueError("ROI must contain exactly 10 bytes.")
        return {
            "Brightness": self.camera_brightness.value(),
            "Contrast": self.camera_contrast.value(),
            "Gain": self.camera_gain.value(),
            "Power Line": self.camera_power_line.currentData(),
            "Hue": self.camera_hue.value(),
            "Saturation": self.camera_saturation.value(),
            "Sharpness": self.camera_sharpness.value(),
            "Gamma": self.camera_gamma.value(),
            "Auto Exposure Mode": self.camera_ae_mode.currentData(),
            "Exposure Absolute": self.camera_exposure.value(),
            "Auto Exposure Priority": int(self.camera_ae_priority.isChecked()),
            "ROI": roi,
        }

    def camera_settings_serializable(self):
        settings = self.camera_settings()
        settings["ROI"] = settings["ROI"].hex(" ")
        return settings

    def load_profile_data(self, data):
        self.port_input.setText(data.get("port", "COM6"))
        self.refresh_rate.setValue(data.get("refresh_rate_Hz", 10.0))
        self.emissivity.setValue(data.get("emissivity", 1.0))
        self.transmission.setValue(data.get("transmission", 1.0))
        self.average_time.setValue(data.get("average_time_s", 0.0))
        self.smart_averaging.setChecked(data.get("smart_averaging", False))
        self.peak_hold.setValue(data.get("peak_hold_s", 0.0))
        camera = data.get("camera", {})
        self.camera_brightness.setValue(camera.get("Brightness", -12))
        self.camera_contrast.setValue(camera.get("Contrast", 25))
        self.camera_gain.setValue(camera.get("Gain", 4))
        self.camera_power_line.setCurrentIndex(max(0, self.camera_power_line.findData(camera.get("Power Line", 2))))
        self.camera_hue.setValue(camera.get("Hue", 0))
        self.camera_saturation.setValue(camera.get("Saturation", 64))
        self.camera_sharpness.setValue(camera.get("Sharpness", 0))
        self.camera_gamma.setValue(camera.get("Gamma", 100))
        self.camera_ae_mode.setCurrentIndex(max(0, self.camera_ae_mode.findData(camera.get("Auto Exposure Mode", 1))))
        self.camera_exposure.setValue(camera.get("Exposure Absolute", 312))
        self.camera_ae_priority.setChecked(bool(camera.get("Auto Exposure Priority", 1)))
        self.camera_roi.setText(camera.get("ROI", ""))

    def revert(self):
        if self.snapshot is not None:
            self.load_profile_data(deepcopy(self.snapshot))
            self.log("Reverted to last read/applied settings")

    def save_profile(self):
        default = Path.cwd() / "config" / "ctvideo_3m_profile.json"
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save CTvideo 3M Profile", str(default), "JSON Files (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.profile_data(), indent=2), encoding="utf-8")
            self.log(f"Profile saved: {path}")

    def sync_connection_status(self):
        connected = self.get_device() is not None
        self.status_label.setText("Connected" if connected else "Disconnected")
        self.status_label.setStyleSheet(f"color:{'#2ecc71' if connected else '#e74c3c'}; font-weight:bold;")
        self.connection_button.setText("Disconnect" if connected else "Connect")
        self.port_input.setEnabled(not connected)
        self.refresh_rate.setEnabled(not connected)
        self.update_realtime_status()

    def update_realtime_status(self):
        response = self.manager.get_metrics("CTVIDEO3M")["response_ms"]
        self.response_label.setText("Response: -" if response is None else f"Response: {response:.1f} ms")

    def _notify_main(self):
        self.sync_connection_status()
        if self.main_window:
            self.main_window.update_device_status()

    def show_error(self, error):
        QMessageBox.critical(self, "CTvideo 3M Error", str(error))
        self.log(error)

    def log(self, message):
        self.log_box.append(str(message))
        if self.main_window:
            self.main_window.log(f"CTvideo 3M: {message}")
