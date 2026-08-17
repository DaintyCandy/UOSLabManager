from collections import deque

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QSplitter, QTabWidget, QVBoxLayout,
    QWidget,
)


class LineProfilePanel(QWidget):
    """Analyze horizontal intensity profiles without owning the camera."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.host = parent
        self.settings = QSettings("UOSLabManager", "UOSLabManager")
        self.profiles = deque(maxlen=max(
            10, int(self.settings.value("line_profile/buffer_rows", 2000))
        ))
        self.play_index = 0
        self.last_frame_identity = None
        self._build_ui()
        self.capture_timer = QTimer(self)
        self.capture_timer.timeout.connect(self.capture_profile)
        self.capture_timer.start(self.interval_spin.value())
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.advance_animation)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.addItems(["Camera 1", "Camera 2"])
        controls.addWidget(QLabel("Source"))
        controls.addWidget(self.camera_combo)

        self.roi_center = QSpinBox()
        self.roi_center.setRange(0, 100)
        self.roi_center.setValue(50)
        self.roi_center.setSuffix(" %")
        controls.addWidget(QLabel("ROI center"))
        controls.addWidget(self.roi_center)
        self.roi_height = QSpinBox()
        self.roi_height.setRange(1, 100)
        self.roi_height.setValue(10)
        self.roi_height.setSuffix(" %")
        controls.addWidget(QLabel("ROI height"))
        controls.addWidget(self.roi_height)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(50, 60_000)
        self.interval_spin.setValue(250)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.valueChanged.connect(self.set_capture_interval)
        controls.addWidget(QLabel("Capture"))
        controls.addWidget(self.interval_spin)
        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(10, 100_000)
        self.buffer_spin.setValue(self.profiles.maxlen)
        self.buffer_spin.valueChanged.connect(self.set_buffer_rows)
        controls.addWidget(QLabel("Buffer"))
        controls.addWidget(self.buffer_spin)
        controls.addStretch()
        layout.addLayout(controls)

        buttons = QHBoxLayout()
        for text, callback in (
            ("Load NPY", self.load_npy), ("Save NPY", self.save_npy),
            ("Play", self.toggle_animation), ("Clear", self.clear),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            if text == "Play":
                self.play_button = button
        self.status = QLabel("Waiting for camera frames")
        buttons.addWidget(self.status, 1)
        layout.addLayout(buttons)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.camera_preview = QLabel("Start preview in the Camera tab")
        self.camera_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_preview.setMinimumWidth(360)
        self.camera_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.camera_preview.setStyleSheet(
            "background:#000; color:#888; border:1px solid #555;"
        )
        splitter.addWidget(self.camera_preview)

        tabs = QTabWidget()
        self.profile_plot = pg.PlotWidget()
        self.profile_plot.setLabel("bottom", "X pixel")
        self.profile_plot.setLabel("left", "Intensity")
        self.profile_curve = self.profile_plot.plot(pen=pg.mkPen("#42d392", width=2))
        tabs.addTab(self.profile_plot, "Profile / Animation")

        self.kymograph = pg.ImageView()
        self.kymograph.ui.roiBtn.hide()
        self.kymograph.ui.menuBtn.hide()
        tabs.addTab(self.kymograph, "Kymograph")
        splitter.addWidget(tabs)
        splitter.setSizes([500, 700])
        layout.addWidget(splitter, 1)

    def _camera_workspace(self):
        return getattr(self.host, "camera_panel", None)

    def capture_profile(self):
        workspace = self._camera_workspace()
        if workspace is None:
            self.status.setText("Camera workspace is unavailable")
            return
        frame, sequence = workspace.get_frame_packet(
            self.camera_combo.currentIndex()
        )
        if frame is None:
            self.status.setText("Start the selected camera preview")
            self.camera_preview.setText("Preview is stopped")
            return
        source_key = (self.camera_combo.currentIndex(), sequence)
        if source_key == self.last_frame_identity:
            return
        self.last_frame_identity = source_key
        height = frame.shape[0]
        center = round(height * self.roi_center.value() / 100)
        roi_height = max(1, round(height * self.roi_height.value() / 100))
        top = max(0, center - roi_height // 2)
        bottom = min(height, top + roi_height)
        self._show_frame(frame, top, bottom)
        roi = np.asarray(frame[top:bottom])
        if roi.ndim == 3:
            roi = (
                roi[..., 0] * 0.114 + roi[..., 1] * 0.587
                + roi[..., 2] * 0.299
            )
        profile = np.mean(roi, axis=0).astype(float, copy=False)
        self.profiles.append(profile.copy())
        self.profile_curve.setData(profile)
        self._update_kymograph()
        self.status.setText(
            f"{len(self.profiles)}/{self.profiles.maxlen} profiles, {len(profile)} px"
        )

    def _show_frame(self, frame, top, bottom):
        rgb = np.asarray(frame)[..., ::-1].copy()
        rgb[max(0, top):min(len(rgb), top + 2), :, :] = (0, 255, 0)
        rgb[max(0, bottom - 2):min(len(rgb), bottom), :, :] = (0, 255, 0)
        height, width = rgb.shape[:2]
        image = QImage(
            rgb.data, width, height, width * 3, QImage.Format.Format_RGB888
        ).copy()
        self.camera_preview.setPixmap(QPixmap.fromImage(image).scaled(
            self.camera_preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def _matrix(self):
        if not self.profiles:
            return None
        width = len(self.profiles[-1])
        compatible = [profile for profile in self.profiles if len(profile) == width]
        return np.asarray(compatible) if compatible else None

    def _update_kymograph(self):
        matrix = self._matrix()
        if matrix is not None:
            self.kymograph.setImage(matrix.T, autoRange=False, autoLevels=True)

    def toggle_animation(self):
        if self.animation_timer.isActive():
            self.animation_timer.stop()
            self.play_button.setText("Play")
            return
        if not self.profiles:
            return
        self.play_index = 0
        self.animation_timer.start(max(20, self.interval_spin.value()))
        self.play_button.setText("Pause")

    def advance_animation(self):
        if not self.profiles:
            self.toggle_animation()
            return
        profiles = list(self.profiles)
        self.profile_curve.setData(profiles[self.play_index % len(profiles)])
        self.play_index = (self.play_index + 1) % len(profiles)

    def load_npy(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load profiles", "", "NumPy (*.npy)")
        if not path:
            return
        try:
            data = np.load(path, allow_pickle=False)
            if data.ndim != 2 or not np.issubdtype(data.dtype, np.number):
                raise ValueError("Expected a numeric samples-by-pixels 2D array")
            self.profiles = deque(
                (np.asarray(row, dtype=float) for row in data[-self.buffer_spin.value():]),
                maxlen=self.buffer_spin.value(),
            )
            self.profile_curve.setData(self.profiles[-1])
            self._update_kymograph()
            self.status.setText(f"Loaded {len(self.profiles)} profiles")
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Line Profile", str(error))

    def save_npy(self):
        matrix = self._matrix()
        if matrix is None:
            QMessageBox.information(self, "Line Profile", "No profiles to save.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save profiles", "line_profiles.npy", "NumPy (*.npy)")
        if path:
            if not path.lower().endswith(".npy"):
                path += ".npy"
            np.save(path, matrix)

    def set_capture_interval(self, interval_ms):
        if hasattr(self, "capture_timer"):
            self.capture_timer.setInterval(int(interval_ms))

    def set_buffer_rows(self, rows):
        rows = max(10, int(rows))
        self.profiles = deque(self.profiles, maxlen=rows)
        self.settings.setValue("line_profile/buffer_rows", rows)
        self._update_kymograph()

    def clear(self):
        self.profiles.clear()
        self.profile_curve.clear()
        self.kymograph.clear()
        self.status.setText("Cleared")

    def shutdown(self):
        self.capture_timer.stop()
        self.animation_timer.stop()
