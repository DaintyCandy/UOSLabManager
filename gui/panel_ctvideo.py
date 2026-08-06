import time

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

try:
    import cv2
except ImportError:
    cv2 = None


class CTVideoWorker(QThread):
    frame_ready = pyqtSignal(object)
    video_error = pyqtSignal(str)
    gain_status = pyqtSignal(str)
    brightness_status = pyqtSignal(str)
    camera_properties = pyqtSignal(object)
    source_status = pyqtSignal(str)
    source_opened = pyqtSignal(object, str)

    def __init__(self, source, camera_name, uvc_settings=None, parent=None):
        super().__init__(parent)
        self.source = source
        self.camera_name = camera_name
        self._uvc_settings = dict(uvc_settings or {})
        self._pending_uvc_settings = None
        self._requested_gain = None
        self._applied_gain = object()
        self._requested_brightness = None
        self._applied_brightness = object()

    @staticmethod
    def _backend_candidates(source):
        if not isinstance(source, int):
            return ((cv2.CAP_ANY, "ANY"),)
        candidates = []
        for attribute, label in (
            ("CAP_DSHOW", "DirectShow"),
            ("CAP_MSMF", "Media Foundation"),
            ("CAP_ANY", "Auto"),
        ):
            backend = getattr(cv2, attribute, None)
            if backend is not None and all(item[0] != backend for item in candidates):
                candidates.append((backend, label))
        return tuple(candidates)

    def _source_candidates(self):
        if not isinstance(self.source, int):
            return (self.source,)
        if self.source < 0:
            return tuple(range(11))
        return tuple(dict.fromkeys((self.source, *range(11))))

    def _open_capture(self):
        failures = []
        for source in self._source_candidates():
            backends = self._backend_candidates(source)
            for backend, backend_name in backends:
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
                        # CTvideo units commonly expose a 640x480 UVC mode;
                        # requesting it recovers drivers that do not choose a
                        # valid default media type.
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

    def set_gain(self, gain):
        self._requested_gain = float(gain)

    def set_brightness(self, brightness):
        self._requested_brightness = float(brightness)

    def set_uvc_settings(self, settings):
        self._pending_uvc_settings = dict(settings)

    def _camera_properties(self, capture):
        auto_exposure = capture.get(cv2.CAP_PROP_AUTO_EXPOSURE)
        return {
            "gain_supported": True,
            "gain": capture.get(cv2.CAP_PROP_GAIN),
            "gain_min": 0, "gain_max": 4, "gain_step": 1,
            "brightness_supported": True,
            "brightness": capture.get(cv2.CAP_PROP_BRIGHTNESS),
            "brightness_min": -64, "brightness_max": 64, "brightness_step": 1,
            "exposure_supported": True,
            "auto_exposure": auto_exposure > 0.5,
            "auto_exposure_raw": auto_exposure,
        }

    def _apply_gain(self, capture):
        gain = self._requested_gain
        if gain is None or gain == self._applied_gain:
            return
        try:
            accepted = capture.set(cv2.CAP_PROP_GAIN, gain)
            self._applied_gain = gain
            properties = self._camera_properties(capture)
            self.camera_properties.emit(properties)
            text = f"Gain: {properties['gain']:g}" if accepted else "Gain: unsupported"
            self.gain_status.emit(text)
        except Exception as error:
            self.gain_status.emit(f"Gain error: {error}")

    def _apply_brightness(self, capture):
        brightness = self._requested_brightness
        if brightness is None or brightness == self._applied_brightness:
            return
        try:
            accepted = capture.set(cv2.CAP_PROP_BRIGHTNESS, brightness)
            self._applied_brightness = brightness
            properties = self._camera_properties(capture)
            self.camera_properties.emit(properties)
            text = (
                f"Brightness: {properties['brightness']:g}"
                if accepted else "Brightness: unsupported"
            )
            self.brightness_status.emit(text)
        except Exception as error:
            self.brightness_status.emit(f"Brightness error: {error}")

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
        try:
            initializer = None
            try:
                from plugins.devices.ctvideo_3m.uvc_initializer import UVCInitializer
                initializer = UVCInitializer(cv2)
                initialization = initializer.apply(capture, self._uvc_settings)
                for item in initialization:
                    state = "OK" if item["applied"] else "SKIP"
                    self.gain_status.emit(
                        f"UVC {state} {item['name']} "
                        f"(E{item['entity']:02X}/S{item['selector']:02X}): {item['detail']}"
                    )
            except Exception as error:
                # Camera preview must remain available even when optional UVC
                # property initialization is rejected by the Windows driver.
                self.gain_status.emit(f"UVC initialization skipped: {error}")
            properties = self._camera_properties(capture)
            self.camera_properties.emit(properties)
            self.gain_status.emit(f"Gain: {properties['gain']:g}")
            self.brightness_status.emit(f"Brightness: {properties['brightness']:g}")
            last_emit = 0.0
            failed_reads = 0
            pending_frame = first_frame
            while not self.isInterruptionRequested():
                if self._pending_uvc_settings is not None:
                    settings = self._pending_uvc_settings
                    self._pending_uvc_settings = None
                    if initializer is not None:
                        try:
                            for item in initializer.apply(capture, settings):
                                state = "OK" if item["applied"] else "SKIP"
                                self.gain_status.emit(
                                    f"UVC {state} {item['name']}: {item['detail']}"
                                )
                        except Exception as error:
                            self.gain_status.emit(f"UVC update skipped: {error}")
                self._apply_gain(capture)
                self._apply_brightness(capture)
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
                now = time.monotonic()
                if now - last_emit < 1.0 / 30.0:
                    time.sleep(0.002)
                    continue
                last_emit = now
                self.frame_ready.emit(frame)
        finally:
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
        self.gain_text = "Gain: device default"
        self.brightness_text = "Brightness: device default"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        group = QGroupBox("CTvideo 3M Pyrometer Video")
        body = QVBoxLayout(group)
        self.preview = QLabel("CTvideo 3M\nVIDEO STANDBY")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(240, 180)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background:#000; color:#777; border:2px inset #555; font-size:18pt;")
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

    def start_preview(self, source=0, camera_name="", uvc_settings=None):
        if not self.stop_preview():
            self.status.setText("Video thread: previous worker is still stopping")
            self.log("CTvideo 3M: preview restart blocked until the previous thread stops")
            return False
        source_text = str(source).strip()
        source = (
            int(source_text)
            if source_text.lstrip("+-").isdigit()
            else source_text
        )
        if isinstance(source, int):
            self.source_selector.blockSignals(True)
            self.source_selector.setValue(source)
            self.source_selector.blockSignals(False)
        self.source = source
        key = (type(source).__name__, source)
        session = self._sessions.get(key)
        if session is None or not session["worker"].isRunning():
            if session is not None:
                self._sessions.pop(key, None)
            worker = CTVideoWorker(source, camera_name, uvc_settings)
            session = {"worker": worker, "views": set()}
            self._sessions[key] = session
            start_worker = True
        else:
            worker = session["worker"]
            start_worker = False
            if uvc_settings:
                worker.set_uvc_settings(uvc_settings)
        self.worker = worker
        self._session_key = key
        session["views"].add(self)
        self.worker.frame_ready.connect(self.update_frame)
        self.worker.video_error.connect(self.handle_error)
        self.worker.gain_status.connect(self.handle_gain_status)
        self.worker.brightness_status.connect(self.handle_brightness_status)
        self.worker.camera_properties.connect(self.forward_camera_properties)
        self.worker.source_status.connect(self.handle_source_status)
        self.worker.source_opened.connect(self.handle_source_opened)
        self.worker.finished.connect(self.worker_finished)
        self.status.setText(
            f"Video thread: {'starting' if start_worker else 'shared'} ({source})"
        )
        if start_worker:
            self.worker.start()
        return True

    def open_selected_source(self):
        self.start_preview(
            self.source_selector.value(), "Manually selected CTvideo camera"
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

    def set_gain(self, gain):
        if self.worker is not None:
            self.worker.set_gain(gain)

    def set_brightness(self, brightness):
        if self.worker is not None:
            self.worker.set_brightness(brightness)

    def set_uvc_settings(self, settings):
        if self.worker is not None:
            self.worker.set_uvc_settings(settings)

    def handle_gain_status(self, message):
        self.gain_text = message
        self.log(f"CTvideo 3M: {message}")

    def handle_brightness_status(self, message):
        self.brightness_text = message
        self.log(f"CTvideo 3M: {message}")

    def stop_preview(self):
        if self.worker is not None:
            worker = self.worker
            key = self._session_key
            session = self._sessions.get(key)
            self._disconnect_worker(worker)
            self.worker = None
            self._session_key = None
            if session is not None and session["worker"] is worker:
                session["views"].discard(self)
                if not session["views"]:
                    worker.requestInterruption()
                    if not worker.wait(4000):
                        return False
                    self._sessions.pop(key, None)
        self.preview.clear()
        self.preview.setText("CTvideo 3M\nVIDEO STANDBY")
        self.status.setText("Video thread: stopped")
        return True

    def _disconnect_worker(self, worker):
        for signal, callback in (
            (worker.frame_ready, self.update_frame),
            (worker.video_error, self.handle_error),
            (worker.gain_status, self.handle_gain_status),
            (worker.brightness_status, self.handle_brightness_status),
            (worker.camera_properties, self.forward_camera_properties),
            (worker.source_status, self.handle_source_status),
            (worker.source_opened, self.handle_source_opened),
            (worker.finished, self.worker_finished),
        ):
            try:
                signal.disconnect(callback)
            except (TypeError, RuntimeError):
                pass

    def update_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)
        self.status.setText(
            f"Video thread: running ({width} x {height}) | "
            f"{self.gain_text} | {self.brightness_text}"
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
