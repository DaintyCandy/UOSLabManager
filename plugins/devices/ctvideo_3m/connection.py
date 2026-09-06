"""Platform-specific CTvideo connection factory."""

import sys

from .d2xx_transport import D2XXSerialAdapter
from .driver import CTVideo3M


def default_connection():
    return "auto" if sys.platform == "darwin" else "COM6"


def create_ctvideo(
    connection, verify=False, *, baudrate=115200, timeout=0.5,
):
    if sys.platform == "darwin":
        transport = D2XXSerialAdapter(
            selector=connection, baudrate=baudrate, timeout=timeout
        )
        device = CTVideo3M(transport=transport)
    else:
        device = CTVideo3M(
            connection, baudrate=baudrate, timeout=timeout
        )

    if verify:
        try:
            device.read_all()
        except Exception:
            device.close()
            raise
    return device
