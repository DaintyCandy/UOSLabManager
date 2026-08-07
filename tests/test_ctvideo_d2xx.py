import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from plugins.devices.ctvideo_3m import connection
from plugins.devices.ctvideo_3m import d2xx_transport
from plugins.devices.ctvideo_3m.d2xx_transport import (
    CTVIDEO_PRODUCT_ID,
    CTVIDEO_VENDOR_ID,
    D2XXError,
    D2XXSerialAdapter,
    FT_PURGE_RX,
)


class FakeD2XX:
    def __init__(self, devices=None, read_data=b""):
        self.devices = devices or []
        self.read_data = read_data
        self.writes = []
        self.FT_SetVIDPID = MagicMock(return_value=0)
        self.FT_CreateDeviceInfoList = MagicMock(side_effect=self._create_list)
        self.FT_GetDeviceInfoDetail = MagicMock(side_effect=self._device_detail)
        self.FT_OpenEx = MagicMock(side_effect=self._open)
        self.FT_ResetDevice = MagicMock(return_value=0)
        self.FT_SetBaudRate = MagicMock(return_value=0)
        self.FT_SetDataCharacteristics = MagicMock(return_value=0)
        self.FT_SetFlowControl = MagicMock(return_value=0)
        self.FT_SetTimeouts = MagicMock(return_value=0)
        self.FT_SetLatencyTimer = MagicMock(return_value=0)
        self.FT_Purge = MagicMock(return_value=0)
        self.FT_Read = MagicMock(side_effect=self._read)
        self.FT_Write = MagicMock(side_effect=self._write)
        self.FT_Close = MagicMock(return_value=0)

    def _create_list(self, count):
        count._obj.value = len(self.devices)
        return 0

    def _device_detail(
        self, index, flags, device_type, device_id, location_id,
        serial_number, description, handle,
    ):
        device = self.devices[index]
        flags._obj.value = 0
        device_type._obj.value = 5
        device_id._obj.value = device.get(
            "device_id", (CTVIDEO_VENDOR_ID << 16) | CTVIDEO_PRODUCT_ID
        )
        location_id._obj.value = device.get("location_id", 0x02113200)
        ctypes.memmove(
            serial_number,
            device["serial_number"].encode("ascii") + b"\0",
            len(device["serial_number"]) + 1,
        )
        encoded_description = device.get(
            "description", "IR Online Video Sensor"
        ).encode("utf-8")
        ctypes.memmove(
            description, encoded_description + b"\0", len(encoded_description) + 1,
        )
        handle._obj.value = 0
        return 0

    @staticmethod
    def _open(serial_number, _flags, handle):
        if not serial_number.value:
            return 2
        handle._obj.value = 0x1234
        return 0

    def _read(self, _handle, buffer, requested, received):
        payload = self.read_data[:requested]
        ctypes.memmove(buffer, payload, len(payload))
        received._obj.value = len(payload)
        return 0

    def _write(self, _handle, buffer, requested, written):
        self.writes.append(ctypes.string_at(buffer, requested))
        written._obj.value = requested
        return 0


class TestD2XXSerialAdapter(unittest.TestCase):
    def test_prefers_library_bundled_beside_frozen_module(self):
        with tempfile.TemporaryDirectory() as directory:
            bundled = Path(directory) / "libftd2xx.dylib"
            bundled.touch()
            with (
                patch.dict(os.environ, {"FTD2XX_LIBRARY": ""}),
                patch.object(d2xx_transport, "_BUNDLED_LIBRARY", bundled),
                patch.object(
                    d2xx_transport.ctypes.util, "find_library", return_value=None
                ),
                patch.object(d2xx_transport.glob, "glob", return_value=[]),
            ):
                candidates = list(d2xx_transport._library_candidates())

        self.assertEqual(candidates[0], str(bundled))

    def test_discovers_library_in_mounted_ftdi_disk_image(self):
        mounted = "/Volumes/dmg/release/build/libftd2xx.dylib"
        with (
            patch.dict(os.environ, {"FTD2XX_LIBRARY": ""}),
            patch.object(
                d2xx_transport.ctypes.util, "find_library", return_value=None
            ),
            patch.object(
                d2xx_transport.glob,
                "glob",
                side_effect=lambda pattern: [mounted]
                if pattern.endswith("/libftd2xx.dylib")
                else [],
            ),
        ):
            candidates = list(d2xx_transport._library_candidates())

        self.assertIn(mounted, candidates)

    def test_registers_custom_pid_and_configures_selected_device(self):
        library = FakeD2XX([{ "serial_number": "CTLV_21060012" }])

        adapter = D2XXSerialAdapter(library=library)

        self.assertTrue(adapter.is_open)
        self.assertEqual(adapter.serial_number, "CTLV_21060012")
        library.FT_SetVIDPID.assert_called_once_with(
            CTVIDEO_VENDOR_ID, CTVIDEO_PRODUCT_ID
        )
        library.FT_SetBaudRate.assert_called_once()
        self.assertEqual(library.FT_SetBaudRate.call_args.args[1], 115200)
        library.FT_SetLatencyTimer.assert_called_once()
        adapter.close()

    def test_exposes_pyserial_read_write_and_purge_surface(self):
        library = FakeD2XX(
            [{ "serial_number": "CTLV_21060012" }],
            read_data=b"\x04\xd2",
        )
        adapter = D2XXSerialAdapter("CTLV_21060012", library=library)

        adapter.reset_input_buffer()
        written = adapter.write(b"\x01")
        adapter.flush()
        received = adapter.read(2)

        self.assertEqual(written, 1)
        self.assertEqual(library.writes, [b"\x01"])
        self.assertEqual(received, b"\x04\xd2")
        self.assertEqual(library.FT_Purge.call_args.args[1], FT_PURGE_RX)
        adapter.close()
        self.assertFalse(adapter.is_open)

    def test_rejects_missing_custom_pid_device(self):
        with self.assertRaisesRegex(D2XXError, "VID:PID 0403:DE33"):
            D2XXSerialAdapter(library=FakeD2XX())

    def test_requires_serial_selector_when_multiple_devices_exist(self):
        library = FakeD2XX([
            {"serial_number": "CTLV_FIRST"},
            {"serial_number": "CTLV_SECOND"},
        ])

        with self.assertRaisesRegex(D2XXError, "Multiple CTvideo"):
            D2XXSerialAdapter(library=library)

    def test_accepts_old_port_value_as_auto_selection(self):
        library = FakeD2XX([{ "serial_number": "CTLV_21060012" }])

        adapter = D2XXSerialAdapter(
            "/dev/cu.usbserial-A9EQ7W68", library=library
        )

        self.assertEqual(adapter.serial_number, "CTLV_21060012")
        adapter.close()

    def test_ignores_unrelated_standard_ftdi_device(self):
        library = FakeD2XX([
            {
                "serial_number": "A9EQ7W68",
                "description": "FT232R USB UART",
                "device_id": (0x0403 << 16) | 0x6001,
            },
            {"serial_number": "CTLV_21060012"},
        ])

        adapter = D2XXSerialAdapter(library=library)

        self.assertEqual(adapter.serial_number, "CTLV_21060012")
        adapter.close()

    def test_recognizes_observed_ctvideo_serial_if_device_id_is_unavailable(self):
        library = FakeD2XX([{
            "serial_number": "CTLV_21060012",
            "device_id": 0,
        }])

        adapter = D2XXSerialAdapter(library=library)

        self.assertEqual(adapter.serial_number, "CTLV_21060012")
        adapter.close()


class TestCTVideoConnectionFactory(unittest.TestCase):
    @patch("plugins.devices.ctvideo_3m.macos_driver.CTVideo3MMacOS")
    def test_macos_factory_uses_d2xx_driver_and_verifies_reading(self, driver_class):
        device = MagicMock()
        driver_class.return_value = device

        with patch.object(connection.sys, "platform", "darwin"):
            result = connection.create_ctvideo("CTLV_21060012", verify=True)

        self.assertIs(result, device)
        driver_class.assert_called_once_with("CTLV_21060012")
        device.read_all.assert_called_once_with()

    @patch("plugins.devices.ctvideo_3m.macos_driver.CTVideo3MMacOS")
    def test_verification_failure_closes_device(self, driver_class):
        device = MagicMock()
        device.read_all.side_effect = TimeoutError("no response")
        driver_class.return_value = device

        with patch.object(connection.sys, "platform", "darwin"):
            with self.assertRaisesRegex(TimeoutError, "no response"):
                connection.create_ctvideo("auto", verify=True)

        device.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
