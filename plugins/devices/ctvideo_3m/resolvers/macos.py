"""macOS CTvideo resolver boundary.

Kept separate so an IOKit/AVFoundation Container-equivalent resolver can be
implemented without changing the Windows PnP implementation.
"""


def resolve_camera(port: str) -> dict:
    raise RuntimeError(
        f"Automatic CTvideo camera resolution for {port} is not implemented on macOS yet."
    )
