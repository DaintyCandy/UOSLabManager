# CTvideo 3M on macOS

The observed CTvideo unit exposes two sibling USB devices behind one hub:

- UVC camera: `093A:2900`, product `CMS_309I01 AA00000000`
- Pyrometer transport: `0403:DE33`, product `IR Online Video Sensor`, serial
  `CTLV_21060012`

The pyrometer uses a custom FTDI product ID, so macOS does not create a
`/dev/cu.*` device for it. The application accesses it through FTDI D2XX while
leaving the original pyserial driver and Windows camera resolver unchanged.

## Required D2XX library

Download the current macOS ARM64 D2XX package from FTDI:

<https://ftdichip.com/drivers/d2xx-drivers/>

The application searches these locations automatically:

- `/usr/local/lib/libftd2xx.dylib`
- `/usr/local/lib/libftd2xx.1.4.35.dylib`
- `/usr/local/lib/libftd2xx.1.4.30.dylib`
- `/opt/homebrew/lib/libftd2xx.dylib`
- `/Volumes/*/release/build/libftd2xx.dylib` (mounted FTDI disk image)
- `/Volumes/*/release/build/libftd2xx.*.dylib` (versioned file in the image)

It can also use an unpacked library without a system-wide installation:

```bash
export FTD2XX_LIBRARY="/absolute/path/to/libftd2xx.dylib"
python3 main.py
```

For the mounted FTDI 1.4.35 disk image used during development, the command is:

```bash
export FTD2XX_LIBRARY="/Volumes/dmg/release/build/libftd2xx.dylib"
python3 main.py
```

The CTvideo connection field accepts `auto`, `CTLV_21060012`, or
`d2xx://CTLV_21060012`. Use `auto` when only one CTvideo is connected.

## First hardware verification

Hardware verification must be started manually by the operator. Before
clicking Connect:

1. Supply the CTvideo electronics as required by the device installation
   (the datasheet specifies 8-36 V DC).
2. Connect the CTvideo USB cable directly or through the known working hub.
3. Set the application connection field to `auto`.
4. Click Connect once and record the complete error message if it fails.

The macOS connection factory performs one read-only temperature verification
before it marks the device connected or starts its camera.

## Camera preview and controls

OpenCV uses the AVFoundation backend for the camera preview. The repository
also contains a native IOKit diagnostic helper for standard UVC
GET/SET/read-back operations; it opens only the camera's VideoControl
interface and does not seize or reset the USB device.

The application UI intentionally does not expose generic UVC brightness,
gain, exposure, or ROI controls. Video Gain and Anti-flicker are
CompactConnect vendor Extension Unit settings, not standard UVC controls, and
the current implementation accesses that vendor XU only through Windows
DirectShow. They therefore remain unavailable on macOS instead of being
silently mapped to unrelated standard UVC properties.

The sensor and camera are normally paired by their shared USB container. If
the D2XX-open sensor is temporarily absent from the I/O Registry, the macOS
resolver falls back only when exactly one `093A:2900` camera is present. The
native helper applies the same unique-device rule when a USB location ID was
not available, so a generic OpenCV preview fallback does not disable otherwise
supported controls. Multiple matching cameras remain an explicit error rather
than risking control of the wrong unit.

## Information needed if the D2XX device opens but times out

Connect the CTvideo to Windows and provide screenshots from CompactConnect of:

- the Device Selection row showing serial number and baud rate;
- Device Setup > USB Communication, including baud rate and checksum state;
- the CompactConnect version and CTvideo firmware revision.

The current protocol uses 115200 baud and the command framing implemented in
`driver.py`. Baud or checksum settings that differ from those assumptions need
to be handled in the macOS connection layer after they are confirmed.
