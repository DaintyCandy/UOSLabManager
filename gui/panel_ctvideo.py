import time

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QGroupBox, QLabel, QSizePolicy, QVBoxLayout, QWidget

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
        backend = cv2.CAP_DSHOW if isinstance(self.source, int) and hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.source, backend)
        if not capture.isOpened():
            self.video_error.emit(f"Cannot open CTvideo camera source: {self.source}")
            capture.release()
            return
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
            properties = self._camera_properties(capture)
            self.camera_properties.emit(properties)
            self.gain_status.emit(f"Gain: {properties['gain']:g}")
            self.brightness_status.emit(f"Brightness: {properties['brightness']:g}")
            while not self.isInterruptionRequested():
                if self._pending_uvc_settings is not None:
                    settings = self._pending_uvc_settings
                    self._pending_uvc_settings = None
                    for item in initializer.apply(capture, settings):
                        state = "OK" if item["applied"] else "SKIP"
                        self.gain_status.emit(
                            f"UVC {state} {item['name']}: {item['detail']}"
                        )
                self._apply_gain(capture)
                self._apply_brightness(capture)
                ok, frame = capture.read()
                if not ok:
                    self.video_error.emit("CTvideo frame capture failed.")
                    break
                self.frame_ready.emit(frame)
                time.sleep(0.001)
        finally:
            capture.release()


class CTVideoView(QWidget):
    camera_properties = pyqtSignal(object)

    def __init__(self, log_callback, parent=None):
        super().__init__(parent)
        self.log = log_callback
        self.worker = None
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
        body.addWidget(self.preview, 1)
        body.addWidget(self.status)
        layout.addWidget(group)

    def start_preview(self, source=0, camera_name="", uvc_settings=None):
        self.stop_preview()
        source = int(source) if str(source).strip().isdigit() else str(source).strip()
        self.source = source
        self.worker = CTVideoWorker(source, camera_name, uvc_settings, self)
        self.worker.frame_ready.connect(self.update_frame)
        self.worker.video_error.connect(self.handle_error)
        self.worker.gain_status.connect(self.handle_gain_status)
        self.worker.brightness_status.connect(self.handle_brightness_status)
        self.worker.camera_properties.connect(self.camera_properties.emit)
        self.worker.finished.connect(self.worker_finished)
        self.status.setText(f"Video thread: starting ({source})")
        self.worker.start()

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
            worker.requestInterruption()
            worker.wait(1500)
            if self.worker is worker:
                self.worker = None
        self.preview.clear()
        self.preview.setText("CTvideo 3M\nVIDEO STANDBY")
        self.status.setText("Video thread: stopped")

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
        if self.worker is self.sender():
            self.worker = None
