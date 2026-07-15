import csv
import json
import math
import time
from copy import deepcopy
from pathlib import Path

import pyqtgraph as pg
from PyQt6.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QProgressDialog, QSizePolicy, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

from .driver import LakeShore331


class CurveHeaderLoadWorker(QThread):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, device, curve, parent=None):
        super().__init__(parent)
        self.device = device
        self.curve = curve

    def run(self):
        try:
            header = self.device.get_curve_header(self.curve)
            points = self.device.get_curve_points(self.curve)
            self.loaded.emit((header, points))
        except Exception as error:
            self.failed.emit(str(error))


class LakeShore331Window(QWidget):
    SENSOR_TYPES = (
        ("Silicon Diode", 0), ("GaAlAs Diode", 1), ("PT-100 / 250", 2),
        ("PT-100 / 500", 3), ("PT-1000", 4), ("NTC RTD", 5),
        ("Thermocouple 25 mV", 6), ("Thermocouple 50 mV", 7),
        ("2.5 V / 1 mA", 8), ("7.5 V / 1 mA", 9),
    )
    HEATER_RANGES = (("Off", 0), ("Low", 1), ("Medium", 2), ("High", 3))
    STANDARD_CURVES = {
        1: "DT-470", 2: "DT-670", 3: "DT-500-D *", 4: "DT-500-E1 *",
        6: "PT-100", 7: "PT-1000 *", 8: "RX-102A-AA", 9: "RX-202A-AA",
        12: "Type K", 13: "Type E", 14: "Type T",
        15: "AuFe 0.03% *", 16: "AuFe 0.07%",
    }
    SENSOR_CURVES = {
        0: (1, 2, 3, 4),
        1: (),
        2: (6,),
        3: (6,),
        4: (7,),
        5: (8, 9),
        6: (12, 13, 14, 15, 16),
        7: (12, 13, 14, 15, 16),
        8: (),
        9: (),
    }

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.main_window = parent
        self.snapshot = None
        self.curve_points = {}
        self.input_history = {
            "A": {"time": [], "temperature": [], "sensor": []},
            "B": {"time": [], "temperature": [], "sensor": []},
        }
        self.tracking_start = time.monotonic()
        self.tracking_timer = QTimer(self)
        self.tracking_timer.setInterval(1000)
        self.tracking_timer.timeout.connect(self.refresh_input_tracking)
        self.tracking_error_active = False
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
        self.settings_tabs.addTab(self._build_safety_tab(), "Safety")
        self.settings_tabs.addTab(self._build_curve_editor_tab(), "Curve Editing")
        self.settings_tabs.setMaximumHeight(370)
        root.addWidget(self.settings_tabs, 1)

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
        group.setMaximumHeight(205)
        layout = QGridLayout(group)
        self.port_input = QLineEdit("COM3")
        self.port_input.setMaximumWidth(90)
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
        self.response_label = QLabel("Response: -")
        layout.addWidget(self.response_label, 1, 0, 1, 3)
        self.summary_labels = {}
        for row, (key, title) in enumerate((
            ("input_a", "Input A"), ("input_b", "Input B"),
            ("loop_1", "Loop 1"), ("loop_2", "Loop 2"), ("safety", "Safety"),
        ), start=2):
            layout.addWidget(QLabel(title), row, 0)
            label = QLabel("-")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label, row, 1, 1, 6)
            self.summary_labels[key] = label
        return group

    def _build_log(self):
        group = QGroupBox("Log")
        group.setMaximumHeight(205)
        layout = QVBoxLayout(group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(110)
        self.log_box.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        layout.addWidget(self.log_box)
        return group

    def _build_input_tab(self, channel):
        panel = QWidget()
        layout = QHBoxLayout(panel)
        sensor_group = QGroupBox("Input Configuration")
        sensor_form = QFormLayout(sensor_group)
        processing_group = QGroupBox("Curve and Processing")
        processing_form = QFormLayout(processing_group)
        input_name = QLineEdit(f"Input {channel}")
        hardware = QLabel("Diode/RTD")
        sensor = QComboBox()
        for name, value in self.SENSOR_TYPES:
            sensor.addItem(name, value)
        sensor_range = QLabel("-")
        excitation = QLabel("-")
        curve = QComboBox()
        preferred_unit = QComboBox()
        preferred_unit.addItems(("K", "°C", "Sensor units"))
        filter_enabled = QCheckBox("Enabled")
        filter_points = QSpinBox()
        filter_points.setRange(2, 64)
        filter_points.setValue(8)
        temperature = QLabel("-")
        sensor_reading = QLabel("-")
        sensor_form.addRow("Input Name", input_name)
        sensor_form.addRow("Sensor Type", sensor)
        sensor_form.addRow("Hardware Type", hardware)
        sensor_form.addRow("Sensor Range", sensor_range)
        sensor_form.addRow("Excitation", excitation)
        processing_form.addRow("Curve", curve)
        processing_form.addRow("Preferred Unit", preferred_unit)
        processing_form.addRow("Filter", filter_enabled)
        processing_form.addRow("Filter Points", filter_points)
        tracking_group = QGroupBox("Readings and Tracking")
        tracking_layout = QVBoxLayout(tracking_group)
        # Outer padding protects axis titles from the group-box frame. Axis
        # dimensions remain automatic so label-to-tick spacing is unchanged.
        tracking_layout.setContentsMargins(28, 20, 20, 30)
        readings = QGridLayout()
        readings.addWidget(QLabel("Temperature"), 0, 0)
        readings.addWidget(temperature, 0, 1)
        readings.addWidget(QLabel("Sensor Value"), 1, 0)
        readings.addWidget(sensor_reading, 1, 1)
        tracking_layout.addLayout(readings)
        tracking_plot = pg.PlotWidget()
        tracking_plot.setLabel("bottom", "Time", units="s")
        tracking_plot.setLabel("left", "Value")
        tracking_plot.getAxis("bottom").setHeight(52)
        tracking_plot.getAxis("left").setWidth(72)
        tracking_plot.addLegend(offset=(-10, 10))
        temperature_curve = tracking_plot.plot([], [], name="Temperature [K]", pen=pg.mkPen("#ef5350", width=2))
        sensor_curve = tracking_plot.plot([], [], name="Sensor Value", pen=pg.mkPen("#42a5f5", width=2))
        tracking_layout.addWidget(tracking_plot)
        for group in (sensor_group, processing_group, tracking_group):
            group.setMinimumWidth(0)
            group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(sensor_group, 1)
        layout.addWidget(processing_group, 1)
        layout.addWidget(tracking_group, 2)
        self.input_controls[channel] = {
            "name": input_name, "hardware": hardware,
            "sensor": sensor, "range": sensor_range, "excitation": excitation,
            "curve": curve, "preferred_unit": preferred_unit,
            "filter": filter_enabled, "filter_points": filter_points,
            "compensation": False,
            "temperature": temperature, "reading": sensor_reading,
            "tracking_plot": tracking_plot, "temperature_curve": temperature_curve,
            "sensor_curve": sensor_curve,
        }
        sensor.currentTextChanged.connect(lambda _, value=channel: self.update_input_options(value))
        self.update_input_options(channel)
        return panel

    def update_input_options(self, channel):
        controls = self.input_controls[channel]
        sensor_code = controls["sensor"].currentData()
        details = {
            0: ("Diode", "2.5 V", "10 µA"),
            1: ("Diode", "7.5 V", "10 µA"),
            2: ("Diode/RTD", "100 Ω Platinum / 250 K", "1 mA"),
            3: ("Diode/RTD", "100 Ω Platinum / 500 K", "1 mA"),
            4: ("Diode/RTD", "1000 Ω Platinum", "1 mA"),
            5: ("Diode/RTD", "NTC RTD", "10 µA"),
            6: ("Thermocouple", "25 mV", "Room compensation"),
            7: ("Thermocouple", "50 mV", "Room compensation"),
            8: ("Diode/RTD", "2.5 V range", "1 mA"),
            9: ("Diode/RTD", "7.5 V range", "1 mA"),
        }[sensor_code]
        controls["range"].setText(details[1])
        controls["hardware"].setText(details[0])
        controls["excitation"].setText(details[2])
        self.populate_curve_options(channel)

    def populate_curve_options(self, channel):
        controls = self.input_controls[channel]
        curve = controls["curve"]
        previous = curve.currentData()
        sensor_code = controls["sensor"].currentData()
        curve.blockSignals(True)
        curve.clear()
        curve.addItem("None", 0)
        for number in self.SENSOR_CURVES[sensor_code]:
            curve.addItem(self.STANDARD_CURVES[number], number)
        for number in range(21, 42):
            curve.addItem(f"User Curve {number}", number)
        index = curve.findData(previous)
        curve.setCurrentIndex(index if index >= 0 else 0)
        curve.blockSignals(False)

    def set_input_sensor_code(self, channel, code):
        controls = self.input_controls[channel]
        controls["sensor"].setCurrentIndex(max(0, controls["sensor"].findData(code)))
        self.update_input_options(channel)

    def _spin(self, minimum, maximum, value, decimals=3):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        return control

    def _build_loop_tab(self, loop):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        groups_layout = QHBoxLayout()
        controls = {
            "mode": QComboBox(), "input": QComboBox(), "units": QComboBox(),
            "setpoint": self._spin(-273.15, 1000, 300), "powerup": QCheckBox("Restore output after restart"),
            "display": QComboBox(), "resistance": self._spin(0.1, 10000, 50),
            "range": QComboBox(),
            "estimated_current": QLabel("0 A"), "estimated_power": QLabel("0 W"),
            "output_limit": self._spin(0, 100, 80), "preset": QComboBox(),
            "p": self._spin(0, 1000, 10), "i": self._spin(0, 1000, 20),
            "d": self._spin(0, 200, 0), "pid_manual": self._spin(0, 100, 0),
            "enabled": QCheckBox("Enable Loop 2") if loop == 2 else None,
            "ramp_enabled": QCheckBox("Enabled"),
            "ramp_rate": self._spin(0.001, 100, 1.0),
            "tune_status": QLabel("Inactive"),
        }
        if controls["enabled"] is not None:
            controls["enabled"].setChecked(True)
            layout.addWidget(controls["enabled"])
        controls["mode"].addItem("Off", 0)
        controls["mode"].addItem("Open Loop", 3)
        controls["mode"].addItem("Closed Loop", 1)
        controls["input"].addItem("Input A", "A")
        controls["input"].addItem("Input B", "B")
        controls["units"].addItem("K", 1)
        controls["units"].addItem("°C", 2)
        controls["units"].addItem("Sensor", 3)
        controls["display"].addItem("Current %", 1)
        controls["display"].addItem("Power %", 2)
        for name, value in self.HEATER_RANGES:
            controls["range"].addItem(name, value)
        for name, mode in (
            ("Manual PID", 1), ("Auto P", 6), ("Auto PI", 5),
            ("Auto PID", 4), ("Zone", 2),
        ):
            controls["preset"].addItem(name, mode)

        control_group = QGroupBox("Control Input")
        control_form = QFormLayout(control_group)
        control_form.addRow("Control Mode", controls["mode"])
        control_form.addRow("Control Input", controls["input"])
        control_form.addRow("Setpoint Unit", controls["units"])
        control_form.addRow("Setpoint", controls["setpoint"])
        control_form.addRow("Ramp", controls["ramp_enabled"])
        control_form.addRow("Ramp Rate [K/min]", controls["ramp_rate"])

        heater_group = QGroupBox("Heater")
        heater_form = QFormLayout(heater_group)
        heater_form.addRow("Power-up Heater", controls["powerup"])
        heater_form.addRow("Output Display", controls["display"])
        heater_form.addRow("Heater Range", controls["range"])
        heater_form.addRow("Output Limit [%]", controls["output_limit"])
        heater_form.addRow("Heater Resistance [Ω]", controls["resistance"])
        heater_form.addRow("Estimated Current", controls["estimated_current"])
        heater_form.addRow("Estimated Power", controls["estimated_power"])
        controls["estimated_current"].setToolTip("Software estimate using the selected range and heater resistance.")
        controls["estimated_power"].setToolTip("Range full-scale assumptions: Low 0.5 W, Medium 5 W, High 50 W.")
        controls["output_limit"].setToolTip("Software safety limit applied to PID Manual Output.")

        pid_group = QGroupBox("PID")
        pid_form = QFormLayout(pid_group)
        pid_form.addRow("P [0–1000]", controls["p"])
        pid_form.addRow("I [0–1000]", controls["i"])
        pid_form.addRow("D [0–200%]", controls["d"])
        pid_form.addRow("Manual Output [%]", controls["pid_manual"])
        pid_form.addRow("Preset", controls["preset"])
        pid_form.addRow("Tune Activated", controls["tune_status"])

        for group in (control_group, heater_group, pid_group):
            group.setMinimumWidth(0)
            group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        groups_layout.addWidget(control_group, 1)
        groups_layout.addWidget(heater_group, 1)
        groups_layout.addWidget(pid_group, 1)
        layout.addLayout(groups_layout)
        self.loop_controls[loop] = controls
        if controls["enabled"] is not None:
            configurable = (control_group, heater_group, pid_group)
            controls["enabled"].toggled.connect(
                lambda checked, number=loop, widgets=configurable: self.set_loop_ui_enabled(number, checked, widgets)
            )
        controls["preset"].currentIndexChanged.connect(lambda _, number=loop: self.apply_pid_preset(number))
        for key in ("resistance", "range", "pid_manual", "output_limit", "display"):
            signal = controls[key].currentIndexChanged if isinstance(controls[key], QComboBox) else controls[key].valueChanged
            signal.connect(lambda _, number=loop: self.update_heater_estimate(number))
        self.update_tune_status(loop)
        return panel

    def apply_pid_preset(self, loop):
        controls = self.loop_controls[loop]
        if controls["preset"].currentData() != 1:
            controls["mode"].setCurrentIndex(max(0, controls["mode"].findData(1)))
        self.update_tune_status(loop)

    def set_loop_ui_enabled(self, loop, checked, widgets):
        for widget in widgets:
            widget.setEnabled(checked)
        self.update_tune_status(loop)

    def update_tune_status(self, loop):
        controls = self.loop_controls[loop]
        loop_enabled = controls["enabled"] is None or controls["enabled"].isChecked()
        activated = loop_enabled and controls["preset"].currentData() in (4, 5, 6)
        controls["tune_status"].setText("Activated" if activated else "Inactive")
        controls["tune_status"].setStyleSheet(
            f"color:{'#2ecc71' if activated else '#808080'}; font-weight:bold;"
        )

    def update_heater_estimate(self, loop):
        controls = self.loop_controls[loop]
        resistance = controls["resistance"].value()
        range_power = {0: 0.0, 1: 0.5, 2: 5.0, 3: 50.0}[controls["range"].currentData()]
        output = min(controls["pid_manual"].value(), controls["output_limit"].value()) / 100.0
        if controls["display"].currentData() == 1:
            full_current = (range_power / resistance) ** 0.5 if range_power else 0.0
            current = full_current * output
            power = current * current * resistance
        else:
            power = range_power * output
            current = (power / resistance) ** 0.5 if power else 0.0
        controls["estimated_current"].setText(f"{current:.4g} A")
        controls["estimated_power"].setText(f"{power:.4g} W")

    def _build_curve_editor_tab(self):
        panel = QWidget()
        layout = QHBoxLayout(panel)
        header_group = QGroupBox("User Curve Header")
        header_form = QFormLayout(header_group)
        self.curve_number = QComboBox()
        for number in range(21, 42):
            self.curve_number.addItem(f"User Curve {number}", number)
        self.curve_name = QLineEdit()
        self.curve_serial = QLineEdit()
        self.curve_format = QComboBox()
        for name, value in (("mV/K", 1), ("V/K", 2), ("Ω/K", 3), ("log Ω/K", 4)):
            self.curve_format.addItem(name, value)
        self.curve_limit = self._spin(0, 1000, 325)
        self.curve_coefficient = QComboBox()
        self.curve_coefficient.addItem("Negative", 1)
        self.curve_coefficient.addItem("Positive", 2)
        header_form.addRow("Curve", self.curve_number)
        header_form.addRow("Name", self.curve_name)
        header_form.addRow("Serial Number", self.curve_serial)
        header_form.addRow("Format", self.curve_format)
        header_form.addRow("Temperature Limit [K]", self.curve_limit)
        header_form.addRow("Coefficient", self.curve_coefficient)
        read_header = QPushButton("Read Header")
        write_header = QPushButton("Write Header")
        delete_curve = QPushButton("Delete Curve")
        read_header.clicked.connect(self.read_curve_header)
        write_header.clicked.connect(self.write_curve_header)
        delete_curve.clicked.connect(self.delete_user_curve)
        header_form.addRow(read_header, write_header)
        header_form.addRow(delete_curve)

        point_group = QGroupBox("Curve Point")
        point_form = QFormLayout(point_group)
        self.curve_point_index = QSpinBox()
        self.curve_point_index.setRange(1, 200)
        self.curve_sensor_value = self._spin(-1e9, 1e9, 0, 6)
        self.curve_temperature = self._spin(0, 1000, 0, 6)
        point_form.addRow("Point Index", self.curve_point_index)
        point_form.addRow("Sensor Units", self.curve_sensor_value)
        point_form.addRow("Temperature [K]", self.curve_temperature)
        read_point = QPushButton("Read Point")
        write_point = QPushButton("Write Point")
        read_point.clicked.connect(self.read_curve_point)
        write_point.clicked.connect(self.write_curve_point)
        point_form.addRow(read_point, write_point)
        import_csv = QPushButton("Import CSV")
        apply_csv = QPushButton("Apply CSV Points")
        clear_preview = QPushButton("Clear Preview")
        import_csv.clicked.connect(self.import_curve_csv)
        apply_csv.clicked.connect(self.apply_curve_csv)
        clear_preview.clicked.connect(self.clear_curve_preview)
        self.curve_point_count = QLabel("0 points loaded")
        point_form.addRow(import_csv, apply_csv)
        point_form.addRow(clear_preview)
        point_form.addRow("CSV Status", self.curve_point_count)

        graph_group = QGroupBox("Curve Preview")
        graph_layout = QVBoxLayout(graph_group)
        graph_layout.setContentsMargins(20, 20, 32, 30)
        self.curve_plot = pg.PlotWidget()
        self.curve_plot.setLabel("bottom", "Sensor Value")
        self.curve_plot.showAxis("right")
        self.curve_plot.hideAxis("left")
        self.curve_plot.setLabel("right", "Temperature", units="K")
        self.curve_plot.getAxis("bottom").setHeight(52)
        self.curve_plot.getAxis("right").setWidth(78)
        self.curve_plot.showGrid(x=True, y=True, alpha=0.25)
        self.curve_preview = self.curve_plot.plot([], [], pen=pg.mkPen("#4da3ff", width=2), symbol="o", symbolSize=5)
        graph_layout.addWidget(self.curve_plot)
        for group in (header_group, point_group, graph_group):
            group.setMinimumWidth(0)
            group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(header_group, 1)
        layout.addWidget(point_group, 1)
        layout.addWidget(graph_group, 2)
        return panel

    def read_curve_header(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        if getattr(self, "curve_load_worker", None) is not None:
            return
        curve = self.curve_number.currentData()
        self.curve_loading_dialog = QProgressDialog(
            f"Reading user curve {curve} header and points...", None, 0, 0, self
        )
        self.curve_loading_dialog.setWindowTitle("Loading Curve")
        self.curve_loading_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.curve_loading_dialog.setCancelButton(None)
        self.curve_loading_dialog.setMinimumDuration(0)
        self.curve_loading_dialog.show()
        self.curve_load_worker = CurveHeaderLoadWorker(device, curve, self)
        self.curve_load_worker.loaded.connect(self.curve_loading_completed)
        self.curve_load_worker.failed.connect(self.curve_loading_failed)
        self.curve_load_worker.finished.connect(self.curve_loading_finished)
        self.curve_load_worker.start()

    def curve_loading_completed(self, result):
        header, points = result
        name, serial_number, data_format, limit, coefficient = header
        self.curve_name.setText(name)
        self.curve_serial.setText(serial_number)
        self.curve_format.setCurrentIndex(max(0, self.curve_format.findData(data_format)))
        self.curve_limit.setValue(limit)
        self.curve_coefficient.setCurrentIndex(max(0, self.curve_coefficient.findData(coefficient)))
        self.curve_points = {index: point for index, point in enumerate(points, start=1)}
        self.update_curve_preview()
        self.close_curve_loading_dialog()
        self.log(f"Curve header and {len(points)} points read")

    def curve_loading_failed(self, message):
        self.close_curve_loading_dialog()
        self.show_error(message)

    def curve_loading_finished(self):
        worker = self.curve_load_worker
        self.curve_load_worker = None
        if worker is not None:
            worker.deleteLater()

    def close_curve_loading_dialog(self):
        dialog = getattr(self, "curve_loading_dialog", None)
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
            self.curve_loading_dialog = None

    def write_curve_header(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        try:
            self.get_device().set_curve_header(
                self.curve_number.currentData(), self.curve_name.text(), self.curve_serial.text(),
                self.curve_format.currentData(), self.curve_limit.value(), self.curve_coefficient.currentData(),
            )
            self.log("Curve header written")
        except Exception as error:
            self.show_error(error)

    def read_curve_point(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        try:
            sensor_value, temperature = self.get_device().get_curve_point(
                self.curve_number.currentData(), self.curve_point_index.value()
            )
            self.curve_sensor_value.setValue(sensor_value)
            self.curve_temperature.setValue(temperature)
            self.curve_points[self.curve_point_index.value()] = (sensor_value, temperature)
            self.update_curve_preview()
            self.log("Curve point read")
        except Exception as error:
            self.show_error(error)

    def write_curve_point(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        try:
            self.get_device().set_curve_point(
                self.curve_number.currentData(), self.curve_point_index.value(),
                self.curve_sensor_value.value(), self.curve_temperature.value(),
            )
            self.curve_points[self.curve_point_index.value()] = (
                self.curve_sensor_value.value(), self.curve_temperature.value()
            )
            self.update_curve_preview()
            self.log("Curve point written")
        except Exception as error:
            self.show_error(error)

    def import_curve_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Curve CSV", str(Path.cwd()), "CSV Files (*.csv)")
        if not path:
            return
        points = []
        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as stream:
                for row in csv.reader(stream):
                    if len(row) < 2:
                        continue
                    try:
                        sensor_value, temperature = float(row[0]), float(row[1])
                    except ValueError:
                        continue
                    if not math.isfinite(sensor_value) or not math.isfinite(temperature) or temperature < 0:
                        raise ValueError("CSV contains a non-finite value or negative temperature.")
                    points.append((sensor_value, temperature))
            if not points:
                raise ValueError("CSV must contain sensor value and temperature columns.")
            if len(points) > 200:
                raise ValueError("A Lake Shore curve can contain at most 200 points.")
        except (OSError, ValueError) as error:
            self.show_error(error)
            return
        self.curve_points = {index: point for index, point in enumerate(points, start=1)}
        self.update_curve_preview()
        self.log(f"Imported {len(points)} curve points: {path}")

    def apply_curve_csv(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        if not self.curve_points:
            self.show_error("Import a CSV file first.")
            return
        curve = self.curve_number.currentData()
        answer = QMessageBox.question(
            self, "Apply Curve Points", f"Write {len(self.curve_points)} points to user curve {curve}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            for index, (sensor_value, temperature) in sorted(self.curve_points.items()):
                self.get_device().set_curve_point(curve, index, sensor_value, temperature)
            self.log(f"Applied {len(self.curve_points)} CSV points to user curve {curve}")
        except Exception as error:
            self.show_error(error)

    def clear_curve_preview(self):
        self.curve_points.clear()
        self.update_curve_preview()

    def update_curve_preview(self):
        points = [point for _, point in sorted(self.curve_points.items())]
        self.curve_preview.setData(
            [point[0] for point in points], [point[1] for point in points]
        )
        self.curve_point_count.setText(f"{len(points)} points loaded")

    def delete_user_curve(self):
        if self.get_device() is None:
            self.show_error("Connect the device first.")
            return
        answer = QMessageBox.question(
            self, "Delete Curve", f"Delete user curve {self.curve_number.currentData()}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.get_device().delete_curve(self.curve_number.currentData())
            self.log("User curve deleted")
        except Exception as error:
            self.show_error(error)

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
            port = self.port_input.text().strip()
            self.manager.add_device("LS331", lambda: LakeShore331(port))
            self.log("Connected")
            self._notify_main()
            self.read_device()
        except Exception as error:
            self.show_error(error)

    def disconnect_device(self):
        self.tracking_timer.stop()
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
                self.set_input_sensor_code(channel, sensor_type)
                controls["compensation"] = compensation
                controls["curve"].setCurrentIndex(max(0, controls["curve"].findData(device.get_input_curve(channel))))
                filter_enabled, filter_points = device.get_filter(channel)
                controls["filter"].setChecked(filter_enabled)
                controls["filter_points"].setValue(filter_points)
                controls["temperature"].setText(f"{device.read_temp(channel):.3f} K")
                unit = "V" if sensor_type in (0, 1, 6, 7, 8, 9) else "Ω"
                controls["reading"].setText(f"{device.read_sensor(channel):.6g} {unit}")
            for loop, controls in self.loop_controls.items():
                input_channel, units, powerup, output_display = device.get_control_setup(loop)
                control_mode = device.get_control_mode(loop)
                controls["input"].setCurrentIndex(max(0, controls["input"].findData(input_channel)))
                controls["units"].setCurrentIndex(max(0, controls["units"].findData(units)))
                controls["powerup"].setChecked(powerup)
                controls["display"].setCurrentIndex(max(0, controls["display"].findData(output_display)))
                controls["setpoint"].setValue(device.get_setpoint(loop))
                p, i, d = device.get_pid(loop)
                controls["p"].setValue(p); controls["i"].setValue(i); controls["d"].setValue(d)
                controls["pid_manual"].setValue(device.get_manual_output(loop))
                controls["preset"].setCurrentIndex(max(0, controls["preset"].findData(control_mode)))
                display_mode = 3 if control_mode == 3 else 1
                controls["mode"].setCurrentIndex(max(0, controls["mode"].findData(display_mode)))
                ramp_enabled, ramp_rate = device.get_ramp(loop)
                controls["ramp_enabled"].setChecked(ramp_enabled)
                controls["ramp_rate"].setValue(ramp_rate)
            heater_range = device.get_heater_range()
            self.loop_controls[1]["range"].setCurrentIndex(max(0, self.loop_controls[1]["range"].findData(heater_range)))
            if heater_range == 0:
                self.loop_controls[1]["mode"].setCurrentIndex(
                    max(0, self.loop_controls[1]["mode"].findData(0))
                )
            for loop in self.loop_controls:
                self.update_heater_estimate(loop)
            self.snapshot = deepcopy(self.profile_data())
            self.update_summary()
            self.log("Device settings read")
        except Exception as error:
            self.show_error(error)

    def refresh_input_tracking(self):
        """Refresh live input readings and retain the latest ten minutes."""
        device = self.get_device()
        if device is None:
            self.tracking_timer.stop()
            self.sync_connection_status()
            return
        elapsed = time.monotonic() - self.tracking_start
        try:
            state = self.manager.get_latest("LS331")
            if not state:
                self.update_realtime_status()
                return
            for channel in ("A", "B"):
                controls = self.input_controls[channel]
                temperature = state[f"{channel}_temp_K"]
                sensor_value = state[f"{channel}_sensor"]
                sensor_code = controls["sensor"].currentData()
                sensor_unit = "V" if sensor_code in (0, 1, 6, 7, 8, 9) else "Ω"
                controls["temperature"].setText(f"{temperature:.3f} K")
                controls["reading"].setText(f"{sensor_value:.6g} {sensor_unit}")

                history = self.input_history[channel]
                history["time"].append(elapsed)
                history["temperature"].append(temperature)
                history["sensor"].append(sensor_value)
                for values in history.values():
                    if len(values) > 600:
                        del values[:-600]
                controls["temperature_curve"].setData(history["time"], history["temperature"])
                controls["sensor_curve"].setData(history["time"], history["sensor"])
            self.tracking_error_active = False
            self.update_realtime_status()
        except Exception as error:
            self.tracking_timer.stop()
            self.manager.remove_device("LS331")
            self.sync_connection_status()
            self.log(f"Connection lost; changed to Disconnected: {error}")
            if self.main_window:
                self.main_window.update_device_status()

    def resume_input_tracking(self):
        if self.get_device() is not None and not self.tracking_timer.isActive():
            self.tracking_timer.start()

    def apply_settings(self):
        device = self.get_device()
        if device is None:
            self.show_error("Connect the device first.")
            return
        tracking_was_active = self.tracking_timer.isActive()
        self.tracking_timer.stop()
        try:
            temperatures = [device.read_temp(channel) for channel in ("A", "B")]
            if max(temperatures) > self.max_temperature.value():
                device.heater_off()
                raise ValueError("Safety temperature exceeded; heater forced OFF.")
            for channel, controls in self.input_controls.items():
                device.set_input_enabled(channel, True)
                sensor_code = controls["sensor"].currentData()
                curve_number = controls["curve"].currentData()
                device.set_input_type(channel, sensor_code, controls["compensation"])
                device.set_input_curve(channel, curve_number)
                device.set_filter(channel, controls["filter"].isChecked(), controls["filter_points"].value())
                applied_sensor, applied_compensation = device.get_input_type(channel)
                applied_curve = device.get_input_curve(channel)
                if (applied_sensor, applied_compensation) != (sensor_code, controls["compensation"]):
                    raise RuntimeError(
                        f"Input {channel} sensor setting was not accepted "
                        f"(requested {sensor_code}, read back {applied_sensor})."
                    )
                if applied_curve != curve_number:
                    raise RuntimeError(
                        f"Input {channel} curve setting was not accepted "
                        f"(requested {curve_number}, read back {applied_curve})."
                    )
            for loop, controls in self.loop_controls.items():
                if loop == 2 and not controls["enabled"].isChecked():
                    device.set_ramp(False, controls["ramp_rate"].value(), loop)
                    device.set_manual_output(0, loop)
                    device.set_control_mode(3, loop)
                    continue
                manual = min(controls["pid_manual"].value(), controls["output_limit"].value(), self.max_manual_output.value())
                mode = controls["mode"].currentData()
                device.set_control_setup(
                    controls["input"].currentData(), controls["units"].currentData(),
                    controls["powerup"].isChecked(), controls["display"].currentData(), loop,
                )
                device_mode = 3 if mode == 3 else controls["preset"].currentData()
                device.set_control_mode(device_mode, loop)
                device.set_setpoint(controls["setpoint"].value(), loop)
                device.set_pid(controls["p"].value(), controls["i"].value(), controls["d"].value(), loop)
                device.set_manual_output(manual, loop)
                device.set_ramp(controls["ramp_enabled"].isChecked(), controls["ramp_rate"].value(), loop)
            loop1 = self.loop_controls[1]
            heater_range = 0 if loop1["mode"].currentData() == 0 else loop1["range"].currentData()
            device.set_heater_range(heater_range)
            self.snapshot = deepcopy(self.profile_data())
            self.log("Settings applied")
        except Exception as error:
            self.show_error(error)
        finally:
            if tracking_was_active:
                QTimer.singleShot(500, self.resume_input_tracking)

    def profile_data(self):
        return {
            "port": self.port_input.text(),
            "inputs": {channel: {
                "name": c["name"].text(),
                "sensor": c["sensor"].currentText(), "sensor_code": c["sensor"].currentData(),
                "excitation": c["excitation"].text(), "curve": c["curve"].currentData(),
                "preferred_unit": c["preferred_unit"].currentText(),
                "filter": c["filter"].isChecked(), "filter_points": c["filter_points"].value(),
                "compensation": c["compensation"],
            } for channel, c in self.input_controls.items()},
            "loops": {str(loop): {
                "mode": c["mode"].currentData(), "input": c["input"].currentData(),
                "units": c["units"].currentData(), "setpoint": c["setpoint"].value(),
                "powerup": c["powerup"].isChecked(), "display": c["display"].currentData(),
                "resistance": c["resistance"].value(), "range": c["range"].currentData(),
                "manual": c["pid_manual"].value(), "output_limit": c["output_limit"].value(),
                "preset": c["preset"].currentText(), "p": c["p"].value(),
                "i": c["i"].value(), "d": c["d"].value(),
                "enabled": True if c["enabled"] is None else c["enabled"].isChecked(),
                "ramp_enabled": c["ramp_enabled"].isChecked(),
                "ramp_rate": c["ramp_rate"].value(),
            } for loop, c in self.loop_controls.items()},
            "safety": {"max_temperature": self.max_temperature.value(), "max_manual_output": self.max_manual_output.value(), "heater_off_disconnect": self.heater_off_disconnect.isChecked()},
        }

    def load_profile_data(self, data):
        self.port_input.setText(data.get("port", self.port_input.text()))
        for channel, values in data.get("inputs", {}).items():
            controls = self.input_controls[channel]
            controls["name"].setText(values.get("name", f"Input {channel}"))
            sensor_code = values.get("sensor_code", 0)
            self.set_input_sensor_code(channel, sensor_code)
            controls["curve"].setCurrentIndex(max(0, controls["curve"].findData(values.get("curve", 0))))
            controls["preferred_unit"].setCurrentText(values.get("preferred_unit", "K"))
            controls["filter"].setChecked(values.get("filter", False))
            controls["filter_points"].setValue(values.get("filter_points", 8))
            controls["compensation"] = values.get("compensation", False)
        for loop_text, values in data.get("loops", {}).items():
            controls = self.loop_controls[int(loop_text)]
            for key, default in (("setpoint", 300), ("p", 10), ("i", 20), ("d", 0)):
                controls[key].setValue(values.get(key, default))
            controls["mode"].setCurrentIndex(max(0, controls["mode"].findData(values.get("mode", 1))))
            controls["input"].setCurrentIndex(max(0, controls["input"].findData(values.get("input", "A"))))
            controls["units"].setCurrentIndex(max(0, controls["units"].findData(values.get("units", 1))))
            controls["powerup"].setChecked(values.get("powerup", False))
            controls["display"].setCurrentIndex(max(0, controls["display"].findData(values.get("display", 1))))
            controls["resistance"].setValue(values.get("resistance", 50))
            controls["range"].setCurrentIndex(max(0, controls["range"].findData(values.get("range", 0))))
            controls["pid_manual"].setValue(values.get("manual", 0))
            controls["output_limit"].setValue(values.get("output_limit", 80))
            controls["preset"].setCurrentText(values.get("preset", "Manual PID"))
            if controls["enabled"] is not None:
                controls["enabled"].setChecked(values.get("enabled", True))
            controls["ramp_enabled"].setChecked(values.get("ramp_enabled", False))
            controls["ramp_rate"].setValue(values.get("ramp_rate", 1.0))
            self.update_heater_estimate(int(loop_text))
        ramp = data.get("ramp", {})
        if ramp:
            legacy_loop = int(ramp.get("loop", 1))
            self.loop_controls[legacy_loop]["ramp_enabled"].setChecked(ramp.get("enabled", False))
            self.loop_controls[legacy_loop]["ramp_rate"].setValue(ramp.get("rate", 1.0))
        safety = data.get("safety", {})
        self.max_temperature.setValue(safety.get("max_temperature", 400))
        self.max_manual_output.setValue(safety.get("max_manual_output", 80))
        self.heater_off_disconnect.setChecked(safety.get("heater_off_disconnect", True))

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
                f"Sensor: {controls['sensor'].currentText()} | "
                f"Curve: {controls['curve'].currentText()} | "
                f"Filter: {'Enabled' if controls['filter'].isChecked() else 'Disabled'} | "
                f"Reading: {controls['temperature'].text()} / {controls['reading'].text()}"
            )
        for number, controls in self.loop_controls.items():
            loop_active = controls["enabled"] is None or controls["enabled"].isChecked()
            ramp_active = loop_active and controls["ramp_enabled"].isChecked()
            mode = controls["mode"].currentText() if loop_active else "Disabled"
            self.summary_labels[f"loop_{number}"].setText(
                f"Mode: {mode} | Input: {controls['input'].currentText()} | "
                f"Setpoint: {controls['setpoint'].value():.3f} {controls['units'].currentText()} | "
                f"Ramp: {'Enabled' if ramp_active else 'Disabled'} ({controls['ramp_rate'].value():g} K/min) | "
                f"PID: {controls['p'].value():g}, {controls['i'].value():g}, {controls['d'].value():g} | "
                f"Tune: {controls['tune_status'].text()}"
            )
        self.summary_labels["safety"].setText(f"Max temperature: {self.max_temperature.value():g} K  |  Max output: {self.max_manual_output.value():g} %")

    def sync_connection_status(self):
        connected = self.get_device() is not None
        self.status_label.setText("● Connected" if connected else "● Disconnected")
        self.status_label.setStyleSheet(f"color:{'#2ecc71' if connected else '#e74c3c'}; font-weight:bold;")
        if connected and not self.tracking_timer.isActive():
            self.tracking_start = time.monotonic()
            self.tracking_timer.start()
            self.refresh_input_tracking()
        elif not connected:
            self.tracking_timer.stop()
        self.update_realtime_status()

    def update_realtime_status(self):
        metrics = self.manager.get_metrics("LS331")
        response = metrics["response_ms"]
        self.response_label.setText("Response: -" if response is None else f"Response: {response:.1f} ms")

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
