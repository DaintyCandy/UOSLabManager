# CTvideo 3M plug-in structure

The plug-in separates the pyrometer protocol, camera path, and user interface.

## Entry points

- `plugin.py`: device plug-in metadata and connection entry point.
- `connection.py`: selects the platform transport and creates `CTVideo3M`.
- `panel.py`: the actual CTvideo settings and monitoring panel.

## Pyrometer communication

- `driver.py`: platform-independent CTvideo binary command protocol.
- `d2xx_transport.py`: macOS serial-like adapter for the FTDI D2XX API.

`driver.py` normally opens a pyserial port. On macOS, `connection.py` injects a
`D2XXSerialAdapter` into the same protocol driver. There is deliberately no
separate macOS protocol subclass.

## Camera and video

- `video.py`: OpenCV capture worker, shared preview widget, and camera-control
  request queue.
- `video_display.py`: pure validation and frame-processing functions.
- `usb_camera.py`: platform-neutral camera resolver entry point.
- `resolvers/windows.py`: Windows sibling-camera lookup.
- `resolvers/macos.py`: macOS USB-container and AVFoundation lookup.
- `compactconnect_camera.py`: Windows CompactConnect vendor Extension Unit
  controller.
- `ks_probe.py`: low-level Windows DirectShow/KS access used by the vendor
  controller.
- `macos_uvc.py` and `macos_uvc_helper.c`: macOS standard-UVC diagnostic tool;
  these do not implement CompactConnect vendor controls.

Device-specific video code lives in this package instead of `gui/`. The
top-level GUI package should contain only application-wide widgets and panels.
