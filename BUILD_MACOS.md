# Internal macOS build

This build produces ad-hoc-signed Apple Silicon or Intel applications for use
inside the lab. It bundles the precompiled CTvideo UVC helper and the FTDI
D2XX library, so recipients do not need Python, PyInstaller, Xcode Command
Line Tools, or a separate D2XX installation.

## Build requirements

- macOS (Apple Silicon can build both variants when Rosetta is installed)
- Python 3.11 with the application's runtime dependencies
- PyInstaller 6.x
- Xcode Command Line Tools (`xcrun clang`)
- FTDI macOS `libftd2xx.dylib` available while building

The FTDI disk image can remain mounted. The build script searches its standard
`/Volumes/*/release/build/` location automatically.

## Build for Apple Silicon

```bash
python3 -m pip install pyinstaller
python3 scripts/build_macos_app.py
```

If automatic D2XX discovery fails:

```bash
python3 scripts/build_macos_app.py \
  --d2xx /absolute/path/to/libftd2xx.dylib
```

Outputs:

- `dist/UOSLabManager.app`
- `dist/UOSLabManager-macOS-arm64.zip`

## Build for Intel

The Python process and every native Python package must be x86_64. On Apple
Silicon, create and use a separate Intel environment through Rosetta:

```bash
arch -x86_64 python3 -m venv /private/tmp/uoslabmanager-x86_64
arch -x86_64 /private/tmp/uoslabmanager-x86_64/bin/python -m pip install \
  pyinstaller==6.21.0 PyQt6==6.7.1 numpy==1.26.4 \
  opencv-python==4.10.0.84 pyqtgraph==0.14.0 pyserial==3.5 \
  PyVISA==1.16.2 pyqtdarktheme==2.1.0
arch -x86_64 /private/tmp/uoslabmanager-x86_64/bin/python \
  scripts/build_macos_app.py --arch x86_64
```

Intel outputs:

- `dist/UOSLabManager-Intel.app`
- `dist/UOSLabManager-macOS-x86_64.zip`

The pinned Intel dependencies target macOS 11 or newer.

## Installation on another lab Mac

1. Choose `UOSLabManager-macOS-arm64.zip` for Apple Silicon or
   `UOSLabManager-macOS-x86_64.zip` for Intel, then copy and unzip it.
2. Move `UOSLabManager.app` to `/Applications` if desired.
3. On first launch, Control-click the app, choose **Open**, then confirm.
4. Approve the macOS camera permission prompt when camera preview is needed.

The app is ad-hoc signed rather than Apple-notarized. Gatekeeper may require
the Control-click **Open** step on each receiving Mac. No pyrometer or camera
is contacted until the operator explicitly presses Connect in the app.
