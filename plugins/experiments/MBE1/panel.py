"""MBE chamber monitor panel.

The panel deliberately only renders snapshots supplied by DeviceManager.  It
does not poll camera or heating hardware from the GUI thread.
"""

from datetime import datetime

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.widget_busy_spinner import run_busy_task


class ExperimentPanel(QWidget):
    """Theme-neutral MBE monitoring and heating-control panel."""

    SNAPSHOT_INTERVAL_MS = 750

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._setpoint_task_running = False
        self._sequence_task_running = False
        self._last_sample_ids = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("MBE chamber monitor")
        title.setProperty("heading", True)
        self.connection_status = QLabel("Waiting for device snapshots")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.connection_status)
        root.addLayout(header)

        cameras = QGridLayout()
        cameras.addWidget(self._create_camera_group("Chamber camera", "camera"), 0, 0)
        cameras.addWidget(self._create_camera_group("Pyrometer camera", "pyrometer_camera"), 0, 1)
        root.addLayout(cameras)

        heating = QGroupBox("Heating control")
        heating_form = QFormLayout(heating)
        self.temperature_value = QLabel("— °C")
        self.temperature_meta = QLabel("No temperature sample")
        self.setpoint_value = QLabel("— °C")
        self.setpoint_input = QDoubleSpinBox()
        self.setpoint_input.setRange(0.0, 2000.0)
        self.setpoint_input.setDecimals(1)
        self.setpoint_input.setSingleStep(1.0)
        self.setpoint_input.setSuffix(" °C")
        self.apply_button = QPushButton("Apply setpoint")
        self.apply_button.clicked.connect(self._apply_setpoint)
        control = QWidget()
        control_layout = QHBoxLayout(control)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.addWidget(self.setpoint_input)
        control_layout.addWidget(self.apply_button)
        heating_form.addRow("Temperature", self.temperature_value)
        heating_form.addRow("Sample", self.temperature_meta)
        heating_form.addRow("Reported setpoint", self.setpoint_value)
        heating_form.addRow("New setpoint", control)
        root.addWidget(heating)
        root.addStretch()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_snapshots)
        self._refresh_timer.start(self.SNAPSHOT_INTERVAL_MS)
        self._refresh_snapshots()

    def _create_camera_group(self, title, resource):
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        image = QLabel("No frame available")
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setMinimumHeight(180)
        image.setProperty("cameraResource", resource)
        meta = QLabel("Waiting for snapshot")
        layout.addWidget(image)
        layout.addWidget(meta)
        setattr(self, f"{resource}_image", image)
        setattr(self, f"{resource}_meta", meta)
        return group

    def _device_manager(self):
        return getattr(self.manager, "device_manager", self.manager)

    def _snapshot_for(self, resource):
        """Return the latest DeviceManager snapshot, without touching hardware."""
        device_manager = self._device_manager()
        for name in ("get_snapshot", "snapshot", "latest_snapshot"):
            reader = getattr(device_manager, name, None)
            if callable(reader):
                try:
                    return reader(resource)
                except (KeyError, LookupError, TypeError):
                    continue
        return None

    @staticmethod
    def _field(snapshot, *names, default=None):
        if snapshot is None:
            return default
        if isinstance(snapshot, dict):
            for name in names:
                if name in snapshot:
                    return snapshot[name]
            return default
        for name in names:
            if hasattr(snapshot, name):
                return getattr(snapshot, name)
        return default

    def _sample_text(self, resource, snapshot):
        sample_id = self._field(snapshot, "sample_id", "id", "sequence", default="—")
        timestamp = self._field(snapshot, "timestamp", "captured_at", "time")
        freshness = self._field(snapshot, "freshness", "is_fresh", "age_ms")
        if isinstance(timestamp, datetime):
            timestamp = timestamp.strftime("%H:%M:%S")
        parts = [f"ID: {sample_id}"]
        if timestamp is not None:
            parts.append(f"Time: {timestamp}")
        if freshness is not None:
            parts.append(f"Fresh: {freshness}")
        self._last_sample_ids[resource] = sample_id
        return " · ".join(parts)

    def _refresh_camera(self, resource):
        snapshot = self._snapshot_for(resource)
        if snapshot is None:
            return False
        image_label = getattr(self, f"{resource}_image")
        frame = self._field(snapshot, "frame", "image", "qimage", "pixmap")
        if isinstance(frame, QPixmap):
            pixmap = frame
        elif isinstance(frame, QImage):
            pixmap = QPixmap.fromImage(frame)
        else:
            pixmap = None
        if pixmap is not None and not pixmap.isNull():
            image_label.setPixmap(pixmap.scaled(
                image_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        getattr(self, f"{resource}_meta").setText(self._sample_text(resource, snapshot))
        return True

    def _refresh_snapshots(self):
        camera_seen = self._refresh_camera("camera")
        pyrometer_seen = self._refresh_camera("pyrometer_camera")
        heating = self._snapshot_for("heating_control")
        if heating is not None:
            temperature = self._field(heating, "temperature", "temperature_c", "value")
            setpoint = self._field(heating, "setpoint", "setpoint_c", "target")
            if temperature is not None:
                self.temperature_value.setText(f"{float(temperature):.1f} °C")
            if setpoint is not None:
                self.setpoint_value.setText(f"{float(setpoint):.1f} °C")
                if not self.setpoint_input.hasFocus():
                    self.setpoint_input.setValue(float(setpoint))
            self.temperature_meta.setText(self._sample_text("heating_control", heating))
        if camera_seen or pyrometer_seen or heating is not None:
            self.connection_status.setText("Receiving DeviceManager snapshots")

    def _set_heating_setpoint(self, value):
        """Worker-side control operation; never called directly by the GUI."""
        device_manager = self._device_manager()
        for accessor in ("get_device", "device", "get_resource"):
            getter = getattr(device_manager, accessor, None)
            if callable(getter):
                try:
                    heating = getter("heating_control")
                    break
                except (KeyError, LookupError, TypeError):
                    heating = None
            else:
                heating = None
        else:
            heating = getattr(device_manager, "heating_control", None)
        if heating is None:
            raise RuntimeError("Heating control device is not available")
        for method_name in ("set_setpoint", "set_temperature_setpoint", "set_target"):
            method = getattr(heating, method_name, None)
            if callable(method):
                method(value)
                return value
        raise RuntimeError("Heating control device does not provide a setpoint command")

    def _apply_setpoint(self):
        if self._setpoint_task_running:
            return
        self._setpoint_task_running = True
        self.apply_button.setEnabled(False)
        value = self.setpoint_input.value()

        def success(_result):
            self._setpoint_task_running = False
            self.apply_button.setEnabled(True)
            self.connection_status.setText(f"Setpoint requested: {value:.1f} °C")

        def failure(error):
            self._setpoint_task_running = False
            self.apply_button.setEnabled(True)
            self.connection_status.setText(f"Setpoint failed: {error}")

        run_busy_task(self, lambda: self._set_heating_setpoint(value), success, failure,
                      key="mbe_heating_setpoint")

    def execute_sequence_command(self, command, value):
        if command != "set_temperature_setpoint":
            raise ValueError(f"Unsupported command: {command}")
        if self._sequence_task_running:
            return False
        self._sequence_task_running = True

        def complete(_result):
            self._sequence_task_running = False

        def failed(_error):
            # Completion allows the sequence engine to proceed to its normal
            # error reporting path without leaving a worker task outstanding.
            self._sequence_task_running = False

        run_busy_task(
            self, lambda: self._set_heating_setpoint(float(value)), complete, failed,
            key="mbe_sequence_setpoint",
        )
        return False

    def is_sequence_command_complete(self, command, value):
        return command == "set_temperature_setpoint" and not self._sequence_task_running

    def cancel_sequence_command(self):
        # There is no local blocking command to cancel; the device remains in a safe state.
        return None

    def shutdown(self):
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        self._setpoint_task_running = False
        self._sequence_task_running = False
