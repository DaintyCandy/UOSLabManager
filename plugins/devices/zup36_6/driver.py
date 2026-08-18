"""Hardware driver. Do not import or access Qt here."""


class DeviceDriver:
    def __init__(self, connection):
        self.connection = connection
        raise NotImplementedError("Implement the hardware connection")

    def read_all(self):
        return {"value": 0.0}

    def close(self):
        pass
