import sys
import threading
import time

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

from plugins.devices.ctvideo_3m.video_display import (
    CompactConnectVideoDisplaySettings,
    process_frame,
)

try:
    import cv2
except ImportError:
    cv2 = None


VIDEO_GAIN_NAME = "CompactConnect Video Gain"
ANTI_FLICKER_NAME = "CompactConnect Anti-flicker"


def _capture_backend(source):
    """Return the preferred OpenCV backend for the current platform."""
    if not isinstance(source, int):
        return cv2.CAP_ANY
    if sys.platform == "win32":
        return getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
    if sys.platform == "darwin":
        return getattr(cv2, "CAP_AVFOUNDATION", cv2.CAP_ANY)
    return cv2.CAP_ANY


class CTVideoWorker(QThread):
    frame_ready = pyqtSignal(object)
    video_error = pyqtSignal(str)
    camera_properties = pyqtSignal(object)
    source_status = pyqtSignal(str)
    source_opened = pyqtSignal(object, str)
    hardware_status = pyqtSignal(str)

    def __init__(
        self, source, camera_name, display_settings=None, camera_info=None,
        parent=None,
    ):
        super().__init__(parent)
        self.source = source
        self.camera_name = camera_name
        self.camera_info = dict(camera_info or {})
        self._display_settings = CompactConnectVideoDisplaySettings.from_mapping(
            display_settings or {}
        )
        self._pending_display_settings = None
        self._pending_video_gain = None
        self._pending_anti_flicker = None
        self._read_properties_requested = False
        self._request_lock = threading.Lock()
        self._hardware_summary = {}

    @staticmethod
    def _backend_candidates(source):
        if not isinstance(source, int):
            return ((cv2.CAP_ANY, "ANY"),)
        if source >= 0:
            backend = _capture_backend(source)
            label = {
                "win32": "DirectShow",
                "darwin": "AVFoundation",
            }.get(sys.platform, "Auto")
            return ((backend, label),)
        candidates = []
        if sys.platform == "win32":
            backend_options = (
                ("CAP_DSHOW", "DirectShow"),
                ("CAP_MSMF", "Media Foundation"),
                ("CAP_ANY", "Auto"),
            )
        elif sys.platform == "darwin":
            backend_options = (
                ("CAP_AVFOUNDATION", "AVFoundation"),
                ("CAP_ANY", "Auto"),
            )
        else:
            backend_options = (("CAP_ANY", "Auto"),)
        for attribute, label in backend_options:
            backend = getattr(cv2, attribute, None)
            if backend is not None and all(item[0] != backend for item in candidates):
                candidates.append((backend, label))
        return tuple(candidates)

    def _source_candidates(self):
        if not isinstance(self.source, int):
            return (self.source,)
        if self.source < 0:
            return tuple(range(11))
        return (self.source,)

    def _open_capture(self):
        failures = []
        for source in self._source_candidates():
            for backend, backend_name in self._backend_candidates(source):
                capture = cv2.VideoCapture(source, backend)
                if not capture.isOpened():
                    failures.append(f"{source}/{backend_name}: open failed")
                    capture.release()
                    continue
                try:
                    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                except Exception:
                    pass
                first_frame = None
                warmup_attempts = 12 if source == self.source else 5
                for attempt in range(warmup_attempts):
                    ok, frame = capture.read()
                    if ok and frame is not None and getattr(frame, "size", 0):
                        first_frame = frame
                        break
                    if self.isInterruptionRequested():
                        capture.release()
                        return None, None
                    if attempt == warmup_attempts // 2:
                        try:
                            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                            capture.set(cv2.CAP_PROP_FPS, 30)
                            capture.set(
                                cv2.CAP_PROP_FOURCC,
                                cv2.VideoWriter_fourcc(*"MJPG"),
                            )
                        except Exception:
                            pass
                    time.sleep(0.05)
                if first_frame is not None:
                    self.source_opened.emit(source, backend_name)
                    self.source_status.emit(
                        f"Camera source {source} opened with {backend_name}"
                    )
                    return capture, first_frame
                failures.append(f"{source}/{backend_name}: no frames")
                capture.release()
        detail = "; ".join(failures[-6:])
        raise RuntimeError(
            f"Cannot receive CTvideo frames from source {self.source}"
            + (f" ({detail})" if detail else "")
        )

    def set_video_display_settings(self, settings):
        validated = CompactConnectVideoDisplaySettings.from_mapping(settings)
        with self._request_lock:
            self._pending_display_settings = validated

    def set_compactconnect_video_gain(self, value, *, confirmed=False):
        if confirmed is not True:
            raise PermissionError(
                "Queueing a persistent Video Gain write requires confirmed=True."
            )
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("CompactConnect Video Gain must be an integer.")
        if not 1 <= value <= 255:
            raise ValueError("CompactConnect Video Gain must be in range 1..255.")
        with self._request_lock:
            self._pending_video_gain = value

    def set_compactconnect_anti_flicker(self, mode, *, confirmed=False):
        if confirmed is not True:
            raise PermissionError(
                "Queueing a persistent Anti-flicker write requires confirmed=True."
            )
        if isinstance(mode, bool) or not isinstance(mode, int):
            raise TypeError("CompactConnect Anti-flicker mode must be an integer.")
        if mode not in (0, 1, 2):
            raise ValueError(
                "CompactConnect Anti-flicker mode must be 0, 1, or 2."
            )
        with self._request_lock:
            self._pending_anti_flicker = mode

    def request_camera_properties(self):
        with self._request_lock:
            self._read_properties_requested = True

    def _take_requests(self):
        with self._request_lock:
            requests = (
                self._pending_display_settings,
                self._pending_video_gain,
                self._pending_anti_flicker,
                self._read_properties_requested,
            )
            self._pending_display_settings = None
            self._pending_video_gain = None
            self._pending_anti_flicker = None
            self._read_properties_requested = False
        return requests

    def _emit_camera_results(self, results, operation):
        controls = {item["name"]: item for item in results}
        self._hardware_summary.update(controls)
        self.camera_properties.emit({"operation": operation, "controls": controls})
        parts = []
        gain = self._hardware_summary.get(VIDEO_GAIN_NAME)
        if gain is not None:
            current = gain.get("current")
            parts.append(
                "Gain unavailable" if current is None else f"Gain {current}"
            )
        anti = self._hardware_summary.get(ANTI_FLICKER_NAME)
        if anti is not None:
            parts.append(anti.get("display") or "Anti-flicker unavailable")
        if parts:
            self.hardware_status.emit(" | ".join(parts))

    @staticmethod
    def _read_hardware_controls(controller):
        results = []
        try:
            snapshot = controller.read_compactconnect_video_gain()
            consistency = (
                "consistent"
                if snapshot.internally_consistent else
                f"complement mismatch ({snapshot.complement})"
            )
            results.append({
                "name": VIDEO_GAIN_NAME,
                "supported": True,
                "applied": None,
                "current": snapshot.value,
                "minimum": 1,
                "maximum": 255,
                "step": 1,
                "detail": (
                    "Vendor YTarget at EEPROM 0x0801; "
                    f"read-back {snapshot.value}, {consistency}"
                ),
            })
        except Exception as error:
            results.append({
                "name": VIDEO_GAIN_NAME,
                "supported": False,
                "applied": None,
                "current": None,
                "minimum": 1,
                "maximum": 255,
                "step": 1,
                "detail": f"Vendor YTarget read unavailable: {error}",
            })
        try:
            snapshot = controller.read_compactconnect_anti_flicker()
            results.append({
                "name": ANTI_FLICKER_NAME,
                "supported": True,
                "applied": None,
                "current": (
                    snapshot.possible_modes[0]
                    if len(snapshot.possible_modes) == 1 else None
                ),
                "raw_current": snapshot.raw_value,
                "possible_modes": snapshot.possible_modes,
                "display": snapshot.description,
                "minimum": 0,
                "maximum": 2,
                "step": 1,
                "detail": (
                    "CompactConnect Indoor byte at EEPROM 0x083A; "
                    f"{snapshot.description}. Off and 50 Hz share raw value 25."
                ),
            })
        except Exception as error:
            results.append({
                "name": ANTI_FLICKER_NAME,
                "supported": False,
                "applied": None,
                "current": None,
                "raw_current": None,
                "possible_modes": (),
                "display": "Anti-flicker unavailable",
                "minimum": 0,
                "maximum": 2,
                "step": 1,
                "detail": f"Vendor Anti-flicker read unavailable: {error}",
            })
        return results

    @staticmethod
    def _gain_write_result(written):
        return {
            "name": VIDEO_GAIN_NAME,
            "supported": written.verified,
            "applied": written.verified,
            "requested": written.requested,
            "current": written.after.value,
            "minimum": 1,
            "maximum": 255,
            "step": 1,
            "detail": (
                f"EEPROM YTarget requested={written.requested}, "
                f"before={written.before.value}, read-back={written.after.value}"
            ),
        }

    @staticmethod
    def _anti_flicker_write_result(written):
        return {
            "name": ANTI_FLICKER_NAME,
            "supported": written.verified,
            "applied": written.verified,
            "requested": written.requested_mode,
            "current": written.requested_mode if written.verified else None,
            "raw_current": written.after.raw_value,
            "possible_modes": written.after.possible_modes,
            "display": written.after.description,
            "minimum": 0,
            "maximum": 2,
            "step": 1,
            "detail": (
                f"EEPROM Anti-flicker requested mode={written.requested_mode}, "
                f"raw={written.requested_raw}, read-back={written.after.raw_value}"
            ),
        }

    @staticmethod
    def _hardware_unavailable_results(error):
        detail = f"CompactConnect vendor controls unavailable: {error}"
        return [
            {
                "name": VIDEO_GAIN_NAME,
                "supported": False,
                "applied": None,
                "current": None,
                "minimum": 1,
                "maximum": 255,
                "step": 1,
                "detail": detail,
            },
            {
                "name": ANTI_FLICKER_NAME,
                "supported": False,
                "applied": None,
                "current": None,
                "raw_current": None,
                "possible_modes": (),
                "display": "Anti-flicker unavailable",
                "minimum": 0,
                "maximum": 2,
                "step": 1,
                "detail": detail,
            },
        ]

    def run(self):
        if cv2 is None:
            self.video_error.emit("OpenCV is not installed.")
            return
        try:
            capture, first_frame = self._open_capture()
        except Exception as error:
            self.video_error.emit(str(error))
            return
        if capture is None:
            return

        controller = None
        try:
            try:
                from plugins.devices.ctvideo_3m.compactconnect_camera import (
                    CompactConnectCameraController,
                )
                controller = CompactConnectCameraController.from_camera_info(
                    self.camera_info
                )
                controller.open()
                results = self._read_hardware_controls(controller)
                self._emit_camera_results(results, "read")
                self.source_status.emit(
                    "CompactConnect camera hardware values read through vendor XU"
                )
            except Exception as error:
                if controller is not None:
                    try:
                        controller.close()
                    except Exception:
                        pass
                controller = None
                self._emit_camera_results(
                    self._hardware_unavailable_results(error), "read"
                )
                self.source_status.emit(str(error))

            last_emit = 0.0
            failed_reads = 0
            pending_frame = first_frame
            process_error_reported = False
            while not self.isInterruptionRequested():
                (
                    display_settings,
                    video_gain,
                    anti_flicker,
                    read_requested,
                ) = self._take_requests()
                if display_settings is not None:
                    self._display_settings = display_settings
                    self.source_status.emit("Video display settings applied")

                if video_gain is not None:
                    try:
                        if controller is None:
                            raise RuntimeError("Vendor camera control is unavailable")
                        written = controller.set_compactconnect_video_gain(
                            video_gain, acknowledged=True
                        )
                        self._emit_camera_results(
                            [self._gain_write_result(written)], "video_gain_apply"
                        )
                    except Exception as error:
                        self._emit_camera_results([{
                            "name": VIDEO_GAIN_NAME,
                            "supported": False,
                            "applied": False,
                            "requested": video_gain,
                            "current": None,
                            "minimum": 1,
                            "maximum": 255,
                            "step": 1,
                            "detail": f"EEPROM write failed: {error}",
                        }], "video_gain_apply")
                        self.source_status.emit(str(error))

                if anti_flicker is not None:
                    try:
                        if controller is None:
                            raise RuntimeError("Vendor camera control is unavailable")
                        written = controller.set_compactconnect_anti_flicker(
                            anti_flicker, acknowledged=True
                        )
                        self._emit_camera_results(
                            [self._anti_flicker_write_result(written)],
                            "anti_flicker_apply",
                        )
                    except Exception as error:
                        self._emit_camera_results([{
                            "name": ANTI_FLICKER_NAME,
                            "supported": False,
                            "applied": False,
                            "requested": anti_flicker,
                            "current": None,
                            "raw_current": None,
                            "possible_modes": (),
                            "display": "Anti-flicker write failed",
                            "minimum": 0,
                            "maximum": 2,
                            "step": 1,
                            "detail": f"EEPROM write failed: {error}",
                        }], "anti_flicker_apply")
                        self.source_status.emit(str(error))

                if read_requested:
                    results = (
                        self._read_hardware_controls(controller)
                        if controller is not None else
                        self._hardware_unavailable_results(
                            "Vendor camera control is unavailable"
                        )
                    )
                    self._emit_camera_results(results, "read")

                if pending_frame is not None:
                    frame = pending_frame
                    pending_frame = None
                    ok = True
                else:
                    ok, frame = capture.read()
                if not ok or frame is None or not getattr(frame, "size", 0):
                    failed_reads += 1
                    if failed_reads >= 20:
                        self.video_error.emit(
                            "CTvideo frame capture failed 20 consecutive times."
                        )
                        break
                    time.sleep(0.05)
                    continue
                failed_reads = 0
                try:
                    frame = process_frame(frame, self._display_settings, cv2)
                    process_error_reported = False
                except Exception as error:
                    if not process_error_reported:
                        self.source_status.emit(
                            f"Video display processing skipped: {error}"
                        )
                        process_error_reported = True
                now = time.monotonic()
                if now - last_emit < 1.0 / 30.0:
                    time.sleep(0.002)
                    continue
                last_emit = now
                self.frame_ready.emit(frame)
        finally:
            if controller is not None:
                try:
                    controller.close()
                except Exception:
                    pass
            capture.release()


class CTVideoView(QWidget):
    camera_properties = pyqtSignal(object)
    _sessions = {}

    def __init__(self, log_callback, parent=None):
        super().__init__(parent)
        self.log = log_callback
        self.worker = None
        self._session_key = None
        self.source = 0
        self._last_display_settings = (
            CompactConnectVideoDisplaySettings().to_dict()
        )
        self._camera_info = {}
        self.hardware_text = "Camera values not read"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        group = QGroupBox("CTvideo 3M Pyrometer Video")
        body = QVBoxLayout(group)
        self.preview = QLabel("CTvideo 3M\nVIDEO STANDBY")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(240, 180)
        self.preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview.setStyleSheet(
            "background:#000; color:#777; border:2px inset #555; font-size:18pt;"
        )
        self.status = QLabel("Video thread: stopped")
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Camera index"))
        self.source_selector = QSpinBox()
        self.source_selector.setRange(-1, 10)
        self.source_selector.setSpecialValueText("Auto scan")
        self.source_selector.setValue(-1)
        self.open_button = QPushButton("Open / Retry")
        self.open_button.clicked.connect(self.open_selected_source)
        source_row.addWidget(self.source_selector)
        source_row.addWidget(self.open_button)
        source_row.addStretch()
        body.addLayout(source_row)
        body.addWidget(self.preview, 1)
        body.addWidget(self.status)
        layout.addWidget(group)

    def start_preview(
        self, source=0, camera_name="", display_settings=None, camera_info=None,
    ):
        if not self.stop_preview():
            self.status.setText("Video thread: previous worker is still stopping")
            self.log("CTvideo 3M: preview restart blocked until the worker stops")
            return False
        source_text = str(source).strip()
        source = int(source_text) if source_text.lstrip("+-").isdigit() else source_text
        if isinstance(source, int):
            self.source_selector.blockSignals(True)
            self.source_selector.setValue(source)
            self.source_selector.blockSignals(False)
        self.source = source
        if display_settings is not None:
            self._last_display_settings = (
                CompactConnectVideoDisplaySettings.from_mapping(
                    display_settings
                ).to_dict()
            )
        if camera_info is not None:
            self._camera_info = dict(camera_info)

        camera_identity = (
            self._camera_info.get("CameraDevicePath")
            or self._camera_info.get("CameraContainerId")
            or camera_name
        )
        key = (
            type(source).__name__, source,
            str(camera_identity or "").strip().casefold(),
        )
        session = self._sessions.get(key)
        if session is None or not session["worker"].isRunning():
            if session is not None:
                self._sessions.pop(key, None)
            worker = CTVideoWorker(
                source,
                camera_name,
                self._last_display_settings,
                self._camera_info,
            )
            session = {"worker": worker, "views": set()}
            self._sessions[key] = session
            start_worker = True
        else:
            worker = session["worker"]
            start_worker = False
            worker.set_video_display_settings(self._last_display_settings)
            worker.request_camera_properties()
        self.worker = worker
        self._session_key = key
        self.hardware_text = "Camera values not read"
        session["views"].add(self)
        self.worker.frame_ready.connect(self.update_frame)
        self.worker.video_error.connect(self.handle_error)
        self.worker.camera_properties.connect(self.forward_camera_properties)
        self.worker.source_status.connect(self.handle_source_status)
        self.worker.source_opened.connect(self.handle_source_opened)
        self.worker.hardware_status.connect(self.handle_hardware_status)
        self.worker.finished.connect(self.worker_finished)
        self.status.setText(
            f"Video thread: {'starting' if start_worker else 'shared'} ({source})"
        )
        if start_worker:
            self.worker.start()
        return True

    def open_selected_source(self):
        self.start_preview(
            self.source_selector.value(),
            "Manually selected CTvideo camera",
            self._last_display_settings,
            self._camera_info,
        )

    def handle_source_opened(self, source, backend_name):
        if isinstance(source, int):
            self.source_selector.setValue(source)
        self.status.setText(
            f"Camera index {source} opened with {backend_name}; waiting for frames"
        )

    def forward_camera_properties(self, properties):
        self.camera_properties.emit(properties)

    def handle_source_status(self, message):
        self.status.setText(message)
        self.log(f"CTvideo 3M: {message}")

    def handle_hardware_status(self, message):
        self.hardware_text = message

    def set_video_display_settings(self, settings):
        self._last_display_settings = (
            CompactConnectVideoDisplaySettings.from_mapping(settings).to_dict()
        )
        if self.worker is None:
            return False
        self.worker.set_video_display_settings(self._last_display_settings)
        return True

    def set_compactconnect_video_gain(self, value, *, confirmed=False):
        if confirmed is not True:
            raise PermissionError(
                "Queueing a persistent Video Gain write requires confirmed=True."
            )
        if self.worker is None:
            return False
        self.worker.set_compactconnect_video_gain(value, confirmed=True)
        return True

    def set_compactconnect_anti_flicker(self, mode, *, confirmed=False):
        if confirmed is not True:
            raise PermissionError(
                "Queueing a persistent Anti-flicker write requires confirmed=True."
            )
        if self.worker is None:
            return False
        self.worker.set_compactconnect_anti_flicker(mode, confirmed=True)
        return True

    def request_camera_properties(self):
        if self.worker is None:
            return False
        self.worker.request_camera_properties()
        return True

    def stop_preview(self):
        if self.worker is not None:
            worker = self.worker
            key = self._session_key
            session = self._sessions.get(key)
            if session is not None and session["worker"] is worker:
                last_view = session["views"] == {self}
                if last_view:
                    worker.requestInterruption()
                    if not worker.wait(4000):
                        self.status.setText("Video thread: waiting for camera to stop")
                        return False
                self._disconnect_worker(worker)
                session["views"].discard(self)
                if last_view:
                    self._sessions.pop(key, None)
            else:
                self._disconnect_worker(worker)
            self.worker = None
            self._session_key = None
        self.preview.clear()
        self.preview.setText("CTvideo 3M\nVIDEO STANDBY")
        self.status.setText("Video thread: stopped")
        return True

    def _disconnect_worker(self, worker):
        for signal, callback in (
            (worker.frame_ready, self.update_frame),
            (worker.video_error, self.handle_error),
            (worker.camera_properties, self.forward_camera_properties),
            (worker.source_status, self.handle_source_status),
            (worker.source_opened, self.handle_source_opened),
            (worker.hardware_status, self.handle_hardware_status),
            (worker.finished, self.worker_finished),
        ):
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass

    def update_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = QImage(
            rgb.data, width, height, 3 * width,
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)
        self.status.setText(
            f"Video thread: running ({width} x {height}) | {self.hardware_text}"
        )

    def handle_error(self, message):
        self.log(f"CTvideo 3M: {message}")
        self.preview.setText(message)
        self.status.setText("Video thread: error")

    def worker_finished(self):
        worker = self.sender()
        if self.worker is worker:
            key = self._session_key
            session = self._sessions.get(key)
            if session is not None and session["worker"] is worker:
                session["views"].discard(self)
                if not worker.isRunning():
                    self._sessions.pop(key, None)
            self.worker = None
            self._session_key = None
