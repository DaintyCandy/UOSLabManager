class DeviceManager:
    def __init__(self):
        self.devices = {}

    def add_device(self, name: str, device):
        if name in self.devices:
            raise ValueError(f"{name} already exists")
        self.devices[name] = device

    def remove_device(self, name: str):
        dev = self.devices.pop(name, None)
        if dev is not None:
            dev.close()

    def get_device(self, name: str):
        return self.devices.get(name)

    def read_all(self):
        results = {}

        for name, dev in self.devices.items():
            try:
                results[name] = dev.read_all()
            except Exception as e:
                results[name] = {"error": str(e)}

        return results

    def close_all(self):
        for dev in self.devices.values():
            try:
                dev.close()
            except Exception:
                pass

        self.devices.clear()