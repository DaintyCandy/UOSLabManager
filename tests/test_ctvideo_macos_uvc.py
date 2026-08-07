import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from plugins.devices.ctvideo_3m import macos_uvc
from plugins.devices.ctvideo_3m.macos_uvc import MacOSUVCController


PROBE_OUTPUT = """\
CONTROL\tbrightness\tBrightness\t1\t1\t0\t255\t1\t118\t118
CONTROL\tgain\tGain\t0\t0\t-\t-\t-\t-\t-
CONTROL\tauto-exposure-mode\tAuto Exposure Mode\t0\t0\t-\t-\t-\t-\t-
"""


class TestMacOSUVCController(unittest.TestCase):
    def test_prefers_precompiled_bundled_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "macos_uvc_helper"
            helper.touch(mode=0o755)
            os.chmod(helper, 0o755)
            with patch.object(macos_uvc, "_BUNDLED_HELPER", helper):
                selected = macos_uvc._helper_binary()

        self.assertEqual(selected, helper)

    def test_missing_location_id_uses_unique_ctvideo_vid_pid_lookup(self):
        runner = MagicMock(return_value=SimpleNamespace(
            returncode=0, stdout=PROBE_OUTPUT, stderr="",
        ))
        controller = MacOSUVCController(
            None, helper="/tmp/fake-uvc-helper", runner=runner
        )

        controller.probe()

        command = runner.call_args.args[0]
        self.assertEqual(command[1], "0x00000000")

    def test_probe_reports_real_brightness_and_unsupported_gain(self):
        runner = MagicMock(return_value=SimpleNamespace(
            returncode=0, stdout=PROBE_OUTPUT, stderr="",
        ))
        controller = MacOSUVCController(
            0x02113100, helper="/tmp/fake-uvc-helper", runner=runner
        )

        controls = controller.probe()
        properties = controller.camera_properties()

        self.assertEqual(controls["Brightness"]["minimum"], 0)
        self.assertEqual(controls["Brightness"]["maximum"], 255)
        self.assertEqual(controls["Brightness"]["current"], 118)
        self.assertTrue(properties["brightness_supported"])
        self.assertFalse(properties["gain_supported"])
        self.assertIsNone(properties["auto_exposure"])
        command = runner.call_args.args[0]
        self.assertEqual(command[1], "0x02113100")

    def test_apply_sets_changed_brightness_and_checks_readback(self):
        applied_output = """\
SET\tbrightness\tOK\t130
CONTROL\tbrightness\tBrightness\t1\t1\t0\t255\t1\t118\t130
CONTROL\tgain\tGain\t0\t0\t-\t-\t-\t-\t-
"""
        runner = MagicMock(side_effect=[
            SimpleNamespace(returncode=0, stdout=PROBE_OUTPUT, stderr=""),
            SimpleNamespace(returncode=0, stdout=applied_output, stderr=""),
        ])
        controller = MacOSUVCController(
            0x02113100, helper="/tmp/fake-uvc-helper", runner=runner
        )
        controller.probe()

        results = controller.apply({"Brightness": 130, "Gain": 4})

        command = runner.call_args_list[1].args[0]
        self.assertIn("brightness=130", command)
        self.assertNotIn("gain=4", command)
        brightness = next(item for item in results if item["name"] == "Brightness")
        gain = next(item for item in results if item["name"] == "Gain")
        self.assertTrue(brightness["applied"])
        self.assertIn("readback=130", brightness["detail"])
        self.assertFalse(gain["applied"])
        self.assertIn("not advertised", gain["detail"])
        self.assertEqual(controller.controls["Brightness"]["current"], 130)

    def test_apply_rejects_value_outside_advertised_range(self):
        runner = MagicMock(return_value=SimpleNamespace(
            returncode=0, stdout=PROBE_OUTPUT, stderr="",
        ))
        controller = MacOSUVCController(
            0x02113100, helper="/tmp/fake-uvc-helper", runner=runner
        )
        controller.probe()

        results = controller.apply({"Brightness": 300})

        self.assertEqual(runner.call_count, 1)
        self.assertFalse(results[0]["applied"])
        self.assertIn("maximum=255", results[0]["detail"])

    def test_apply_does_not_write_unchanged_value(self):
        runner = MagicMock(return_value=SimpleNamespace(
            returncode=0, stdout=PROBE_OUTPUT, stderr="",
        ))
        controller = MacOSUVCController(
            0x02113100, helper="/tmp/fake-uvc-helper", runner=runner
        )
        controller.probe()

        results = controller.apply({"Brightness": 118})

        self.assertEqual(results, [])
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
