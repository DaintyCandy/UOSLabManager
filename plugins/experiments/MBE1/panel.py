"""Theme-neutral MBE heating monitor."""

import math
import os
import queue
import shutil
import struct
import tempfile
import time
from datetime import datetime

import numpy as np
import cv2
from PyQt6.QtCore import (
    QByteArray,
    QBuffer,
    QIODevice,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import QFont, QImage
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


PYROMETER_ID = "CTVIDEO3M"
POWER_SUPPLY_ID = "ZUP"
HEATING_EXPERIMENT_ID = "heating_control"
CAMERA_INDEX = 0
PYROMETER_CAMERA_INDEX = 1
SCREEN_RECORDING_FPS = 10
SCREEN_RECORDING_QUEUE_SIZE = 3
RECORDING_DIRECTORY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "camera_recording"
)
_ACTIVE_SCREEN_RECORDERS = set()


class ScreenRecorderThread(QThread):
    """Encode detached QImages as an OpenCV-backed MJPEG AVI off the GUI thread."""

    recorder_ready = pyqtSignal()
    AVI_SIZE_LIMIT = 0xFFF00000

    def __init__(self, output_path, width, height, fps):
        super().__init__()
        self.output_path = os.path.abspath(output_path)
        self.width = max(2, int(width) // 2 * 2)
        self.height = max(2, int(height) // 2 * 2)
        self.fps = max(1, int(fps))
        self.frame_count = 0
        self.dropped_frames = 0
        self.error_message = ""
        self.saved = False
        self.cancelled = False
        self.size_limit_reached = False
        self._frames = queue.Queue(maxsize=SCREEN_RECORDING_QUEUE_SIZE)
        self._stop_requested = False
        self._accepting_frames = False

    def enqueue_frame(self, image):
        """Queue a detached frame without ever blocking the GUI thread."""
        if self._stop_requested or not self._accepting_frames:
            return False
        try:
            self._frames.put_nowait(image.copy())
        except queue.Full:
            self.dropped_frames += 1
            return False
        return True

    def stop_async(self, discard_pending=False):
        self._stop_requested = True
        self._accepting_frames = False
        self.requestInterruption()
        if discard_pending:
            while True:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    break

    def run(self):
        temporary_path = None
        try:
            output_directory = os.path.dirname(self.output_path)
            os.makedirs(output_directory, exist_ok=True)
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(self.output_path)}.",
                suffix=".part",
                dir=output_directory,
            )
            with os.fdopen(file_descriptor, "w+b") as output, \
                    tempfile.TemporaryFile() as index:
                header = self._write_avi_header(output)
                if self._stop_requested:
                    self.cancelled = True
                    return

                self._accepting_frames = True
                self.recorder_ready.emit()
                max_frame_size = 0

                while not self._stop_requested or not self._frames.empty():
                    try:
                        image = self._frames.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    jpeg = self._encode_jpeg(image)
                    projected_size = output.tell() + len(jpeg) + 24
                    if projected_size >= self.AVI_SIZE_LIMIT:
                        self.size_limit_reached = True
                        self._stop_requested = True
                        self._accepting_frames = False
                        break

                    chunk_position = output.tell()
                    output.write(b"00dc")
                    output.write(struct.pack("<I", len(jpeg)))
                    output.write(jpeg)
                    if len(jpeg) & 1:
                        output.write(b"\x00")

                    index.write(struct.pack(
                        "<4sIII",
                        b"00dc",
                        0x10,
                        chunk_position - header["movi_type_position"],
                        len(jpeg),
                    ))
                    self.frame_count += 1
                    max_frame_size = max(max_frame_size, len(jpeg))

                if self.frame_count == 0:
                    self.cancelled = True
                    return

                self._finish_avi(output, index, header, max_frame_size)
                output.flush()
                os.fsync(output.fileno())

            os.replace(temporary_path, self.output_path)
            temporary_path = None
            self.saved = True
        except Exception as error:
            self.error_message = str(error)
        finally:
            self._accepting_frames = False
            if temporary_path is not None:
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass

    def _write_avi_header(self, output):
        microseconds_per_frame = round(1_000_000 / self.fps)
        image_bytes = self.width * self.height * 3

        output.write(b"RIFF")
        riff_size_position = output.tell()
        output.write(struct.pack("<I", 0))
        output.write(b"AVI ")

        output.write(b"LIST")
        output.write(struct.pack("<I", 192))
        output.write(b"hdrl")

        output.write(b"avih")
        output.write(struct.pack("<I", 56))
        avih_position = output.tell()
        output.write(struct.pack(
            "<14I",
            microseconds_per_frame,
            0,
            0,
            0x10,
            0,
            0,
            1,
            0,
            self.width,
            self.height,
            0,
            0,
            0,
            0,
        ))

        output.write(b"LIST")
        output.write(struct.pack("<I", 116))
        output.write(b"strl")
        output.write(b"strh")
        output.write(struct.pack("<I", 56))
        strh_position = output.tell()
        output.write(struct.pack(
            "<4s4sIHH8I4h",
            b"vids",
            b"MJPG",
            0,
            0,
            0,
            0,
            1,
            self.fps,
            0,
            0,
            0,
            0xFFFFFFFF,
            0,
            0,
            0,
            self.width,
            self.height,
        ))

        output.write(b"strf")
        output.write(struct.pack("<I", 40))
        output.write(struct.pack(
            "<IiiHH4sIiiII",
            40,
            self.width,
            self.height,
            1,
            24,
            b"MJPG",
            image_bytes,
            0,
            0,
            0,
            0,
        ))

        output.write(b"LIST")
        movi_size_position = output.tell()
        output.write(struct.pack("<I", 0))
        movi_type_position = output.tell()
        output.write(b"movi")
        return {
            "riff_size_position": riff_size_position,
            "avih_position": avih_position,
            "strh_position": strh_position,
            "movi_size_position": movi_size_position,
            "movi_type_position": movi_type_position,
        }

    def _encode_jpeg(self, image):
        if image.isNull():
            raise RuntimeError("화면 프레임을 캡처하지 못했습니다.")
        if image.width() != self.width or image.height() != self.height:
            image = image.scaled(
                self.width,
                self.height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        rgb_image = image.convertToFormat(QImage.Format.Format_RGB888)
        byte_count = rgb_image.sizeInBytes()
        bits = rgb_image.bits()
        bits.setsize(byte_count)
        rows = np.frombuffer(bits, dtype=np.uint8, count=byte_count).reshape(
            rgb_image.height(), rgb_image.bytesPerLine()
        )
        rgb = np.ascontiguousarray(
            rows[:, :rgb_image.width() * 3].reshape(
                rgb_image.height(), rgb_image.width(), 3
            )
        )
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        success, encoded = cv2.imencode(
            ".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85]
        )
        if not success:
            raise RuntimeError("OpenCV JPEG encoder is unavailable.")
        return encoded.tobytes()

        encoded = QByteArray()
        buffer = QBuffer(encoded)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise RuntimeError("영상 프레임 버퍼를 열지 못했습니다.")
        try:
            if not image.save(buffer, "JPEG", 85):
                raise RuntimeError("Qt JPEG 인코더를 사용할 수 없습니다.")
        finally:
            buffer.close()
        return bytes(encoded)

    def _finish_avi(self, output, index, header, max_frame_size):
        movi_end = output.tell()
        self._patch_uint32(
            output,
            header["movi_size_position"],
            movi_end - header["movi_type_position"],
        )

        output.seek(movi_end)
        index_size = self.frame_count * 16
        output.write(b"idx1")
        output.write(struct.pack("<I", index_size))
        index.seek(0)
        shutil.copyfileobj(index, output, length=1024 * 1024)
        file_end = output.tell()

        self._patch_uint32(output, header["riff_size_position"], file_end - 8)
        self._patch_uint32(
            output,
            header["avih_position"] + 4,
            max_frame_size * self.fps,
        )
        self._patch_uint32(output, header["avih_position"] + 16, self.frame_count)
        self._patch_uint32(output, header["avih_position"] + 28, max_frame_size)
        self._patch_uint32(output, header["strh_position"] + 32, self.frame_count)
        self._patch_uint32(output, header["strh_position"] + 36, max_frame_size)
        output.seek(file_end)

    @staticmethod
    def _patch_uint32(output, position, value):
        current = output.tell()
        output.seek(position)
        output.write(struct.pack("<I", max(0, min(0xFFFFFFFF, int(value)))))
        output.seek(current)


class ExperimentPanel(QWidget):
    """Monitor pyrometer/camera data and forward heating setpoints safely."""

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self._device_samples = {
            PYROMETER_ID: self._empty_sample_state(),
            POWER_SUPPLY_ID: self._empty_sample_state(),
        }
        self._requested_setpoint = None
        self._setpoint_complete = False
        self._stop_pending = False
        self._command_in_progress = False
        self._heating_requested_by_panel = False
        self._screen_recorder = None
        self._screen_recording_started_at = None
        self._screen_recording_stop_requested = False
        self._shutting_down = False
        self._preview_routing_active = False
        self._preview_route_ready = {"camera": False, "pyrometer": False}

        self._build_ui()
        self.screen_capture_timer = QTimer(self)
        self.screen_capture_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.screen_capture_timer.timeout.connect(self._capture_screen_frame)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()
        self.refresh()

    @staticmethod
    def _empty_sample_state():
        return {
            "sample_id": 0,
            "sampled_at_utc": None,
            "age_ms": None,
            "fresh": False,
            "connected": False,
            "values": {},
        }

    def _build_ui(self):
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        layout.addLayout(self._build_screen_recording_controls(), 0, 0, 1, 2)

        self.camera_panel = self._build_camera_panel()
        self.pyrometer_panel = self._build_pyrometer_panel()
        self.notes_panel = self._build_notes_panel()
        self.control_panel = self._build_control_panel()
        for bottom_panel in (self.notes_panel, self.control_panel):
            bottom_panel.setMaximumHeight(205)
            bottom_panel.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
        layout.addWidget(self.camera_panel, 1, 0)
        layout.addWidget(self.pyrometer_panel, 1, 1)
        layout.addWidget(self.notes_panel, 2, 0)
        layout.addWidget(self.control_panel, 2, 1)
        layout.setRowStretch(1, 1)
        layout.setRowStretch(2, 0)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)

    def _build_screen_recording_controls(self):
        controls = QHBoxLayout()
        controls.addWidget(QLabel("모니터링 화면 녹화"))

        self.screen_fps = QSpinBox()
        self.screen_fps.setRange(1, 30)
        self.screen_fps.setValue(SCREEN_RECORDING_FPS)
        self.screen_fps.setSuffix(" FPS")
        self.screen_fps.setToolTip("화면 녹화 프레임 속도 (1–30 FPS)")
        controls.addWidget(self.screen_fps)

        self.screen_record_button = QPushButton("녹화 시작")
        self.screen_record_button.clicked.connect(self.start_screen_recording)
        controls.addWidget(self.screen_record_button)

        self.screen_stop_button = QPushButton("녹화 중지")
        self.screen_stop_button.setEnabled(False)
        self.screen_stop_button.clicked.connect(self.stop_screen_recording)
        controls.addWidget(self.screen_stop_button)

        self.screen_record_status = QLabel("대기 중")
        self.screen_record_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        controls.addWidget(self.screen_record_status, 1)
        return controls

    def _build_camera_panel(self):
        group = QGroupBox("Monitor View 1")
        layout = QVBoxLayout(group)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source"))
        self.camera_source_selector = self._camera_source_selector(1)
        source_row.addWidget(self.camera_source_selector, 1)
        layout.addLayout(source_row)
        self.camera_view = QLabel(
            "Camera 화면에서 프리뷰를 켜면 공유 스트림이 표시됩니다."
        )
        self.camera_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_view.setWordWrap(True)
        self.camera_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.camera_view.setStyleSheet("border: 1px solid palette(mid);")
        layout.addWidget(self.camera_view, 1)
        self.camera_status = QLabel("Camera renderer is in the Camera tab")
        self.camera_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.camera_status)
        self.camera_source_selector.currentIndexChanged.connect(
            lambda _index: self._preview_source_changed(
                self.camera_source_selector,
                self.pyrometer_source_selector,
            )
        )
        return group

    def _build_pyrometer_panel(self):
        group = QGroupBox("Monitor View 2")
        layout = QVBoxLayout(group)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source"))
        self.pyrometer_source_selector = self._camera_source_selector(0)
        source_row.addWidget(self.pyrometer_source_selector, 1)
        layout.addLayout(source_row)

        self.pyrometer_view = QLabel("CTvideo 3M 영상 스트림을 기다리는 중입니다.")
        self.pyrometer_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pyrometer_view.setWordWrap(True)
        self.pyrometer_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.pyrometer_view.setStyleSheet("border: 1px solid palette(mid);")
        layout.addWidget(self.pyrometer_view, 3)
        self.pyrometer_camera_status = QLabel(
            "Pyrometer camera renderer is in the Camera tab"
        )
        self.pyrometer_camera_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.pyrometer_camera_status)
        self.pyrometer_source_selector.currentIndexChanged.connect(
            lambda _index: self._preview_source_changed(
                self.pyrometer_source_selector,
                self.camera_source_selector,
            )
        )

        return group

    @staticmethod
    def _camera_source_selector(default_index):
        selector = QComboBox()
        selector.addItem("Camera 1", CAMERA_INDEX)
        selector.addItem("Camera 2", PYROMETER_CAMERA_INDEX)
        selector.setCurrentIndex(default_index)
        return selector

    def _preview_source_changed(self, selector, other_selector):
        selected_camera = int(selector.currentData())
        if int(other_selector.currentData()) == selected_camera:
            replacement = (
                PYROMETER_CAMERA_INDEX
                if selected_camera == CAMERA_INDEX
                else CAMERA_INDEX
            )
            other_selector.blockSignals(True)
            other_selector.setCurrentIndex(other_selector.findData(replacement))
            other_selector.blockSignals(False)
        if self._preview_routing_active:
            self._route_selected_previews()

    def _build_notes_panel(self):
        group = QGroupBox("실험 메모")
        layout = QVBoxLayout(group)
        self.notes = QTextEdit()
        self.notes.setPlaceholderText(
            "실험 조건, 관찰 내용, 시료 상태 등을 기록하세요."
        )
        self.notes.textChanged.connect(self._update_note_count)
        layout.addWidget(self.notes, 1)

        footer = QHBoxLayout()
        self.insert_time_button = QPushButton("현재 시각 삽입")
        self.insert_time_button.clicked.connect(self._insert_note_timestamp)
        footer.addWidget(self.insert_time_button)
        footer.addStretch()
        self.note_count = QLabel("0자")
        footer.addWidget(self.note_count)
        layout.addLayout(footer)
        return group

    def _build_control_panel(self):
        group = QGroupBox("Heating Control")
        layout = QVBoxLayout(group)

        live_form = QFormLayout()
        self.control_temperature = self._live_value_label("— °C")
        self.control_current = self._live_value_label("— A")
        live_form.addRow("현재 온도", self.control_temperature)
        live_form.addRow("현재 전류", self.control_current)
        layout.addLayout(live_form)

        self.control_freshness = QLabel("측정 데이터 확인 중")
        self.control_freshness.setWordWrap(True)
        layout.addWidget(self.control_freshness)

        setpoint_form = QFormLayout()
        self.setpoint = QDoubleSpinBox()
        self.setpoint.setRange(-50.0, 2000.0)
        self.setpoint.setDecimals(1)
        self.setpoint.setSingleStep(1.0)
        self.setpoint.setValue(300.0)
        self.setpoint.setSuffix(" °C")
        setpoint_form.addRow("Setpoint", self.setpoint)
        layout.addLayout(setpoint_form)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Setpoint 적용")
        self.apply_button.clicked.connect(self.apply_setpoint)
        buttons.addWidget(self.apply_button, 1)
        self.stop_button = QPushButton("가열 정지")
        self.stop_button.clicked.connect(self.stop_heating)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

        self.control_status = QLabel("대기 중")
        self.control_status.setWordWrap(True)
        self.control_status.setStyleSheet(
            "font-weight: 600; border-top: 1px solid palette(mid); padding-top: 6px;"
        )
        layout.addWidget(self.control_status)
        layout.addStretch()
        return group

    @staticmethod
    def _live_value_label(text):
        label = QLabel(text)
        font = QFont(label.font())
        font.setPointSize(max(16, font.pointSize() + 6))
        font.setBold(True)
        label.setFont(font)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return label

    def refresh(self):
        if self._shutting_down:
            return
        self._refresh_device(PYROMETER_ID)
        self._refresh_device(POWER_SUPPLY_ID)
        self._refresh_measurement_widgets()
        self._refresh_command_status()
        self._retry_unavailable_previews()

    def _refresh_device(self, device_id):
        values = self.context.data.latest(device_id)
        metrics = self.context.data.metrics(device_id)
        sample_id = int(metrics.get("sample_id") or 0)
        state = self._device_samples[device_id]

        # Replace retained values only for a new timestamped DeviceManager sample.
        if sample_id and sample_id != state["sample_id"]:
            state["sample_id"] = sample_id
            state["sampled_at_utc"] = metrics.get("sampled_at_utc")
            state["values"] = dict(values)
        state["age_ms"] = metrics.get("age_ms")
        state["fresh"] = bool(metrics.get("realtime"))
        state["connected"] = bool(metrics.get("connected"))
        state["error"] = metrics.get("error", "")

    def _refresh_measurement_widgets(self):
        pyro = self._device_samples[PYROMETER_ID]
        supply = self._device_samples[POWER_SUPPLY_ID]
        temperature = (
            self._finite_number(pyro["values"].get("actual_temp_C"))
            if pyro["connected"] else None
        )
        current = (
            self._finite_number(supply["values"].get("current_A"))
            if supply["connected"] else None
        )

        temperature_text = "— °C" if temperature is None else f"{temperature:.1f} °C"
        current_text = "— A" if current is None else f"{current:.3f} A"
        self.control_temperature.setText(temperature_text)
        self.control_current.setText(current_text)

        pyro_state = self._short_freshness(pyro, "온도")
        supply_state = self._short_freshness(supply, "전류")
        self.control_freshness.setText(f"{pyro_state}  ·  {supply_state}")

    @staticmethod
    def _finite_number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _short_freshness(state, label):
        if not state["connected"]:
            return f"{label}: 연결 안 됨"
        age_ms = state["age_ms"]
        age = "—" if age_ms is None else f"{age_ms / 1000.0:.1f}s"
        status = "fresh" if state["fresh"] else "stale"
        return f"{label}: {status} ({age}, #{state['sample_id']})"

    def activate(self):
        """Move the host's live renderers here instead of copying frames."""
        self._preview_routing_active = True
        self._route_selected_previews()

    def _route_selected_previews(self):
        self.context.cameras.release_preview(self)
        self._preview_route_ready = {"camera": False, "pyrometer": False}
        self._route_preview(
            "camera", self.camera_view, self.camera_source_selector,
            self.camera_status,
        )
        self._route_preview(
            "pyrometer", self.pyrometer_view,
            self.pyrometer_source_selector, self.pyrometer_camera_status,
        )

    def _route_preview(self, key, target, selector, status_label):
        camera_index = int(selector.currentData())
        try:
            routed = self.context.cameras.route_preview(
                target, camera_index, self
            )
        except Exception as error:
            self._preview_route_ready[key] = False
            status_label.setText(f"Camera routing failed: {error}")
            return False
        self._preview_route_ready[key] = bool(routed)
        status_label.setText(
            f"Live Camera {camera_index + 1} renderer"
            if routed else f"Camera {camera_index + 1} unavailable; retrying"
        )
        return bool(routed)

    def _retry_unavailable_previews(self):
        if not self._preview_routing_active:
            return
        if not self._preview_route_ready["camera"]:
            self._route_preview(
                "camera", self.camera_view, self.camera_source_selector,
                self.camera_status,
            )
        if not self._preview_route_ready["pyrometer"]:
            self._route_preview(
                "pyrometer", self.pyrometer_view,
                self.pyrometer_source_selector, self.pyrometer_camera_status,
            )

    def deactivate(self):
        self._preview_routing_active = False
        self._preview_route_ready = {"camera": False, "pyrometer": False}
        self.context.cameras.release_preview(self)
        self.camera_status.setText("Camera renderer returned to the Camera tab")
        self.pyrometer_camera_status.setText(
            "Pyrometer camera renderer returned to the Camera tab"
        )

    def start_screen_recording(self):
        if self._shutting_down or self._screen_recorder is not None:
            return

        filename = datetime.now().strftime("MBE_monitor_%Y%m%d_%H%M%S_%f.avi")
        output_path = os.path.join(RECORDING_DIRECTORY, filename)

        probe = self.grab().toImage()
        if probe.isNull() or probe.width() < 2 or probe.height() < 2:
            QMessageBox.warning(
                self,
                "MBE Heating Monitor",
                "현재 모니터링 화면을 캡처할 수 없습니다.",
            )
            return

        recorder = ScreenRecorderThread(
            output_path,
            probe.width(),
            probe.height(),
            self.screen_fps.value(),
        )
        recorder.recorder_ready.connect(self._screen_recorder_ready)
        recorder.finished.connect(self._screen_recorder_finished)
        recorder.finished.connect(
            lambda recorder=recorder: _ACTIVE_SCREEN_RECORDERS.discard(recorder)
        )
        recorder.finished.connect(recorder.deleteLater)
        _ACTIVE_SCREEN_RECORDERS.add(recorder)
        self._screen_recorder = recorder
        self._screen_recording_started_at = None
        self._screen_recording_stop_requested = False
        self.screen_record_button.setEnabled(False)
        self.screen_stop_button.setEnabled(True)
        self.screen_fps.setEnabled(False)
        self._set_screen_record_status("영상 파일 준비 중…", "#c58a00")
        self.screen_record_status.setToolTip(output_path)
        recorder.start()

    def _screen_recorder_ready(self):
        recorder = self.sender()
        if recorder is not self._screen_recorder:
            return
        if self._shutting_down or self._screen_recording_stop_requested:
            recorder.stop_async(discard_pending=True)
            return

        self._screen_recording_started_at = time.monotonic()
        interval_ms = max(1, round(1000 / recorder.fps))
        self.screen_capture_timer.start(interval_ms)
        self._set_screen_record_status("● 화면 녹화 중 · 00:00", "#d9534f")
        self._capture_screen_frame()

    def _capture_screen_frame(self):
        recorder = self._screen_recorder
        if (
            recorder is None
            or self._screen_recording_started_at is None
            or self._screen_recording_stop_requested
        ):
            return

        image = self.grab().toImage()
        recorder.enqueue_frame(image)
        elapsed = max(0, int(time.monotonic() - self._screen_recording_started_at))
        minutes, seconds = divmod(elapsed, 60)
        dropped = (
            f" · 누락 {recorder.dropped_frames}"
            if recorder.dropped_frames else ""
        )
        self._set_screen_record_status(
            f"● 화면 녹화 중 · {minutes:02d}:{seconds:02d}{dropped}",
            "#d9534f",
        )

    def stop_screen_recording(self):
        recorder = self._screen_recorder
        if recorder is None or self._screen_recording_stop_requested:
            return
        self._screen_recording_stop_requested = True
        self.screen_capture_timer.stop()
        self.screen_stop_button.setEnabled(False)
        self._set_screen_record_status("녹화 종료 및 저장 중…", "#c58a00")
        recorder.stop_async()

    def _screen_recorder_finished(self):
        recorder = self.sender()
        if recorder is not self._screen_recorder:
            return

        self.screen_capture_timer.stop()
        self._screen_recorder = None
        self._screen_recording_started_at = None
        self._screen_recording_stop_requested = False

        if not self._shutting_down:
            self.screen_record_button.setEnabled(True)
            self.screen_stop_button.setEnabled(False)
            self.screen_fps.setEnabled(True)

            if recorder.error_message:
                self._set_screen_record_status(
                    f"녹화 실패: {recorder.error_message}", "#d9534f"
                )
                QMessageBox.critical(
                    self,
                    "MBE Heating Monitor / 화면 녹화",
                    recorder.error_message,
                )
            elif recorder.saved:
                limit_note = (
                    " · AVI 용량 한도 도달"
                    if recorder.size_limit_reached else ""
                )
                dropped_note = (
                    f" · 누락 {recorder.dropped_frames}"
                    if recorder.dropped_frames else ""
                )
                self._set_screen_record_status(
                    f"저장 완료 · {os.path.basename(recorder.output_path)}"
                    f" · {recorder.frame_count}프레임{dropped_note}{limit_note}",
                    "#2e9d55",
                )
                self.screen_record_status.setToolTip(recorder.output_path)
            else:
                self._set_screen_record_status("녹화가 취소되었습니다.")

    def _set_screen_record_status(self, text, color=None):
        self.screen_record_status.setText(text)
        self.screen_record_status.setStyleSheet(
            f"color: {color}; font-weight: 600;" if color else ""
        )

    def _insert_note_timestamp(self):
        stamp = datetime.now().astimezone().strftime("[%Y-%m-%d %H:%M:%S] ")
        self.notes.textCursor().insertText(stamp)
        self.notes.setFocus()

    def _update_note_count(self):
        self.note_count.setText(f"{len(self.notes.toPlainText())}자")

    def apply_setpoint(self):
        target = self.setpoint.value()
        try:
            self._request_setpoint(target)
        except Exception as error:
            self._show_control_error(error)

    def _request_setpoint(self, target):
        target = float(target)
        if self._command_in_progress:
            return False
        if (
            self._requested_setpoint is not None
            and math.isclose(target, self._requested_setpoint, abs_tol=0.05)
            and not self._setpoint_complete
        ):
            self.control_status.setText(f"{target:.1f} °C 도달 대기 중")
            return False

        self._command_in_progress = True
        self.apply_button.setEnabled(False)
        try:
            complete = bool(self.context.experiments.execute(
                HEATING_EXPERIMENT_ID, "ramp_to_setpoint", target
            ))
        finally:
            self._command_in_progress = False
            self.apply_button.setEnabled(True)

        self._requested_setpoint = target
        self._setpoint_complete = complete
        self._stop_pending = False
        self._heating_requested_by_panel = True
        self.control_status.setText(
            f"Setpoint {target:.1f} °C "
            + ("도달" if complete else "적용됨 · 도달 대기 중")
        )
        return complete

    def stop_heating(self):
        try:
            return self._request_stop()
        except Exception as error:
            self._show_control_error(error)
            return False

    def _request_stop(self):
        if self._command_in_progress or self._stop_pending:
            return False
        self._command_in_progress = True
        self.stop_button.setEnabled(False)
        try:
            complete = bool(self.context.experiments.execute(
                HEATING_EXPERIMENT_ID, "stop_heating", 0
            ))
        finally:
            self._command_in_progress = False
            self.stop_button.setEnabled(True)
        self._requested_setpoint = None
        self._setpoint_complete = False
        self._stop_pending = not complete
        self.control_status.setText("가열 정지 완료" if complete else "안전 정지 중")
        if complete:
            self._heating_requested_by_panel = False
        return complete

    def _refresh_command_status(self):
        if self._stop_pending:
            try:
                complete = self.context.experiments.is_complete(
                    HEATING_EXPERIMENT_ID, "stop_heating", 0
                )
            except Exception as error:
                self._stop_pending = False
                self.control_status.setText(f"정지 상태 확인 실패: {error}")
                return
            if complete:
                self._stop_pending = False
                self._heating_requested_by_panel = False
                self.control_status.setText("가열 정지 완료")
            return

        if self._requested_setpoint is None or self._setpoint_complete:
            return
        try:
            complete = self.context.experiments.is_complete(
                HEATING_EXPERIMENT_ID,
                "ramp_to_setpoint",
                self._requested_setpoint,
            )
        except Exception as error:
            self._requested_setpoint = None
            self.control_status.setText(f"Heating Control 중단: {error}")
            return
        if complete:
            self._setpoint_complete = True
            self.control_status.setText(
                f"Setpoint {self._requested_setpoint:.1f} °C 도달"
            )

    def _show_control_error(self, error):
        self.control_status.setText(f"명령 실패: {error}")
        QMessageBox.critical(self, "MBE Heating Monitor", str(error))

    def execute_sequence_command(self, command, value):
        if command != "set_value":
            raise ValueError(f"Unsupported command: {command}")
        self.setpoint.setValue(float(value))
        return self._request_setpoint(float(value))

    def is_sequence_command_complete(self, command, value):
        if command != "set_value":
            raise ValueError(f"Unsupported command: {command}")
        return bool(self.context.experiments.is_complete(
            HEATING_EXPERIMENT_ID, "ramp_to_setpoint", float(value)
        ))

    def cancel_sequence_command(self):
        self._request_stop()

    def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        self.deactivate()
        self.refresh_timer.stop()
        self.screen_capture_timer.stop()
        recorder = self._screen_recorder
        if recorder is not None:
            recorder.stop_async()
            recorder.wait(5000)
            self._screen_recorder = None
        if self._heating_requested_by_panel:
            try:
                self.context.experiments.execute(
                    HEATING_EXPERIMENT_ID, "stop_heating", 0
                )
            except Exception:
                # The owning heating-control panel also performs its safe shutdown.
                pass
        self._requested_setpoint = None
        self._stop_pending = False
