"""Platform-neutral entry point for CTvideo camera resolution."""

import sys


def resolve_camera_for_port(port: str) -> dict:
    if sys.platform == "win32":
        from .resolvers.windows import resolve_camera
    elif sys.platform == "darwin":
        from .resolvers.macos import resolve_camera
    else:
        raise RuntimeError(f"CTvideo camera resolution is unsupported on {sys.platform}.")
    return resolve_camera(port)
