#!/usr/bin/env python3
"""Build an internal, ad-hoc-signed macOS UOSLabManager app."""

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
UVC_SOURCE = (
    PROJECT_ROOT / "plugins/devices/ctvideo_3m/macos_uvc_helper.c"
)
SUPPORTED_ARCHITECTURES = ("arm64", "x86_64")


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


def require_architecture(path, architecture):
    result = subprocess.run(
        ["lipo", str(path), "-verify_arch", architecture],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SystemExit(
            f"{path} does not contain the required {architecture} code. "
            f"{detail}"
        )


def build_paths(architecture):
    native_dir = PROJECT_ROOT / "build" / "macos-native" / architecture
    helper = native_dir / "macos_uvc_helper"
    app_name = (
        "UOSLabManager.app"
        if architecture == "arm64"
        else "UOSLabManager-Intel.app"
    )
    app = PROJECT_ROOT / "dist" / app_name
    archive = (
        PROJECT_ROOT
        / "dist"
        / f"UOSLabManager-macOS-{architecture}.zip"
    )
    return native_dir, helper, app, archive


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build UOSLabManager.app for internal macOS use."
    )
    parser.add_argument(
        "--d2xx",
        help="Path to FTDI libftd2xx.dylib; mounted images are auto-detected.",
    )
    parser.add_argument(
        "--arch",
        choices=SUPPORTED_ARCHITECTURES,
        default=platform.machine(),
        help="Target architecture (default: the running Python architecture).",
    )
    parser.add_argument(
        "--skip-tests", action="store_true", help="Skip the unittest suite."
    )
    args = parser.parse_args(argv)

    if sys.platform != "darwin":
        raise SystemExit("The macOS app must be built on macOS.")
    if platform.machine() != args.arch:
        raise SystemExit(
            f"The running Python is {platform.machine()}, but --arch is "
            f"{args.arch}. Run this script with a {args.arch} Python "
            "environment. On Apple Silicon, prefix an Intel Python command "
            "with: arch -x86_64"
        )

    require_tool("xcrun")
    require_tool("codesign")
    require_tool("ditto")
    require_tool("lipo")
    d2xx = find_d2xx(args.d2xx)
    require_architecture(d2xx, args.arch)
    native_dir, uvc_helper, app, archive = build_paths(args.arch)

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

    native_dir.mkdir(parents=True, exist_ok=True)
    run(
        [
            "xcrun",
            "clang",
            "-arch",
            args.arch,
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            UVC_SOURCE,
            "-o",
            uvc_helper,
            "-framework",
            "IOKit",
            "-framework",
            "CoreFoundation",
        ]
    )
    require_architecture(uvc_helper, args.arch)

    build_environment = os.environ.copy()
    build_environment["CTVIDEO_UVC_HELPER"] = str(uvc_helper)
    build_environment["FTD2XX_LIBRARY"] = str(d2xx)
    build_environment["PYINSTALLER_TARGET_ARCH"] = args.arch
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

    run(["codesign", "--force", "--deep", "--sign", "-", app])
    run(
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            "--verbose=2",
            app,
        ]
    )

    archive.unlink(missing_ok=True)
    run(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            app,
            archive,
        ]
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    print(f"\nArchitecture: {args.arch}")
    print(f"Built app:   {app}")
    print(f"Archive:     {archive}")
    print(f"SHA-256:     {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
