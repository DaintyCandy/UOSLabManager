import sys
import time

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QGroupBox, QLabel, QSizePolicy, QVBoxLayout, QWidget

try:
    import cv2
except ImportError:
    cv2 = None


def _capture_backend(source):
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
    gain_status = pyqtSignal(str)
    brightness_status = pyqtSignal(str)
    camera_properties = pyqtSignal(object)

    def __init__(
        self, source, camera_name, uvc_settings=None, camera_info=None,
        parent=None,
    ):
        super().__init__(parent)
        self.source = source
        self.camera_name = camera_name
        self.camera_info = dict(camera_info or {})
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
        if sys.platform != "win32":
            return {
                "gain_supported": False,
                "gain": None,
                "gain_min": None,
                "gain_max": None,
                "gain_step": None,
                "brightness_supported": False,
                "brightness": None,
                "brightness_min": None,
                "brightness_max": None,
                "brightness_step": None,
                "exposure_supported": False,
                "auto_exposure": None,
                "auto_exposure_raw": None,
                "uvc_controls": {},
            }
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
        backend = _capture_backend(self.source)
        capture = cv2.VideoCapture(self.source, backend)
        if not capture.isOpened():
            self.video_error.emit(f"Cannot open CTvideo camera source: {self.source}")
            capture.release()
            return
        try:
            initializer = None
            native_controller = None
            properties = None
            if sys.platform == "win32":
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
                    # Camera preview must remain available even when optional
                    # UVC property initialization is rejected by the driver.
                    self.gain_status.emit(f"UVC initialization skipped: {error}")
            elif sys.platform == "darwin":
                try:
                    from plugins.devices.ctvideo_3m.macos_uvc import (
                        MacOSUVCController,
                    )
                    native_controller = MacOSUVCController(
                        self.camera_info.get("CameraLocationId")
                    )
                    native_controller.probe()
                    properties = native_controller.camera_properties()
                    self.gain_status.emit(
                        "macOS native UVC controls ready"
                    )
                except Exception as error:
                    self.gain_status.emit(
                        f"macOS native UVC controls unavailable: {error}"
                    )
            else:
                self.gain_status.emit(
                    "UVC initialization skipped: unsupported platform"
                )
            if properties is None:
                properties = self._camera_properties(capture)
            self.camera_properties.emit(properties)
            gain = properties.get("gain")
            brightness = properties.get("brightness")
            self.gain_status.emit(
                f"Gain: {gain:g}"
                if properties.get("gain_supported") and gain is not None
                else "Gain: unsupported"
            )
            self.brightness_status.emit(
                f"Brightness: {brightness:g}"
                if properties.get("brightness_supported")
                and brightness is not None
                else "Brightness: unsupported"
            )
            while not self.isInterruptionRequested():
                if self._pending_uvc_settings is not None:
                    settings = self._pending_uvc_settings
                    self._pending_uvc_settings = None
                    if native_controller is not None:
                        try:
                            for item in native_controller.apply(settings):
                                state = "OK" if item["applied"] else "SKIP"
                                self.gain_status.emit(
                                    f"UVC {state} {item['name']}: {item['detail']}"
                                )
                            properties = native_controller.camera_properties()
                            self.camera_properties.emit(properties)
                            gain = properties.get("gain")
                            brightness = properties.get("brightness")
                            self.gain_status.emit(
                                f"Gain: {gain:g}"
                                if properties.get("gain_supported")
                                and gain is not None
                                else "Gain: unsupported"
                            )
                            self.brightness_status.emit(
                                f"Brightness: {brightness:g}"
                                if properties.get("brightness_supported")
                                and brightness is not None
                                else "Brightness: unsupported"
                            )
                        except Exception as error:
                            self.gain_status.emit(f"UVC update failed: {error}")
                    elif initializer is not None:
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

    def start_preview(
        self, source=0, camera_name="", uvc_settings=None, camera_info=None,
    ):
        if not self.stop_preview():
            self.status.setText("Video thread: previous worker is still stopping")
            self.log("CTvideo 3M: preview restart blocked until the previous thread stops")
            return False
        source = int(source) if str(source).strip().isdigit() else str(source).strip()
        self.source = source
        self.worker = CTVideoWorker(
            source,
            camera_name,
            uvc_settings,
            camera_info=camera_info,
            parent=self,
        )
        self.worker.frame_ready.connect(self.update_frame)
        self.worker.video_error.connect(self.handle_error)
        self.worker.gain_status.connect(self.handle_gain_status)
        self.worker.brightness_status.connect(self.handle_brightness_status)
        self.worker.camera_properties.connect(self.camera_properties.emit)
        self.worker.finished.connect(self.worker_finished)
        self.status.setText(f"Video thread: starting ({source})")
        self.worker.start()
        return True

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
            if not worker.wait(4000):
                return False
            if self.worker is worker:
                self.worker = None
        self.preview.clear()
        self.preview.setText("CTvideo 3M\nVIDEO STANDBY")
        self.status.setText("Video thread: stopped")
        return True

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
