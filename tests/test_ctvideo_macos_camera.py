import json
import plistlib
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from plugins.devices.ctvideo_3m import video
from plugins.devices.ctvideo_3m.resolvers import macos


CONTAINER_ID = "cc8214e5-49d5-4e1a-ab9c-f45642fa5ad5"


def observed_usb_devices():
    return [
        {
            "USB Product Name": "USB 2.0 Hub",
            "idVendor": 0x1A40,
            "idProduct": 0x0401,
            "locationID": 0x02113000,
            "kUSBContainerID": CONTAINER_ID,
        },
        {
            "USB Product Name": "CMS_309I01 AA00000000",
            "idVendor": 0x093A,
            "idProduct": 0x2900,
            "locationID": 0x02113100,
            "kUSBContainerID": CONTAINER_ID,
        },
        {
            "USB Product Name": "IR Online Video Sensor",
            "USB Serial Number": "CTLV_21060012",
            "idVendor": 0x0403,
            "idProduct": 0xDE33,
            "locationID": 0x02113200,
            "kUSBContainerID": CONTAINER_ID,
        },
    ]


def observed_cameras():
    return [
        {
            "index": 0,
            "name": "MacBook Pro Camera",
            "unique_id": "6C707041-05AC-0010-0007-000000000001",
            "location_id": None,
        },
        {
            "index": 1,
            "name": "CMS_309I01 AA00000000",
            "unique_id": "0x2113100093a2900",
            "location_id": 0x02113100,
        },
    ]


class TestMacOSCameraResolver(unittest.TestCase):
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_matches_sibling_camera_by_shared_usb_container(self, usb_devices, cameras):
        usb_devices.return_value = observed_usb_devices()
        cameras.return_value = observed_cameras()

        result = macos.resolve_camera("auto")

        self.assertEqual(result["PortName"], "d2xx://CTLV_21060012")
        self.assertEqual(result["PortContainerId"], CONTAINER_ID)
        self.assertEqual(result["CameraIndex"], 1)
        self.assertEqual(result["CameraName"], "CMS_309I01 AA00000000")
        self.assertEqual(result["CameraLocationId"], 0x02113100)
        self.assertEqual(result["CameraVendorId"], 0x093A)
        self.assertEqual(result["CameraProductId"], 0x2900)
        self.assertEqual(result["CameraContainerId"], CONTAINER_ID)
        self.assertEqual(result["CameraDevicePath"], "AVFoundation camera index 1")

    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_selects_requested_d2xx_serial(self, usb_devices, cameras):
        second = observed_usb_devices()[-1].copy()
        second["USB Serial Number"] = "CTLV_OTHER"
        second["kUSBContainerID"] = "other-container"
        usb_devices.return_value = observed_usb_devices() + [second]
        cameras.return_value = observed_cameras()

        result = macos.resolve_camera("CTLV_21060012")

        self.assertEqual(result["PortName"], "d2xx://CTLV_21060012")

    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_rejects_camera_outside_sensor_container(self, usb_devices, cameras):
        usb_devices.return_value = observed_usb_devices()
        cameras.return_value = [{
            "index": 0,
            "name": "Unrelated camera",
            "unique_id": "0x2112000534d0021",
            "location_id": 0x02112000,
        }]

        with self.assertRaisesRegex(RuntimeError, "No AVFoundation camera"):
            macos.resolve_camera("auto")

    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_falls_back_to_unique_ctvideo_camera_when_sensor_is_missing(
        self, usb_devices, cameras
    ):
        usb_devices.return_value = observed_usb_devices()[:2]
        cameras.return_value = observed_cameras()

        result = macos.resolve_camera("auto")

        self.assertEqual(result["PortName"], "d2xx://auto")
        self.assertEqual(result["CameraIndex"], 1)
        self.assertEqual(result["CameraLocationId"], 0x02113100)
        self.assertEqual(result["CameraVendorId"], 0x093A)
        self.assertEqual(result["CameraProductId"], 0x2900)
        self.assertEqual(result["CameraContainerId"], CONTAINER_ID)

    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_preserves_requested_serial_in_direct_camera_fallback(
        self, usb_devices, cameras
    ):
        usb_devices.return_value = observed_usb_devices()[:2]
        cameras.return_value = observed_cameras()

        result = macos.resolve_camera("CTLV_21060012")

        self.assertEqual(result["PortName"], "d2xx://CTLV_21060012")

    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_falls_back_when_sensor_container_mapping_is_unavailable(
        self, usb_devices, cameras
    ):
        devices = observed_usb_devices()
        devices[-1] = devices[-1].copy()
        devices[-1].pop("kUSBContainerID")
        usb_devices.return_value = devices
        cameras.return_value = observed_cameras()

        result = macos.resolve_camera("auto")

        self.assertEqual(result["PortName"], "d2xx://CTLV_21060012")
        self.assertEqual(result["CameraLocationId"], 0x02113100)
        self.assertEqual(result["CameraVendorId"], 0x093A)
        self.assertEqual(result["CameraProductId"], 0x2900)

    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_rejects_ambiguous_direct_ctvideo_cameras(
        self, usb_devices, cameras
    ):
        second_camera = observed_usb_devices()[1].copy()
        second_camera["locationID"] = 0x02114100
        second_camera["kUSBContainerID"] = "another-container"
        usb_devices.return_value = observed_usb_devices()[:2] + [second_camera]
        cameras.return_value = observed_cameras()

        with self.assertRaisesRegex(
            RuntimeError, "Multiple CTvideo camera USB devices"
        ):
            macos.resolve_camera("auto")

    @patch("plugins.devices.ctvideo_3m.resolvers.macos._cameras")
    @patch("plugins.devices.ctvideo_3m.resolvers.macos._usb_devices")
    def test_rejects_missing_sensor_and_camera(self, usb_devices, cameras):
        usb_devices.return_value = observed_usb_devices()[:1]
        cameras.return_value = observed_cameras()

        with self.assertRaisesRegex(RuntimeError, "VID:PID 093A:2900"):
            macos.resolve_camera("auto")

    @patch("plugins.devices.ctvideo_3m.resolvers.macos.subprocess.run")
    def test_parses_ioreg_archive(self, run):
        report = [{
            "IORegistryEntryChildren": observed_usb_devices(),
        }]
        run.return_value = SimpleNamespace(stdout=plistlib.dumps(report))

        devices = macos._usb_devices()

        self.assertEqual(len(devices), 3)
        self.assertEqual(devices[-1]["idProduct"], 0xDE33)
        run.assert_called_once_with(
            macos._IOREG_COMMAND,
            check=True,
            capture_output=True,
            timeout=15,
        )

    @patch("plugins.devices.ctvideo_3m.resolvers.macos.subprocess.run")
    def test_uses_avfoundation_order_for_opencv_index(self, run):
        report = [
            {
                "index": 0,
                "name": "MacBook Pro Camera",
                "unique_id": "builtin-camera",
            },
            {
                "index": 1,
                "name": "CMS_309I01 AA00000000",
                "unique_id": "0x2113100093a2900",
            },
        ]
        run.return_value = SimpleNamespace(stdout=json.dumps(report))

        cameras = macos._cameras()

        self.assertEqual(cameras[1]["index"], 1)
        self.assertEqual(cameras[1]["location_id"], 0x02113100)

    @patch("plugins.devices.ctvideo_3m.resolvers.macos.subprocess.run")
    def test_reports_avfoundation_enumeration_failure(self, run):
        run.side_effect = subprocess.TimeoutExpired("swift", 30)

        with self.assertRaisesRegex(RuntimeError, "AVFoundation cameras"):
            macos._cameras()


class TestCTVideoCaptureBackend(unittest.TestCase):
    def setUp(self):
        self.cv2 = SimpleNamespace(
            CAP_ANY=0,
            CAP_DSHOW=700,
            CAP_AVFOUNDATION=1200,
        )

    def test_uses_avfoundation_for_macos_camera_index(self):
        with patch.object(video, "cv2", self.cv2), patch.object(
            video.sys, "platform", "darwin"
        ):
            self.assertEqual(video._capture_backend(1), 1200)

    def test_preserves_directshow_for_windows_camera_index(self):
        with patch.object(video, "cv2", self.cv2), patch.object(
            video.sys, "platform", "win32"
        ):
            self.assertEqual(video._capture_backend(1), 700)

    def test_uses_default_backend_for_non_index_source(self):
        with patch.object(video, "cv2", self.cv2), patch.object(
            video.sys, "platform", "darwin"
        ):
            self.assertEqual(video._capture_backend("video.mp4"), 0)


if __name__ == "__main__":
    unittest.main()
