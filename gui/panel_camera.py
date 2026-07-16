import os
import time
import numpy as np  # <-- NumPy 추가
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QSizePolicy, QSplitter,
    QStackedLayout, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from .widget_busy_spinner import BusySpinner

try:
    import cv2
except ImportError:
    cv2 = None


class CameraWorker(QThread):
    frame_ready = pyqtSignal(object)
    camera_error = pyqtSignal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source

    def run(self):
        capture = cv2.VideoCapture(self.source)
        if not capture.isOpened():
            capture.release()
            self.camera_error.emit(f"Cannot open camera source: {self.source}")
            return
        try:
            while not self.isInterruptionRequested():
                ok, frame = capture.read()
                if not ok:
                    self.camera_error.emit("Camera frame read failed")
                    return
                self.frame_ready.emit(frame)
        finally:
            capture.release()


class CameraPanel(QWidget):
    def __init__(self, output_dir, log_callback, default_source="0", title="Camera 1"):
        super().__init__()
        self.output_dir = output_dir
        self.log = log_callback
        self.default_source = default_source
        self.title = title
        self.camera_worker = None
        self.writer = None
        self.recording_armed = False
        self.recording = False
        self.recording_paused = False
        self.video_path = ""
        self.last_frame_at = None
        self.last_recorded_at = None
        self.preview_fps = None
        self.preview_active = False
        
        # --- [RHEED 1D 추출용 변수] ---
        self.latest_profile = None 

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox(f"{self.title} / Recording")
        body = QVBoxLayout(group)
        
        # 1. 상단 소스 및 FPS
        options = QHBoxLayout()
        options.addWidget(QLabel("Source:"))
        self.source_input = QLineEdit(self.default_source)
        self.source_input.setFixedWidth(50)
        options.addWidget(self.source_input)
        options.addStretch()
        self.set_fps_checkbox = QCheckBox("Set FPS:")
        self.set_fps_checkbox.setChecked(True)
        self.set_fps_checkbox.setToolTip(
            "Enable to record at the selected FPS. Disable to record every received frame."
        )
        self.set_fps_checkbox.toggled.connect(self.update_recording_mode_controls)
        options.addWidget(self.set_fps_checkbox)
        self.fps_input = QDoubleSpinBox()
        self.fps_input.setRange(1.0, 60.0)
        self.fps_input.setDecimals(1)
        self.fps_input.setValue(30.0)
        self.fps_input.setToolTip("Lower values save fewer frames and reduce video file size.")
        options.addWidget(self.fps_input)
        self.frame_status_label = QLabel("Frame: -")
        options.addWidget(self.frame_status_label)
        self.recording_indicator = QLabel("● RECORDING")
        self.recording_indicator.setStyleSheet(
            "color:#ff3b30; background:rgba(120, 0, 0, 90); "
            "font-size:12pt; font-weight:900; padding:5px 10px; border-radius:5px;"
        )
        self.recording_indicator.setVisible(False)
        options.addWidget(self.recording_indicator)
        body.addLayout(options)
        self.preview_container = QWidget()
        self.preview_container.setMinimumSize(320, 200)
        self.preview_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview_stack = QStackedLayout(self.preview_container)
        self.preview_stack.setContentsMargins(0, 0, 0, 0)
        
        # --- [추가] 2. RHEED ROI(관심영역) 설정 UI ---
        roi_layout = QHBoxLayout()
        roi_layout.addWidget(QLabel("ROI Center Y(%):"))
        self.roi_y_spin = QDoubleSpinBox()
        self.roi_y_spin.setRange(0, 100)
        self.roi_y_spin.setValue(50.0) # 기본 화면 정중앙
        roi_layout.addWidget(self.roi_y_spin)
        
        roi_layout.addWidget(QLabel("ROI Height(%):"))
        self.roi_h_spin = QDoubleSpinBox()
        self.roi_h_spin.setRange(1, 100)
        self.roi_h_spin.setValue(10.0) # 화면 높이의 10% 두께
        roi_layout.addWidget(self.roi_h_spin)
        roi_layout.addStretch()
        body.addLayout(roi_layout)
        # ----------------------------------------

        # 3. 프리뷰 화면
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background:#000; color:#777; border:2px inset #555;")
        self.set_standby_preview()
        self.preview_stack.addWidget(self.preview)
        self.loading_page = QWidget()
        self.loading_page.setStyleSheet("background:#000; color:#ddd; border:2px inset #555;")
        loading_layout = QVBoxLayout(self.loading_page)
        loading_layout.addStretch()
        loading_layout.addWidget(BusySpinner(self.loading_page), alignment=Qt.AlignmentFlag.AlignCenter)
        loading_layout.addStretch()
        self.preview_stack.addWidget(self.loading_page)
        self.preview_stack.setCurrentWidget(self.preview)
        body.addWidget(self.preview_container, 1)
        recording_controls = QHBoxLayout()
        recording_controls.addStretch()
        self.preview_switch = QToolButton()
        self.preview_switch.setText("Preview OFF")
        self.preview_switch.setCheckable(True)
        self.preview_switch.setFixedSize(110, 34)
        self.preview_switch.setStyleSheet(
            "QToolButton { border:1px solid #777; border-radius:17px; font-weight:bold; }"
            "QToolButton:checked { background:#2e7d32; color:white; border-color:#66bb6a; }"
        )
        self.preview_switch.toggled.connect(self.toggle_preview)
        recording_controls.addWidget(self.preview_switch)

        self.record_button = QToolButton()
        self.record_button.setText("●")
        self.record_button.setToolTip("Start Recording")
        self.record_button.setFixedSize(42, 34)
        self.record_button.setStyleSheet("font-size:16pt; font-weight:bold; color:#ef5350;")
        self.record_button.clicked.connect(self.start_recording)
        recording_controls.addWidget(self.record_button)

        self.play_pause_button = QToolButton()
        self.play_pause_button.setText("▶")
        self.play_pause_button.setToolTip("Resume Recording")
        self.play_pause_button.setFixedSize(42, 34)
        self.play_pause_button.setStyleSheet("font-size:16pt; font-weight:bold;")
        self.play_pause_button.setEnabled(False)
        self.play_pause_button.clicked.connect(self.toggle_recording_pause)
        recording_controls.addWidget(self.play_pause_button)

        self.stop_record_button = QToolButton()
        self.stop_record_button.setText("■")
        self.stop_record_button.setToolTip("Stop Recording")
        self.stop_record_button.setFixedSize(42, 34)
        self.stop_record_button.setStyleSheet("font-size:16pt; font-weight:bold;")
        self.stop_record_button.setEnabled(False)
        self.stop_record_button.clicked.connect(self.stop_recording)
        recording_controls.addWidget(self.stop_record_button)
        recording_controls.addStretch()
        body.addLayout(recording_controls)
        layout.addWidget(group, 1)

    def set_standby_preview(self):
        camera_number = self.title.rsplit(" ", 1)[-1]
        self.preview.setText(
            "<div style='text-align:center;'>"
            f"<span style='font-size:84pt; font-weight:800; color:#555;'>{camera_number}</span>"
            "<br><span style='font-size:14pt; color:#777;'>CAMERA STANDBY</span>"
            "</div>"
        )

    def update_recording_mode_controls(self, _checked=False):
        self.fps_input.setEnabled(self.set_fps_checkbox.isChecked() and not self.recording_armed)

    def set_preview_switch(self, enabled):
        self.preview_switch.blockSignals(True)
        self.preview_switch.setChecked(enabled)
        self.preview_switch.setText("Preview ON" if enabled else "Preview OFF")
        self.preview_switch.blockSignals(False)

    def toggle_preview(self, enabled):
        self.preview_switch.setText("Preview ON" if enabled else "Preview OFF")
        if enabled:
            if not self.start_preview():
                self.set_preview_switch(False)
        else:
            self.stop_preview()

    def source(self):
        value = self.source_input.text().strip()
        return int(value) if value.isdigit() else value

    def start_preview(self):
        if cv2 is None:
            QMessageBox.critical(self, "Camera Error", "OpenCV is not installed.")
            return False
        if self.camera_worker is not None and self.camera_worker.isRunning():
            self.preview_active = True
            self.set_preview_switch(True)
            return True
        self.camera_worker = CameraWorker(self.source(), self)
        self.camera_worker.frame_ready.connect(self.update_frame)
        self.camera_worker.camera_error.connect(self.handle_camera_error)
        self.camera_worker.finished.connect(self.camera_worker_finished)
        self.preview_stack.setCurrentWidget(self.loading_page)
        self.preview_fps = None
        self.preview_active = True
        self.camera_worker.start()
        self.set_preview_switch(True)
        self.log(f"Camera preview started: {self.source()}")
        return True

    def stop_preview(self):
        self.preview_active = False
        self.set_preview_switch(False)
        self.stop_recording()
        if self.camera_worker is not None:
            worker = self.camera_worker
            worker.requestInterruption()
            if worker.wait(1500) and self.camera_worker is worker:
                self.camera_worker = None
        self.last_frame_at = None
        self.preview_fps = None
        self.frame_status_label.setText("Frame: -")
        self.latest_profile = None # 끄면 프로파일도 초기화
        self.preview.clear()
        self.set_standby_preview()
        self.preview_stack.setCurrentWidget(self.preview)

    def handle_camera_error(self, message):
        self.log(message)
        self.preview_active = False
        self.set_preview_switch(False)
        self.stop_recording()
        self.preview.clear()
        self.set_standby_preview()
        self.preview_stack.setCurrentWidget(self.preview)

    def camera_worker_finished(self):
        worker = self.sender()
        was_active = self.preview_active
        self.preview_active = False
        if self.camera_worker is worker:
            self.camera_worker = None
        if self.preview_switch.isChecked() or was_active:
            self.set_preview_switch(False)
            self.stop_recording()
            self.last_frame_at = None
            self.preview_fps = None
            self.frame_status_label.setText("Frame: -")
            self.latest_profile = None
            self.preview.clear()
            self.set_standby_preview()
            self.preview_stack.setCurrentWidget(self.preview)

    def arm_recording(self):
        if self.recording_armed:
            return True
        if not self.start_preview():
            return False
        os.makedirs(self.output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        source_name = str(self.source()).replace(":", "_").replace("/", "_").replace("\\", "_")
        self.video_path = os.path.join(self.output_dir, f"camera_{source_name}_{stamp}.mp4")
        self.recording_armed = True
        self.recording = False
        self.recording_paused = False
        self.last_recorded_at = None
        self.fps_input.setEnabled(False)
        self.set_fps_checkbox.setEnabled(False)
        self.recording_indicator.setVisible(True)
        self.recording_indicator.setText("● ARMED")
        self.recording_indicator.setStyleSheet(
            "color:#ffb74d; background:rgba(100, 60, 0, 100); "
            "font-size:12pt; font-weight:900; padding:5px 10px; border-radius:5px;"
        )
        self.log(f"Camera recording armed: {self.video_path}")
        return True

    def start_recording(self):
        was_paused = self.recording_paused
        if not self.recording_armed and not self.arm_recording():
            return
        self.recording = True
        self.recording_paused = False
        self.last_recorded_at = None
        self.recording_indicator.setVisible(True)
        self.recording_indicator.setText("● RECORDING")
        self.recording_indicator.setStyleSheet(
            "color:#ff3b30; background:rgba(120, 0, 0, 90); "
            "font-size:12pt; font-weight:900; padding:5px 10px; border-radius:5px;"
        )
        self.record_button.setEnabled(False)
        self.play_pause_button.setEnabled(True)
        self.play_pause_button.setText("⏸")
        self.play_pause_button.setToolTip("Pause Recording")
        self.stop_record_button.setEnabled(True)
        self.log("Camera recording resumed" if was_paused else "Camera recording started")

    def toggle_recording_pause(self):
        if self.recording:
            self.pause_recording()
        elif self.recording_paused:
            self.start_recording()

    def pause_recording(self):
        if not self.recording_armed or not self.recording:
            return
        self.recording = False
        self.recording_paused = True
        self.recording_indicator.setText("⏸ PAUSED")
        self.recording_indicator.setStyleSheet(
            "color:#ffb74d; background:rgba(100, 60, 0, 100); "
            "font-size:12pt; font-weight:900; padding:5px 10px; border-radius:5px;"
        )
        self.play_pause_button.setText("▶")
        self.play_pause_button.setToolTip("Resume Recording")
        self.log("Camera recording paused")

    def stop_recording(self):
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        if self.recording_armed:
            self.recording_armed = False
            self.recording = False
            self.recording_paused = False
            self.last_recorded_at = None
            self.set_fps_checkbox.setEnabled(True)
            self.update_recording_mode_controls()
            self.recording_indicator.setVisible(False)
            self.record_button.setEnabled(True)
            self.play_pause_button.setText("▶")
            self.play_pause_button.setToolTip("Resume Recording")
            self.play_pause_button.setEnabled(False)
            self.stop_record_button.setEnabled(False)
            self.log(f"Camera recording saved: {self.video_path}")

    def update_frame(self, frame):
        if not self.preview_active:
            return
        self.preview_stack.setCurrentWidget(self.preview)
        now = time.perf_counter()
        if self.last_frame_at is not None:
            frame_ms = (now - self.last_frame_at) * 1000.0
            fps = 1000.0 / frame_ms if frame_ms > 0 else 0.0
            if 1.0 <= fps <= 240.0:
                self.preview_fps = fps if self.preview_fps is None else (
                    self.preview_fps * 0.9 + fps * 0.1
                )
            self.frame_status_label.setText(f"Frame: {frame_ms:.1f} ms ({fps:.1f} FPS)")
        self.last_frame_at = now
        if self.recording:
            if self.set_fps_checkbox.isChecked():
                recording_interval = 1.0 / self.fps_input.value()
                if self.last_recorded_at is None or now - self.last_recorded_at >= recording_interval:
                    self.write_frame(frame)
                    self.last_recorded_at = now
            else:
                self.write_frame(frame)
                self.last_recorded_at = now
            
        # --- [추가] RHEED 1D 프로파일 추출 (Vertical Projection) ---
        height, width = frame.shape[:2]
        center_pct = self.roi_y_spin.value() / 100.0
        height_pct = self.roi_h_spin.value() / 100.0
        
        y_center = int(height * center_pct)
        h_pixels = int(height * height_pct)
        
        y1 = max(0, y_center - h_pixels // 2)
        y2 = min(height, y_center + h_pixels // 2)

        # 흑백으로 변환 후 해당 영역(ROI)을 세로(axis=0)로 평균 냄
        if y2 > y1:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            roi = gray[y1:y2, :]
            self.latest_profile = np.mean(roi, axis=0) # 1D Array 생성!
        else:
            self.latest_profile = None

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # 추출 영역을 녹색 박스로 렌더링 (사용자 시각적 확인용)
        cv2.rectangle(rgb, (0, y1), (width - 1, y2), (0, 255, 0), 2)
        # --------------------------------------------------------

        bytes_per_line = 3 * width
        image = QImage(rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

    def write_frame(self, frame):
        if self.writer is None:
            height, width = frame.shape[:2]
            codec = cv2.VideoWriter_fourcc(*"mp4v")
            output_fps = (
                self.fps_input.value()
                if self.set_fps_checkbox.isChecked()
                else max(1.0, min(120.0, self.preview_fps or 30.0))
            )
            self.writer = cv2.VideoWriter(self.video_path, codec, output_fps, (width, height))
            if not self.writer.isOpened():
                QMessageBox.critical(self, "Camera Error", "Cannot create camera video file.")
                self.stop_recording()
                return
        self.writer.write(frame)

    def get_latest_profile(self):
        return self.latest_profile


class CameraWorkspace(QWidget):
    """One or two independently controlled camera panels."""

    def __init__(self, output_dir, log_callback):
        super().__init__()
        self.output_dir = output_dir
        self.external_log = log_callback
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addStretch()
        self.split_button = QToolButton()
        self.split_button.setText("◫")
        self.split_button.setToolTip("Split camera view")
        self.split_button.setCheckable(True)
        self.split_button.setFixedSize(36, 30)
        self.split_button.setStyleSheet("font-size:17pt; font-weight:bold;")
        self.split_button.toggled.connect(self.set_split_view)
        controls.addWidget(self.split_button)
        layout.addLayout(controls)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(0)
        self.splitter.setChildrenCollapsible(False)
        self.primary = CameraPanel(output_dir, self.camera_log, "0", "Camera 1")
        self.secondary = CameraPanel(output_dir, self.camera_log, "1", "Camera 2")
        self.splitter.addWidget(self.primary)
        self.splitter.addWidget(self.secondary)
        self.splitter.handle(1).setEnabled(False)
        self.secondary.setVisible(False)
        layout.addWidget(self.splitter, 1)
        log_group = QGroupBox("Camera Log")
        log_group.setMinimumHeight(140)
        log_group.setMaximumHeight(190)
        log_layout = QVBoxLayout(log_group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        log_layout.addWidget(self.log_box)
        layout.addWidget(log_group)

    def camera_log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{stamp}] {message}")
        self.external_log(message)

    def set_output_dir(self, path):
        """Apply the shared recording folder to every camera panel."""
        if not path:
            return
        self.output_dir = path
        self.primary.output_dir = path
        self.secondary.output_dir = path
        self.camera_log(f"Camera save folder changed: {path}")

    def set_split_view(self, enabled):
        minimum_width = 440 if enabled else 0
        self.primary.setMinimumWidth(minimum_width)
        self.secondary.setMinimumWidth(minimum_width)
        self.secondary.setVisible(enabled)
        self.split_button.setText("▣" if enabled else "◫")
        self.split_button.setToolTip("Merge camera view" if enabled else "Split camera view")
        if enabled:
            self.splitter.setSizes([1, 1])

    def stop_preview(self):
        self.primary.stop_preview()
        self.secondary.stop_preview()
        
    # 데이터 로거가 프로파일을 가져갈 수 있게 하는 함수
    def get_latest_profile(self):
        return self.primary.get_latest_profile()
