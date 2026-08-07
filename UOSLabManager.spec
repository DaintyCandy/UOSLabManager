# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH)
native_dir = project_root / "build" / "macos-native"
helper = Path(
    os.environ.get("CTVIDEO_UVC_HELPER", native_dir / "macos_uvc_helper")
)
d2xx = Path(os.environ.get("FTD2XX_LIBRARY", ""))

if not helper.is_file():
    raise SystemExit(
        "Precompiled CTvideo UVC helper is missing. "
        "Run scripts/build_macos_app.py instead of invoking the spec directly."
    )
if not d2xx.is_file():
    raise SystemExit(
        "FTD2XX_LIBRARY must point to the FTDI macOS libftd2xx.dylib. "
        "Run scripts/build_macos_app.py --d2xx /absolute/path/libftd2xx.dylib."
    )

hidden_imports = sorted(
    set(
        collect_submodules("plugins.devices")
        + collect_submodules("plugins.experiments")
    )
)
package_destination = "plugins/devices/ctvideo_3m"

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[
        (str(helper), package_destination),
        (str(d2xx), package_destination),
    ],
    datas=[
        (
            str(
                project_root
                / "plugins/devices/ctvideo_3m/macos_uvc_helper.c"
            ),
            package_destination,
        ),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UOSLabManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="UOSLabManager",
)
app = BUNDLE(
    coll,
    name="UOSLabManager.app",
    icon=None,
    bundle_identifier="kr.ac.uos.UOSLabManager",
    info_plist={
        "CFBundleDisplayName": "UOSLabManager",
        "CFBundleShortVersionString": "0.1.0",
        "NSCameraUsageDescription": (
            "CTvideo and laboratory camera previews require camera access."
        ),
        "NSHighResolutionCapable": True,
    },
)
