import tempfile
import unittest

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel
from unittest.mock import MagicMock, patch

from gui.panel_camera import CameraPanel, CameraWorkspace
from plugins.devices.ctvideo_3m.video import CTVideoView


class FakeCameraWorker(QObject):
    frame_ready = pyqtSignal(object)
    finished = pyqtSignal()


class FakeCTVideoWorker(QObject):
    frame_ready = pyqtSignal(object)
    video_error = pyqtSignal(str)
    camera_properties = pyqtSignal(object)
    source_status = pyqtSignal(str)
    source_opened = pyqtSignal(object, str)
    hardware_status = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = False

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def requestInterruption(self):
        self.running = False

    def set_video_display_settings(self, _settings):
        pass

    def request_camera_properties(self):
        pass


class CameraStreamRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.panel = CameraPanel(self.temp_dir.name, lambda _message: None)
        self.addCleanup(self.panel.deleteLater)

    def test_external_worker_is_reused_and_preview_is_routed(self):
        worker = FakeCameraWorker()
        target = QLabel()
        target.resize(320, 240)
        owner = object()

        self.panel.attach_external_stream(worker, "CTvideo 3M")
        self.assertTrue(self.panel.route_display(target, owner))

        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        frame[..., 1] = 255
        worker.frame_ready.emit(frame)
        self.app.processEvents()

        self.assertIs(self.panel.external_worker, worker)
        self.assertIsNone(self.panel.camera_worker)
        self.assertFalse(target.pixmap().isNull())
        borrowed, sequence = self.panel.get_frame_packet(copy=False)
        self.assertIs(borrowed, self.panel.latest_frame)
        self.assertEqual(sequence, 1)

        self.panel.release_display(owner)
        self.assertIs(self.panel.display_target, self.panel.preview)

    def test_preview_off_does_not_close_shared_capture(self):
        worker = FakeCameraWorker()
        self.panel.attach_external_stream(worker, "CTvideo 3M")

        self.panel.stop_preview()

        self.assertIs(self.panel.external_worker, worker)
        self.assertFalse(self.panel.preview_active)
        self.panel.detach_external_stream(worker)
        self.assertIsNone(self.panel.external_worker)

    def test_routing_does_not_start_a_camera_when_preview_is_off(self):
        target = QLabel()

        with patch.object(self.panel, "start_preview") as start_preview:
            routed = self.panel.route_display(target, object())

        self.assertFalse(routed)
        start_preview.assert_not_called()
        self.assertIs(self.panel.display_target, self.panel.preview)
        self.assertIn("Camera tab", target.text())

    def test_two_camera_renderers_can_move_to_one_experiment_tab(self):
        workspace = CameraWorkspace(self.temp_dir.name, lambda _message: None)
        self.addCleanup(workspace.deleteLater)
        primary_worker = FakeCameraWorker()
        secondary_worker = FakeCameraWorker()
        workspace.attach_external_stream(primary_worker, 0, "Camera 1")
        workspace.attach_external_stream(secondary_worker, 1, "Camera 2")
        first_target = QLabel()
        second_target = QLabel()
        owner = object()

        self.assertTrue(workspace.route_preview(first_target, 0, owner))
        self.assertTrue(workspace.route_preview(second_target, 1, owner))

        self.assertIs(workspace.primary.display_target, first_target)
        self.assertIs(workspace.secondary.display_target, second_target)
        workspace.release_preview(owner)
        self.assertIs(workspace.primary.display_target, workspace.primary.preview)
        self.assertIs(workspace.secondary.display_target, workspace.secondary.preview)
        workspace.detach_external_stream(primary_worker, 0)
        workspace.detach_external_stream(secondary_worker, 1)

    def test_ctvideo_registers_its_existing_worker_with_camera_workspace(self):
        worker = FakeCTVideoWorker()
        workspace = MagicMock()
        CTVideoView._sessions.clear()
        self.addCleanup(CTVideoView._sessions.clear)

        with patch(
            "plugins.devices.ctvideo_3m.video.CTVideoWorker",
            return_value=worker,
        ):
            view = CTVideoView(
                lambda _message: None, camera_workspace=workspace
            )
            self.addCleanup(view.deleteLater)
            self.assertTrue(view.start_preview(1, "CTvideo camera"))

        workspace.attach_external_stream.assert_called_once_with(
            worker, 0, "CTvideo camera"
        )
        view.stop_preview()
        workspace.detach_external_stream.assert_called_with(worker, 0)


if __name__ == "__main__":
    unittest.main()
