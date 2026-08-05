"""macOS CTvideo driver using the FTDI D2XX transport."""

import threading

from .d2xx_transport import D2XXSerialAdapter
from .driver import CTVideo3M


class CTVideo3MMacOS(CTVideo3M):
    """Reuse the CTvideo binary protocol over its custom FTDI USB interface."""

    def __init__(self, selector="auto", library=None):
        self.ser = D2XXSerialAdapter(selector=selector, library=library)
        self._lock = threading.RLock()
