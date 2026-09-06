import unittest

import numpy as np
import cv2
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from plugins.experiments.MBE1.panel import ExperimentPanel, ScreenRecorderThread


class Cameras:
    def __init__(self):
        self.routes = []
        self.releases = []
        self.available = {0: True, 1: True}

    def frame_packet(self, _index):
        raise AssertionError("MBE monitor must not capture or copy frames")

    def route_preview(self, target, index, owner):
        self.routes.append((target, index, owner))
        return self.available[index]

    def release_preview(self, owner):
        self.releases.append(owner)


class Data:
    def latest(self, device_id):
        if device_id == "CTVIDEO3M":
            return {"actual_temp_C": 321.5}
        if device_id == "ZUP":
            return {"voltage_V": 12, "current_A": 2, "power_W": 24}
        return {}

    def metrics(self, _device_id):
        return {
            "age_ms": 25.0,
            "sample_id": 1,
            "connected": True,
            "realtime": True,
            "sampled_at_utc": "2026-08-24T00:00:00Z",
            "error": "",
        }


class Experiments:
    def __init__(self):
        self.calls = []

    def execute(self, experiment_id, command, value):
        self.calls.append((experiment_id, command, value))
        return False

    def is_complete(self, *_args):
        return False

    def panel(self, _experiment_id):
        return None


class Context:
    def __init__(self):
        self.cameras = Cameras()
        self.data = Data()
        self.experiments = Experiments()


class MbeMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_uses_real_context_services(self):
        context = Context()
        panel = ExperimentPanel(context)
        panel.refresh()

        self.assertIn("321.5", panel.control_temperature.text())
        self.assertIn("2.000", panel.control_current.text())
        panel.activate()
        self.assertEqual(
            [(target, index) for target, index, _owner in context.cameras.routes],
            [(panel.camera_view, 1), (panel.pyrometer_view, 0)],
        )
        self.assertTrue(all(
            owner is panel for _target, _index, owner in context.cameras.routes
        ))
        self.assertIn("Live Camera 2", panel.camera_status.text())
        panel.deactivate()
        self.assertIs(context.cameras.releases[-1], panel)
        panel.setpoint.setValue(400)
        panel.apply_setpoint()
        self.assertEqual(
            context.experiments.calls[-1],
            ("heating_control", "ramp_to_setpoint", 400.0),
        )
        panel.shutdown()

    def test_screen_recorder_encodes_jpeg_without_qt_image_plugin(self):
        image = QImage(18, 10, QImage.Format.Format_RGB32)
        image.fill(0xFF2A80C0)
        recorder = ScreenRecorderThread("unused.avi", 18, 10, 10)

        jpeg = recorder._encode_jpeg(image)
        decoded = cv2.imdecode(
            np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
        )

        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape[:2], (10, 18))

    def test_monitor_views_can_swap_camera_sources(self):
        context = Context()
        panel = ExperimentPanel(context)
        panel.activate()
        context.cameras.routes.clear()

        panel.camera_source_selector.setCurrentIndex(0)

        self.assertEqual(panel.camera_source_selector.currentData(), 0)
        self.assertEqual(panel.pyrometer_source_selector.currentData(), 1)
        self.assertEqual(
            [(target, index) for target, index, _owner in context.cameras.routes],
            [(panel.camera_view, 0), (panel.pyrometer_view, 1)],
        )
        self.assertIn("Live Camera 1", panel.camera_status.text())
        self.assertIn("Live Camera 2", panel.pyrometer_camera_status.text())
        panel.shutdown()

    def test_unavailable_camera_is_retried_when_stream_appears(self):
        context = Context()
        context.cameras.available[1] = False
        panel = ExperimentPanel(context)
        panel.activate()
        self.assertIn("retrying", panel.camera_status.text())

        context.cameras.available[1] = True
        panel.refresh()

        self.assertTrue(panel._preview_route_ready["camera"])
        self.assertIn("Live Camera 2", panel.camera_status.text())
        panel.shutdown()


if __name__ == "__main__":
    unittest.main()
