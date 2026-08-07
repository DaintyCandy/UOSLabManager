# Internal macOS build

This build produces an ad-hoc-signed Apple Silicon application for use inside
the lab. It bundles the precompiled CTvideo UVC helper and the FTDI D2XX
library, so recipients do not need Python, PyInstaller, Xcode Command Line
Tools, or a separate D2XX installation.

## Build requirements

- Apple Silicon Mac
- Python 3.11 with the application's runtime dependencies
- PyInstaller 6.x
- Xcode Command Line Tools (`xcrun clang`)
- FTDI macOS `libftd2xx.dylib` available while building

The FTDI disk image can remain mounted. The build script searches its standard
`/Volumes/*/release/build/` location automatically.

## Build

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

## Installation on another lab Mac

1. Copy and unzip `UOSLabManager-macOS-arm64.zip`.
2. Move `UOSLabManager.app` to `/Applications` if desired.
3. On first launch, Control-click the app, choose **Open**, then confirm.
4. Approve the macOS camera permission prompt when camera preview is needed.

The app is ad-hoc signed rather than Apple-notarized. Gatekeeper may require
the Control-click **Open** step on each receiving Mac. No pyrometer or camera
is contacted until the operator explicitly presses Connect in the app.
