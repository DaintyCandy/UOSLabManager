# -*- mode: python ; coding: utf-8 -*-
import glob
import os
import shutil
import sys
from importlib.metadata import PackageNotFoundError, distribution

from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('serial')
hiddenimports += collect_submodules('openai_codex')
codex_datas, codex_binaries, codex_cli_hiddenimports = collect_all(
    'codex_cli_bin', include_py_files=True
)
hiddenimports += codex_cli_hiddenimports

license_packages = (
    'PyQt6', 'PyQt6-sip', 'pyqtgraph', 'pyqtdarktheme', 'pyserial',
    'PyVISA', 'opencv-python', 'numpy', 'PyInstaller',
)
third_party_license_files = []
for package_name in license_packages:
    try:
        package = distribution(package_name)
    except PackageNotFoundError:
        continue
    package_destination = os.path.join(
        'licenses', f'{package.metadata["Name"]}-{package.version}'
    )
    for relative_path in package.files or ():
        basename = os.path.basename(str(relative_path)).lower()
        if not any(
            marker in basename for marker in ('license', 'copying', 'notice')
        ):
            continue
        source = package.locate_file(relative_path)
        if source.is_file():
            destination = os.path.join(
                package_destination, os.path.dirname(str(relative_path))
            )
            third_party_license_files.append((str(source), destination))

conda_qt_bin = os.path.join(sys.prefix, 'Library', 'bin')
qt_binaries = [
    (path, 'PyQt6/Qt6/bin')
    for path in glob.glob(os.path.join(conda_qt_bin, 'Qt6*.dll'))
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[*qt_binaries, *codex_binaries],
    datas=[
        ('LICENSE', '.'),
        ('THIRD_PARTY_NOTICES.md', '.'),
        ('assets/uoslabmanager_icon.png', 'assets'),
        ('core/experiment_context.py', '_codex_context/core'),
        ('core/device_manager.py', '_codex_context/core'),
        ('core/plugin_manager.py', '_codex_context/core'),
        ('gui/panel_camera.py', '_codex_context/gui'),
        *third_party_license_files,
        *codex_datas,
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PySide2', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='UOSLabManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='assets/uoslabmanager_icon.ico',
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='UOSLabManager',
)

# Keep editable plug-ins visible beside UOSLabManager.exe instead of placing
# them in PyInstaller's internal contents directory.
external_plugin_dir = os.path.join(DISTPATH, 'UOSLabManager', 'plugins')
shutil.copytree(
    'plugins', external_plugin_dir, dirs_exist_ok=True,
    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'),
)
