import json
import time
from copy import deepcopy
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from .video import CTVideoView
from .connection import create_ctvideo, default_connection
from .driver import CTVideo3M
from .panel_calibration import CTVideoCalibrationMixin
from .panel_video import CTVideoControlsMixin
from .usb_camera import resolve_camera_for_port
from .video_display import CompactConnectVideoDisplaySettings
from gui.widget_busy_spinner import run_busy_task


class CTVideo3MPanel(
    CTVideoCalibrationMixin, CTVideoControlsMixin, QWidget
):
    COLORS = {"actual_temp_C": "#ffb74d"}

    def __init__(self, manager, plugin, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.plugin = plugin
        self.main_window = parent
        self.snapshot = None
        # Exact pyrometer values read from the connected device.  This is kept
        # separate from the UI/profile snapshot so opening a connection can
        # never turn profile defaults into device writes.
        self.device_settings_snapshot = None
        self.plot_started_at = time.monotonic()
        self.plot_times = []
        self.plot_values = {key: [] for key in self.COLORS}
        self.last_plotted_update = None
        self.compactconnect_video_gain_supported = False
        self.compactconnect_anti_flicker_supported = False
        self.calibration_snapshot = None
        self._calibration_busy = False
        self._video_attach_attempted = False
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
        self.tabs.addTab(self._build_calibration_tab(), "Calibration")
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
        self.port_input = QLineEdit(default_connection())
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
        self.log_box.document().setMaximumBlockCount(2000)
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

        camera_group = QGroupBox("CompactConnect Video Display")
        camera_layout = QVBoxLayout(camera_group)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_body = QWidget()
        scroll_layout = QVBoxLayout(scroll_body)

        defaults = CompactConnectVideoDisplaySettings()
        image_group = QGroupBox("Image")
        image_form = QFormLayout(image_group)
        self.video_red_gain = self._spin(0.0, 10.0, defaults.red_gain, 2)
        self.video_green_gain = self._spin(0.0, 10.0, defaults.green_gain, 2)
        self.video_blue_gain = self._spin(0.0, 10.0, defaults.blue_gain, 2)
        self.video_brightness = self._spin(0.0, 10.0, defaults.brightness, 2)
        for control in (
            self.video_red_gain, self.video_green_gain,
            self.video_blue_gain, self.video_brightness,
        ):
            control.setSingleStep(0.01)
        self.video_rotation = self._integer_spin(0, 359, defaults.rotation_deg)
        self.video_black_white = QCheckBox("Enabled")
        self.video_black_white.setChecked(defaults.black_and_white)
        self.video_mirror_x = QCheckBox("Enabled")
        self.video_mirror_x.setChecked(defaults.mirror_x)
        self.video_mirror_y = QCheckBox("Enabled")
        self.video_mirror_y.setChecked(defaults.mirror_y)
        image_form.addRow("Red gain", self.video_red_gain)
        image_form.addRow("Green gain", self.video_green_gain)
        image_form.addRow("Blue gain", self.video_blue_gain)
        image_form.addRow("Display brightness", self.video_brightness)
        image_form.addRow("Rotation [deg]", self.video_rotation)
        image_form.addRow("Black and white", self.video_black_white)
        image_form.addRow("Mirror-X", self.video_mirror_x)
        image_form.addRow("Mirror-Y", self.video_mirror_y)
        scroll_layout.addWidget(image_group)

        overlay_group = QGroupBox("Target Circle and Background")
        overlay_form = QFormLayout(overlay_group)
        self.target_circle_style = QComboBox()
        self.target_circle_style.addItem("Dotted line", "dotted")
        self.target_circle_style.addItem("Solid", "solid")
        self.target_circle_style.setCurrentIndex(
            self.target_circle_style.findData(defaults.target_circle_style)
        )
        self.target_circle_width = self._integer_spin(
            0, 25, defaults.target_circle_width
        )
        self.target_circle_color = self._make_color_button(
            "Target circle color", defaults.target_circle_color
        )
        self.video_background_color = self._make_color_button(
            "Background color", defaults.background_color
        )
        self.background_circle_color = self._make_color_button(
            "Background circle color", defaults.background_circle_color
        )
        self.background_circle_diameter = self._integer_spin(
            100, 1200, defaults.background_circle_diameter
        )
        overlay_form.addRow("Target line style", self.target_circle_style)
        overlay_form.addRow("Target line width", self.target_circle_width)
        overlay_form.addRow("Target line color", self.target_circle_color)
        overlay_form.addRow("Background color", self.video_background_color)
        overlay_form.addRow(
            "Background circle / outside color", self.background_circle_color
        )
        overlay_form.addRow("BG circle diameter / zoom", self.background_circle_diameter)
        scroll_layout.addWidget(overlay_group)

        hardware_group = QGroupBox("Camera Hardware (CompactConnect Vendor XU)")
        hardware_form = QFormLayout(hardware_group)
        self.compactconnect_video_gain = self._integer_spin(1, 255, 180)
        self.compactconnect_video_gain.setEnabled(False)
        self.video_gain_readback = QLabel("Read camera hardware first")
        gain_row = QWidget()
        gain_layout = QHBoxLayout(gain_row)
        gain_layout.setContentsMargins(0, 0, 0, 0)
        gain_layout.addWidget(self.compactconnect_video_gain)
        gain_layout.addWidget(self.video_gain_readback, 1)
        self.compactconnect_anti_flicker = QComboBox()
        self.compactconnect_anti_flicker.addItem("Off", 0)
        self.compactconnect_anti_flicker.addItem("50 Hz", 1)
        self.compactconnect_anti_flicker.addItem("60 Hz", 2)
        self.compactconnect_anti_flicker.setEnabled(False)
        self.anti_flicker_readback = QLabel("Read camera hardware first")
        anti_row = QWidget()
        anti_layout = QHBoxLayout(anti_row)
        anti_layout.setContentsMargins(0, 0, 0, 0)
        anti_layout.addWidget(self.compactconnect_anti_flicker)
        anti_layout.addWidget(self.anti_flicker_readback, 1)
        hardware_form.addRow("Video Gain / YTarget", gain_row)
        hardware_form.addRow("Anti-flicker", anti_row)
        scroll_layout.addWidget(hardware_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_body)
        camera_layout.addWidget(scroll, 1)

        camera_buttons = QGridLayout()
        self.read_camera_button = QPushButton("Read Camera Hardware")
        self.read_camera_button.clicked.connect(self.read_camera_hardware_settings)
        self.apply_display_button = QPushButton("Apply Display")
        self.apply_display_button.clicked.connect(self.apply_video_display_settings)
        self.reset_display_button = QPushButton("Standard Display")
        self.reset_display_button.clicked.connect(self.reset_video_display_settings)
        self.write_video_gain_button = QPushButton(
            "Write Gain..."
        )
        self.write_video_gain_button.clicked.connect(
            self.apply_compactconnect_video_gain
        )
        self.write_video_gain_button.setEnabled(False)
        self.write_anti_flicker_button = QPushButton("Write Anti-flicker...")
        self.write_anti_flicker_button.clicked.connect(
            self.apply_compactconnect_anti_flicker
        )
        self.write_anti_flicker_button.setEnabled(False)
        camera_buttons.addWidget(self.read_camera_button, 0, 0)
        camera_buttons.addWidget(self.apply_display_button, 0, 1)
        camera_buttons.addWidget(self.reset_display_button, 0, 2)
        camera_buttons.addWidget(self.write_video_gain_button, 1, 0)
        camera_buttons.addWidget(self.write_anti_flicker_button, 1, 1)
        camera_buttons.setColumnStretch(3, 1)
        camera_layout.addLayout(camera_buttons)
        vendor_warning = QLabel(
            "Image and overlay controls are software display settings. Video Gain "
            "and Anti-flicker write persistent camera EEPROM and are excluded "
            "from Apply Display and saved profiles."
        )
        vendor_warning.setWordWrap(True)
        vendor_warning.setStyleSheet("color:#d98200;")
        camera_layout.addWidget(vendor_warning)
        self.camera_status_label = QLabel("Camera hardware: not read")
        self.camera_status_label.setWordWrap(True)
        camera_layout.addWidget(self.camera_status_label)

        for control in (
            self.video_red_gain, self.video_green_gain, self.video_blue_gain,
            self.video_brightness, self.video_rotation,
            self.target_circle_width, self.background_circle_diameter,
        ):
            control.valueChanged.connect(self._video_display_changed)
        for control in (
            self.video_black_white, self.video_mirror_x, self.video_mirror_y,
        ):
            control.toggled.connect(self._video_display_changed)
        self.target_circle_style.currentIndexChanged.connect(
            self._video_display_changed
        )

        splitter.addWidget(camera_group)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 1])
        pyrometer_group.setMinimumWidth(0)
        camera_group.setMinimumWidth(0)
        layout.addWidget(splitter)
        return panel

    def _build_calibration_tab(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        warning = QLabel(
            "WARNING: Tweak Offset and Tweak Gain change the pyrometer's "
            "linear temperature calibration. Stop any heating control before "
            "writing. Calibration is never loaded from a profile or written by "
            "the normal Apply button."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "background:#5b3200; color:#ffd9a0; border:1px solid #d98200; "
            "padding:8px; font-weight:600;"
        )
        layout.addWidget(warning)

        identity_group = QGroupBox("Calibration Device Identity")
        identity_form = QFormLayout(identity_group)
        self.calibration_serial_label = QLabel("-")
        self.calibration_firmware_label = QLabel("-")
        identity_form.addRow("Serial number", self.calibration_serial_label)
        identity_form.addRow("Firmware revision", self.calibration_firmware_label)
        layout.addWidget(identity_group)

        values_group = QGroupBox("Linear Pyrometer Calibration")
        grid = QGridLayout(values_group)
        for column, title in enumerate(
            ("Parameter", "Current device value", "Proposed value", "Read-back / status")
        ):
            header = QLabel(f"<b>{title}</b>")
            grid.addWidget(header, 0, column)

        offset_spec, gain_spec = CTVideo3M.CALIBRATION_FIELDS
        self.calibration_offset_current = QLabel("-")
        self.calibration_offset_proposed = self._spin(
            offset_spec.minimum, offset_spec.maximum, 0.0, offset_spec.decimals
        )
        self.calibration_offset_proposed.setSingleStep(offset_spec.step)
        self.calibration_offset_readback = QLabel("Read current calibration first")
        grid.addWidget(QLabel("Tweak Offset [°C]"), 1, 0)
        grid.addWidget(self.calibration_offset_current, 1, 1)
        grid.addWidget(self.calibration_offset_proposed, 1, 2)
        grid.addWidget(self.calibration_offset_readback, 1, 3)

        self.calibration_gain_current = QLabel("-")
        self.calibration_gain_proposed = self._spin(
            gain_spec.minimum, gain_spec.maximum, 1.0, gain_spec.decimals
        )
        self.calibration_gain_proposed.setSingleStep(gain_spec.step)
        self.calibration_gain_readback = QLabel("Read current calibration first")
        grid.addWidget(QLabel("Tweak Gain"), 2, 0)
        grid.addWidget(self.calibration_gain_current, 2, 1)
        grid.addWidget(self.calibration_gain_proposed, 2, 2)
        grid.addWidget(self.calibration_gain_readback, 2, 3)

        for label in (
            self.calibration_offset_current, self.calibration_offset_readback,
            self.calibration_gain_current, self.calibration_gain_readback,
        ):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
        self.calibration_offset_proposed.setEnabled(False)
        self.calibration_gain_proposed.setEnabled(False)
        self.calibration_offset_proposed.valueChanged.connect(
            self._calibration_proposal_changed
        )
        self.calibration_gain_proposed.valueChanged.connect(
            self._calibration_proposal_changed
        )
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 2)
        layout.addWidget(values_group)

        self.calibration_ack = QCheckBox(
            "I understand and authorize this calibration change."
        )
        self.calibration_ack.toggled.connect(self._update_calibration_actions)
        layout.addWidget(self.calibration_ack)

        actions = QHBoxLayout()
        self.read_calibration_button = QPushButton("Read Current Calibration")
        self.read_calibration_button.clicked.connect(self.read_calibration)
        self.apply_calibration_button = QPushButton("Write Calibration to Device...")
        self.apply_calibration_button.clicked.connect(self.apply_calibration)
        self.apply_calibration_button.setStyleSheet(
            "QPushButton:enabled { background:#9b4d00; color:white; font-weight:600; }"
        )
        actions.addWidget(self.read_calibration_button)
        actions.addWidget(self.apply_calibration_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.calibration_status_label = QLabel(
            "Connect the pyrometer, then read its current calibration."
        )
        self.calibration_status_label.setWordWrap(True)
        layout.addWidget(self.calibration_status_label)
        layout.addStretch()
        self._update_calibration_actions()
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
        self.device_settings_snapshot = None
        self._invalidate_calibration_snapshot(
            "Read calibration after connecting to verify the device identity."
        )
        port = self.port_input.text().strip()
        interval = 1.0 / self.refresh_rate.value()

        def connect():
            try:
                self.manager.add_device(
                    "CTVIDEO3M",
                    lambda: create_ctvideo(port, verify=True),
                    interval=interval,
                )
                try:
                    camera_info, camera_error = resolve_camera_for_port(port), None
                except Exception as caught:
                    camera_info, camera_error = ({
                        "PortName": port,
                        "CameraIndex": 1,
                        "CameraName": "CTvideo OpenCV fallback",
                        "CameraDevicePath": "OpenCV preferred index 1 with recovery",
                    }, caught)
                settings = self.get_device().read_settings()
                return camera_info, camera_error, settings
            except Exception:
                if self.get_device() is not None:
                    self.manager.remove_device("CTVIDEO3M")
                raise

        def connected(result):
            device_info, camera_error, settings = result
            self._apply_device_settings(settings)
            self.log("Initial device settings read and preserved (no writes)")
            if camera_error is not None:
                self.log(
                    f"Camera mapping failed ({camera_error}); "
                    "starting automatic OpenCV source recovery."
                )
            self._show_connection_addresses(device_info)
            self._video_attach_attempted = True
            if not self.video_view.start_preview(
                device_info["CameraIndex"], device_info["CameraName"],
                self.video_display_settings(), device_info,
            ):
                raise RuntimeError("The CTvideo camera thread did not start.")
            self.monitor_timer.start()
            self.log(
                f"Pyrometer and sibling camera connected: {port}, "
                f"{device_info['CameraName']} [{device_info['CameraIndex']}]"
            )
            self._notify_main()
            self.read_camera_hardware_settings()

        def failed(error):
            self.video_view.stop_preview()
            if self.get_device() is not None:
                run_busy_task(
                    self, lambda: self.manager.remove_device("CTVIDEO3M"),
                    lambda _result: self._notify_main(),
                    lambda cleanup_error: self.log(str(cleanup_error)),
                    key="connection_cleanup",
                )
            self._invalidate_calibration_snapshot(
                "Connection failed; calibration writes are disabled."
            )
            self._notify_main()
            self.show_error(error)

        run_busy_task(
            self, connect, connected, failed,
            key="connection",
        )

    def _resolve_camera_info(self, port):
        try:
            return resolve_camera_for_port(port)
        except Exception as camera_error:
            # The capture worker tries alternative backends and indices if
            # this preferred fallback is unavailable.
            self.log(
                f"Camera mapping failed ({camera_error}); "
                "starting automatic OpenCV source recovery."
            )
            return {
                "PortName": port,
                "CameraIndex": 1,
                "CameraName": "CTvideo OpenCV fallback",
                "CameraDevicePath": "OpenCV preferred index 1 with recovery",
            }

    def ensure_video_preview(self):
        if (
            self.get_device() is None
            or self.video_view.worker is not None
            or self._video_attach_attempted
        ):
            return
        self._video_attach_attempted = True
        try:
            info = self._resolve_camera_info(self.port_input.text().strip())
            self._show_connection_addresses(info)
            if not self.video_view.start_preview(
                info["CameraIndex"], info["CameraName"],
                self.video_display_settings(), info,
            ):
                self._video_attach_attempted = False
                raise RuntimeError("The CTvideo camera thread did not start.")
            self.log("Attached to the shared CTvideo camera preview")
        except Exception as error:
            self.log(f"Camera preview attach failed: {error}")

    def disconnect_device(self):
        if self.get_device() is None:
            return
        self.monitor_timer.stop()
        self.stop_video()
        self._video_attach_attempted = False
        self._invalidate_calibration_snapshot(
            "Disconnected. Reconnect and read calibration before writing."
        )
        def disconnected(_result):
            self.device_settings_snapshot = None
            self.log("Pyrometer communication disconnected")
            self._notify_main()

        def failed(error):
            disconnected(None)
            self.show_error(error)

        run_busy_task(
            self,
            lambda: self.manager.remove_device("CTVIDEO3M"),
            disconnected,
            failed,
            key="connection",
        )

    def stop_video(self):
        self.video_view.stop_preview()
        self.compactconnect_video_gain_supported = False
        self.compactconnect_anti_flicker_supported = False
        self.compactconnect_video_gain.setEnabled(False)
        self.compactconnect_anti_flicker.setEnabled(False)
        self.write_video_gain_button.setEnabled(False)
        self.write_anti_flicker_button.setEnabled(False)
        self.video_gain_readback.setText("Read camera hardware after reconnecting")
        self.anti_flicker_readback.setText(
            "Read camera hardware after reconnecting"
        )
        self.camera_status_label.setText("Camera hardware: disconnected")

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
        device = self.get_device()
        if device is None:
            self.show_error("Connect the pyrometer first.")
            return
        run_busy_task(
            self,
            device.read_settings,
            lambda values: (
                self._apply_device_settings(values),
                self.log("Device settings read"),
                self.read_camera_hardware_settings(),
            ),
            self.show_error,
            key="device_action",
        )

    def _apply_device_settings(self, values):
        self.emissivity.setValue(values["emissivity"])
        self.transmission.setValue(values["transmission"])
        self.average_time.setValue(values["average_time_s"])
        self.smart_averaging.setChecked(values["smart_averaging"])
        self.peak_hold.setValue(values["peak_hold_s"])
        self.device_settings_snapshot = {
            "emissivity": float(values["emissivity"]),
            "transmission": float(values["transmission"]),
            "average_time_s": float(values["average_time_s"]),
            "smart_averaging": bool(values["smart_averaging"]),
            "peak_hold_s": float(values["peak_hold_s"]),
        }
        self.snapshot = deepcopy(self.profile_data())

    def _edited_device_settings(self):
        return {
            "emissivity": self.emissivity.value(),
            "transmission": self.transmission.value(),
            "average_time_s": self.average_time.value(),
            "smart_averaging": self.smart_averaging.isChecked(),
            "peak_hold_s": self.peak_hold.value(),
        }

    def apply_settings(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the pyrometer first.")
            return
        if self.device_settings_snapshot is None:
            self.show_error(
                "Read the current device settings before writing. "
                "Reconnect or press Read Device first."
            )
            return
        requested = self._edited_device_settings()
        changed = {
            key: value for key, value in requested.items()
            if value != self.device_settings_snapshot[key]
        }

        def apply():
            setters = {
                "emissivity": device.set_emissivity,
                "transmission": device.set_transmission,
                "average_time_s": device.set_average_time,
                "smart_averaging": device.set_smart_averaging,
                "peak_hold_s": device.set_peak_hold_time,
            }
            for key, value in changed.items():
                setters[key](value)
            return device.read_settings()

        def completed(readback):
            self._apply_device_settings(readback)
            display_applied = self.apply_video_display_settings(log_change=False)
            self.log(
                (
                    "Changed pyrometer settings applied: "
                    + ", ".join(changed)
                    if changed else
                    "Pyrometer settings unchanged; no device write sent"
                )
                + ("; video display applied" if display_applied else "")
            )

        run_busy_task(
            self, apply, completed, self.show_error,
            key="device_action",
        )

    def profile_data(self):
        return {
            "port": self.port_input.text(),
            "refresh_rate_Hz": self.refresh_rate.value(),
            "emissivity": self.emissivity.value(),
            "transmission": self.transmission.value(),
            "average_time_s": self.average_time.value(),
            "smart_averaging": self.smart_averaging.isChecked(),
            "peak_hold_s": self.peak_hold.value(),
            "video_display": self.video_display_settings(),
        }

    def load_profile_data(self, data):
        self.port_input.setText(data.get("port", default_connection()))
        self.refresh_rate.setValue(data.get("refresh_rate_Hz", 10.0))
        self.emissivity.setValue(data.get("emissivity", 1.0))
        self.transmission.setValue(data.get("transmission", 1.0))
        self.average_time.setValue(data.get("average_time_s", 0.0))
        self.smart_averaging.setChecked(data.get("smart_averaging", False))
        self.peak_hold.setValue(data.get("peak_hold_s", 0.0))
        self._set_video_display_controls(data.get("video_display", {}))
        if self.video_view.worker is not None:
            self.apply_video_display_settings(log_change=False)

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
        if connected:
            self.ensure_video_preview()
        else:
            self._video_attach_attempted = False
        self._update_calibration_actions()
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
