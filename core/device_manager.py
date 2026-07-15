import copy
import queue
import threading
import time


class DeviceProxy:
    """Route every explicit device command through its dedicated worker."""

    def __init__(self, worker):
        self._worker = worker

    def __getattr__(self, name):
        return lambda *args, **kwargs: self._worker.call(name, *args, **kwargs)


class DeviceWorker(threading.Thread):
    def __init__(self, name, factory, update_callback, failure_callback, interval=1.0):
        super().__init__(name=f"DeviceWorker-{name}", daemon=True)
        self.device_name = name
        self.factory = factory
        self.update_callback = update_callback
        self.failure_callback = failure_callback
        self.interval = interval
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.startup_error = None
        self.device = None

    def run(self):
        try:
            self.device = self.factory() if callable(self.factory) else self.factory
        except Exception as error:
            self.startup_error = error
            self.ready.set()
            return
        self.ready.set()
        next_poll = time.monotonic()
        try:
            while not self.stop_event.is_set():
                timeout = max(0.0, next_poll - time.monotonic())
                try:
                    command = self.commands.get(timeout=timeout)
                except queue.Empty:
                    command = None
                if command is not None:
                    self._execute(command)
                    continue
                started = time.perf_counter()
                try:
                    values = self.device.read_all()
                    if not isinstance(values, dict):
                        raise TypeError("read_all() must return a dictionary")
                    response_ms = (time.perf_counter() - started) * 1000.0
                    self.update_callback(self.device_name, self, values, response_ms)
                except Exception as error:
                    self.failure_callback(self.device_name, self, error)
                    break
                next_poll = time.monotonic() + self.interval
        finally:
            self._fail_pending(RuntimeError(f"{self.device_name} is disconnected"))
            try:
                if self.device is not None:
                    self.device.close()
            except Exception:
                pass

    def _execute(self, command):
        method_name, args, kwargs, completed, result = command
        try:
            result["value"] = getattr(self.device, method_name)(*args, **kwargs)
        except Exception as error:
            result["error"] = error
        finally:
            completed.set()

    def _fail_pending(self, error):
        while True:
            try:
                _, _, _, completed, result = self.commands.get_nowait()
            except queue.Empty:
                return
            result["error"] = error
            completed.set()

    def call(self, method_name, *args, **kwargs):
        if self.stop_event.is_set() or not self.is_alive():
            raise RuntimeError(f"{self.device_name} is disconnected")
        completed = threading.Event()
        result = {}
        self.commands.put((method_name, args, kwargs, completed, result))
        if not completed.wait(15.0):
            raise TimeoutError(f"{self.device_name} command timed out: {method_name}")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def stop(self):
        self.stop_event.set()


class DeviceManager:
    def __init__(self):
        self.devices = {}
        self.workers = {}
        self.latest = {}
        self.telemetry = {}
        self.disconnect_errors = {}
        self.lock = threading.RLock()

    def add_device(self, name: str, device_or_factory):
        with self.lock:
            if name in self.devices:
                raise ValueError(f"{name} already exists")
            worker = DeviceWorker(name, device_or_factory, self._updated, self._failed)
            self.workers[name] = worker
            self.devices[name] = DeviceProxy(worker)
            self.telemetry[name] = {"response_ms": None, "updated_at": None}
        worker.start()
        if not worker.ready.wait(10.0):
            self.remove_device(name)
            raise TimeoutError(f"{name} connection timed out")
        if worker.startup_error is not None:
            with self.lock:
                self.devices.pop(name, None)
                self.workers.pop(name, None)
                self.telemetry.pop(name, None)
            raise worker.startup_error

    def _updated(self, name, worker, values, response_ms):
        with self.lock:
            if self.workers.get(name) is not worker:
                return
            self.latest[name] = copy.deepcopy(values)
            self.telemetry[name] = {
                "response_ms": response_ms,
                "updated_at": time.monotonic(),
            }
            self.disconnect_errors.pop(name, None)

    def _failed(self, name, worker, error):
        with self.lock:
            if self.workers.get(name) is not worker:
                return
            self.devices.pop(name, None)
            self.workers.pop(name, None)
            self.latest.pop(name, None)
            self.telemetry.pop(name, None)
            self.disconnect_errors[name] = str(error)
        worker.stop()

    def remove_device(self, name: str):
        with self.lock:
            self.devices.pop(name, None)
            worker = self.workers.pop(name, None)
            self.latest.pop(name, None)
            self.telemetry.pop(name, None)
        if worker is not None:
            worker.stop()

    def get_device(self, name: str):
        with self.lock:
            return self.devices.get(name)

    def get_latest(self, name: str):
        with self.lock:
            return copy.deepcopy(self.latest.get(name, {}))

    def get_metrics(self, name: str):
        with self.lock:
            connected = name in self.devices
            telemetry = self.telemetry.get(name, {})
            updated_at = telemetry.get("updated_at")
            return {
                "connected": connected,
                "realtime": bool(connected and updated_at is not None and time.monotonic() - updated_at < 2.5),
                "response_ms": telemetry.get("response_ms"),
                "age_ms": None if updated_at is None else (time.monotonic() - updated_at) * 1000.0,
                "error": self.disconnect_errors.get(name, ""),
            }

    def read_all(self):
        with self.lock:
            return {
                name: copy.deepcopy(self.latest.get(name, {}))
                for name in self.devices
            }

    def close_all(self):
        with self.lock:
            workers = list(self.workers.values())
            self.devices.clear()
            self.workers.clear()
            self.latest.clear()
            self.telemetry.clear()
        for worker in workers:
            worker.stop()
