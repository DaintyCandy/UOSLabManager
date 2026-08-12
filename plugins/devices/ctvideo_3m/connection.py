"""Platform-specific CTvideo connection factory."""

import sys

from .d2xx_transport import D2XXSerialAdapter
from .driver import CTVideo3M


def default_connection():
    return "auto" if sys.platform == "darwin" else "COM6"


def create_ctvideo(connection, verify=False):
    if sys.platform == "darwin":
        transport = D2XXSerialAdapter(selector=connection)
        device = CTVideo3M(transport=transport)
    else:
        device = CTVideo3M(connection)

    if verify:
        try:
            device.read_all()
        except Exception:
            device.close()
            raise
    return device
