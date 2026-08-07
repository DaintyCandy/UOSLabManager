#!/usr/bin/env python3
"""Build an internal, ad-hoc-signed Apple Silicon UOSLabManager app."""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NATIVE_DIR = PROJECT_ROOT / "build" / "macos-native"
UVC_SOURCE = (
    PROJECT_ROOT / "plugins/devices/ctvideo_3m/macos_uvc_helper.c"
)
UVC_HELPER = NATIVE_DIR / "macos_uvc_helper"
APP = PROJECT_ROOT / "dist" / "UOSLabManager.app"
ARCHIVE = PROJECT_ROOT / "dist" / "UOSLabManager-macOS-arm64.zip"


def run(command, *, env=None):
    printable = " ".join(str(item) for item in command)
    print(f"+ {printable}", flush=True)
    subprocess.run(
        [str(item) for item in command],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
    )


def find_d2xx(explicit):
    candidates = [explicit, os.environ.get("FTD2XX_LIBRARY", "")]
    for pattern in (
        "/Volumes/*/release/build/libftd2xx.dylib",
        "/Volumes/*/release/build/libftd2xx.*.dylib",
    ):
        candidates.extend(sorted(glob.glob(pattern)))
    candidates.extend(
        [
            "/usr/local/lib/libftd2xx.dylib",
            "/opt/homebrew/lib/libftd2xx.dylib",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise SystemExit(
        "libftd2xx.dylib was not found. Mount the FTDI macOS D2XX image or "
        "pass --d2xx /absolute/path/libftd2xx.dylib."
    )


def require_tool(name):
    path = shutil.which(name)
    if path is None:
        raise SystemExit(f"Required macOS build tool is unavailable: {name}")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build UOSLabManager.app for internal Apple Silicon use."
    )
    parser.add_argument(
        "--d2xx",
        help="Path to FTDI libftd2xx.dylib; mounted images are auto-detected.",
    )
    parser.add_argument(
        "--skip-tests", action="store_true", help="Skip the unittest suite."
    )
    args = parser.parse_args(argv)

    if sys.platform != "darwin":
        raise SystemExit("The macOS app must be built on macOS.")
    if platform.machine() != "arm64":
        raise SystemExit(
            "This build recipe targets Apple Silicon. Build on an arm64 Mac."
        )

    require_tool("xcrun")
    require_tool("codesign")
    require_tool("ditto")
    d2xx = find_d2xx(args.d2xx)

    try:
        run([sys.executable, "-m", "PyInstaller", "--version"])
    except subprocess.CalledProcessError as error:
        raise SystemExit(
            "PyInstaller is missing. Install it with: "
            f"{sys.executable} -m pip install pyinstaller"
        ) from error

    if not args.skip_tests:
        run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_*.py",
            ]
        )

    NATIVE_DIR.mkdir(parents=True, exist_ok=True)
    run(
        [
            "xcrun",
            "clang",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            UVC_SOURCE,
            "-o",
            UVC_HELPER,
            "-framework",
            "IOKit",
            "-framework",
            "CoreFoundation",
        ]
    )

    build_environment = os.environ.copy()
    build_environment["CTVIDEO_UVC_HELPER"] = str(UVC_HELPER)
    build_environment["FTD2XX_LIBRARY"] = str(d2xx)
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            PROJECT_ROOT / "UOSLabManager.spec",
        ],
        env=build_environment,
    )

    run(["codesign", "--force", "--deep", "--sign", "-", APP])
    run(
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            "--verbose=2",
            APP,
        ]
    )

    ARCHIVE.unlink(missing_ok=True)
    run(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            APP,
            ARCHIVE,
        ]
    )
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    print(f"\nBuilt app: {APP}")
    print(f"Archive:   {ARCHIVE}")
    print(f"SHA-256:   {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
