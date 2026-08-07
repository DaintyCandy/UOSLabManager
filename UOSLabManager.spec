# -*- mode: python ; coding: utf-8 -*-
import glob
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('plugins')

# Conda installs the Qt runtime in Library/bin instead of inside the PyQt6
# wheel directory expected by PyInstaller's standard hook.  Bundle those DLLs
# in the layout used by the PyQt6 runtime hook.
conda_qt_bin = os.path.join(sys.prefix, 'Library', 'bin')
qt_binaries = [
    (path, 'PyQt6/Qt6/bin')
    for path in glob.glob(os.path.join(conda_qt_bin, 'Qt6*.dll'))
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=qt_binaries,
    datas=[],
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
    a.binaries,
    a.datas,
    [],
    name='UOSLabManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
