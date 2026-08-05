"""Platform-specific CTvideo connection factory."""

import sys


def default_connection():
    return "auto" if sys.platform == "darwin" else "COM6"


def create_ctvideo(connection, verify=False):
    if sys.platform == "darwin":
        from .macos_driver import CTVideo3MMacOS

        device = CTVideo3MMacOS(connection)
    else:
        from .driver import CTVideo3M

        device = CTVideo3M(connection)

    if verify:
        try:
            device.read_all()
        except Exception:
            device.close()
            raise
    return device
