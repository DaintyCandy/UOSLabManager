"""Hardware-free driver used by validation and tests."""


class MockDeviceDriver:
    def __init__(self, _connection="mock"):
        self.closed = False

    def read_all(self):
        return {"value": 0.0}

    def close(self):
        self.closed = True
