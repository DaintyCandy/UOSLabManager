"""Native macOS UVC controls used alongside AVFoundation capture."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import threading


class MacOSUVCError(RuntimeError):
    pass


_BUILD_LOCK = threading.Lock()
_SOURCE = Path(__file__).with_name("macos_uvc_helper.c")
_BUNDLED_HELPER = Path(__file__).with_name("macos_uvc_helper")
_SETTING_KEYS = {
    "Brightness": "brightness",
    "Contrast": "contrast",
    "Gain": "gain",
    "Power Line": "power-line",
    "Hue": "hue",
    "Saturation": "saturation",
    "Sharpness": "sharpness",
    "Gamma": "gamma",
    "Auto Exposure Mode": "auto-exposure-mode",
    "Auto Exposure Priority": "auto-exposure-priority",
    "Exposure Absolute": "exposure-absolute",
}


def _helper_binary():
    if _BUNDLED_HELPER.is_file() and os.access(_BUNDLED_HELPER, os.X_OK):
        return _BUNDLED_HELPER
    try:
        source = _SOURCE.read_bytes()
    except OSError as error:
        raise MacOSUVCError(f"macOS UVC helper source is unavailable: {error}") from error
    digest = hashlib.sha256(source).hexdigest()[:16]
    binary = Path(tempfile.gettempdir()) / f"uoslabmanager-ctvideo-uvc-{digest}"
    if binary.is_file():
        return binary

    with _BUILD_LOCK:
        if binary.is_file():
            return binary
        temporary = binary.with_name(f"{binary.name}.{os.getpid()}.tmp")
        command = [
            "xcrun", "clang", "-std=c11", "-O2", str(_SOURCE),
            "-o", str(temporary), "-framework", "IOKit",
            "-framework", "CoreFoundation",
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise MacOSUVCError(
                f"Could not build the macOS UVC helper: {error}"
            ) from error
        if result.returncode != 0:
            temporary.unlink(missing_ok=True)
            detail = result.stderr.strip() or result.stdout.strip() or "clang failed"
            raise MacOSUVCError(f"Could not build the macOS UVC helper: {detail}")
        try:
            os.replace(temporary, binary)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise MacOSUVCError(
                f"Could not install the temporary macOS UVC helper: {error}"
            ) from error
    return binary


def _optional_integer(value):
    return None if value == "-" else int(value)


def _parse_output(output):
    controls = {}
    updates = {}
    for line in output.splitlines():
        fields = line.rstrip("\n").split("\t")
        if not fields:
            continue
        if fields[0] == "CONTROL" and len(fields) == 10:
            key, display_name = fields[1], fields[2]
            controls[display_name] = {
                "key": key,
                "supported": fields[3] == "1",
                "settable": fields[4] == "1",
                "minimum": _optional_integer(fields[5]),
                "maximum": _optional_integer(fields[6]),
                "step": _optional_integer(fields[7]),
                "default": _optional_integer(fields[8]),
                "current": _optional_integer(fields[9]),
            }
        elif fields[0] == "SET" and len(fields) == 4:
            updates[fields[1]] = {
                "status": fields[2],
                "readback": _optional_integer(fields[3]),
            }
    return controls, updates


class MacOSUVCController:
    """Probe/update UVC controls by location, or by a unique CTvideo VID:PID."""

    def __init__(self, location_id, helper=None, runner=None):
        self.location_id = int(location_id or 0)
        self._helper = Path(helper) if helper is not None else _helper_binary()
        self._runner = runner or subprocess.run
        self.controls = {}

    def _execute(self, assignments=()):
        command = [str(self._helper), f"0x{self.location_id:08x}"]
        command.extend(assignments)
        try:
            result = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise MacOSUVCError(f"macOS UVC helper failed: {error}") from error
        controls, updates = _parse_output(result.stdout)
        if controls:
            self.controls = controls
        if result.returncode not in (0, 3):
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise MacOSUVCError(f"macOS UVC helper failed: {detail}")
        return updates

    def probe(self):
        self._execute()
        if not self.controls:
            raise MacOSUVCError("The camera returned no UVC control information.")
        return self.controls

    def apply(self, values):
        if not self.controls:
            self.probe()
        assignments = []
        attempted = []
        results = []
        for display_name, key in _SETTING_KEYS.items():
            if display_name not in values:
                continue
            metadata = self.controls.get(display_name, {})
            requested = int(values[display_name])
            if not metadata.get("supported") or not metadata.get("settable"):
                results.append({
                    "name": display_name,
                    "applied": False,
                    "detail": "not advertised as writable by this camera",
                })
                continue
            if metadata.get("current") == requested:
                continue
            minimum, maximum = metadata.get("minimum"), metadata.get("maximum")
            if minimum is not None and requested < minimum:
                results.append({
                    "name": display_name,
                    "applied": False,
                    "detail": f"requested={requested}, minimum={minimum}",
                })
                continue
            if maximum is not None and requested > maximum:
                results.append({
                    "name": display_name,
                    "applied": False,
                    "detail": f"requested={requested}, maximum={maximum}",
                })
                continue
            assignments.append(f"{key}={requested}")
            attempted.append((display_name, key, requested))

        updates = self._execute(assignments) if assignments else {}
        for display_name, key, requested in attempted:
            update = updates.get(key, {"status": "FAILED", "readback": None})
            readback = update["readback"]
            applied = update["status"] == "OK" and readback == requested
            results.append({
                "name": display_name,
                "applied": applied,
                "detail": (
                    f"requested={requested}, readback={readback}"
                    if readback is not None
                    else f"requested={requested}, status={update['status']}"
                ),
            })
        return results

    def camera_properties(self):
        if not self.controls:
            self.probe()
        brightness = self.controls.get("Brightness", {})
        gain = self.controls.get("Gain", {})
        exposure = self.controls.get("Auto Exposure Mode", {})
        exposure_value = exposure.get("current")
        return {
            "gain_supported": bool(gain.get("supported") and gain.get("settable")),
            "gain": gain.get("current"),
            "gain_min": gain.get("minimum"),
            "gain_max": gain.get("maximum"),
            "gain_step": gain.get("step"),
            "brightness_supported": bool(
                brightness.get("supported") and brightness.get("settable")
            ),
            "brightness": brightness.get("current"),
            "brightness_min": brightness.get("minimum"),
            "brightness_max": brightness.get("maximum"),
            "brightness_step": brightness.get("step"),
            "exposure_supported": bool(exposure.get("supported")),
            "auto_exposure": (
                exposure_value != 1
                if exposure.get("supported") and exposure_value is not None
                else None
            ),
            "auto_exposure_raw": exposure_value,
            "uvc_controls": self.controls,
        }
