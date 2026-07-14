import os
import numpy as np  # <-- NumPy 추가
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

try:
    import cv2
except ImportError:
    cv2 = None

class CameraPanel(QWidget):
    def __init__(self, output_dir, log_callback):
        super().__init__()
        self.output_dir = output_dir
        self.log = log_callback
        self.capture = None
        self.writer = None
        self.recording = False
        self.video_path = ""
        
        # --- [RHEED 1D 추출용 변수] ---
        self.latest_profile = None 

        self.timer = QTimer()
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.update_frame)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox("Camera / Recording")
        body = QVBoxLayout(group)
        
        # 1. 상단 소스 및 FPS
        options = QHBoxLayout()
        options.addWidget(QLabel("Source:"))
        self.source_input = QLineEdit("0")
        self.source_input.setFixedWidth(50)
        options.addWidget(self.source_input)
        options.addWidget(QLabel("FPS:"))
        self.fps_input = QDoubleSpinBox()
        self.fps_input.setValue(30.0)
        options.addWidget(self.fps_input)
        options.addStretch()
        body.addLayout(options)
        
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
        self.preview = QLabel("No camera preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(160)
        self.preview.setStyleSheet("background:#000; color:#777; border:2px inset #555;")
        body.addWidget(self.preview)
        
        # 4. 저장 및 제어 버튼
        folder = QHBoxLayout()
        folder.addWidget(QLabel("Path:"))
        self.path_display = QLineEdit(self.output_dir)
        self.path_display.setReadOnly(True)
        folder.addWidget(self.path_display)
        choose = QPushButton("Choose")
        choose.clicked.connect(self.choose_output_dir)
        folder.addWidget(choose)
        body.addLayout(folder)
        
        controls = QHBoxLayout()
        start = QPushButton("Start Preview")
        stop = QPushButton("Stop Preview")
        start.clicked.connect(self.start_preview)
        stop.clicked.connect(self.stop_preview)
        controls.addWidget(start)
        controls.addWidget(stop)
        body.addLayout(controls)
        
        self.record_button = QPushButton("Start Recording")
        self.record_button.clicked.connect(self.toggle_recording)
        body.addWidget(self.record_button)
        layout.addWidget(group)

    def source(self):
        value = self.source_input.text().strip()
        return int(value) if value.isdigit() else value

    def choose_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Camera Save Folder", self.output_dir)
        if path:
            self.output_dir = path
            self.path_display.setText(path)
            self.log(f"Camera save folder changed: {path}")

    def start_preview(self):
        if cv2 is None:
            QMessageBox.critical(self, "Camera Error", "OpenCV is not installed.")
            return False
        if self.capture is not None:
            return True
        capture = cv2.VideoCapture(self.source())
        if not capture.isOpened():
            capture.release()
            QMessageBox.critical(self, "Camera Error", f"Cannot open camera source: {self.source()}")
            return False
        self.capture = capture
        self.timer.start()
        self.log(f"Camera preview started: {self.source()}")
        return True

    def stop_preview(self):
        self.stop_recording()
        self.timer.stop()
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.latest_profile = None # 끄면 프로파일도 초기화
        self.preview.clear()
        self.preview.setText("No camera preview")

    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
            return
        if not self.start_preview():
            return
        os.makedirs(self.output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.video_path = os.path.join(self.output_dir, f"camera_{stamp}.mp4")
        self.recording = True
        self.record_button.setText("Stop Recording")
        self.log(f"Camera recording armed: {self.video_path}")

    def stop_recording(self):
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        if self.recording:
            self.recording = False
            self.record_button.setText("Start Recording")
            self.log(f"Camera recording saved: {self.video_path}")

    def update_frame(self):
        if self.capture is None:
            return
        ok, frame = self.capture.read()
        if not ok:
            self.stop_preview()
            return
        if self.recording:
            self.write_frame(frame)
            
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
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

    def write_frame(self, frame):
        if self.writer is None:
            height, width = frame.shape[:2]
            codec = cv2.VideoWriter_fourcc(*"mp4v")
            self.writer = cv2.VideoWriter(self.video_path, codec, int(self.fps_input.value()), (width, height))
            if not self.writer.isOpened():
                QMessageBox.critical(self, "Camera Error", "Cannot create camera video file.")
                self.stop_recording()
                return
        self.writer.write(frame)
        
    # 데이터 로거가 프로파일을 가져갈 수 있게 하는 함수
    def get_latest_profile(self):
        return self.latest_profile
