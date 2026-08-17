import threading
import time
import unittest

from core.device_manager import DeviceManager


class ThreadReportingDevice:
    def __init__(self):
        self.created_on = threading.current_thread().name
        self.closed = False

    def read_all(self):
        return {"worker": threading.current_thread().name}

    def command_thread(self):
        return threading.current_thread().name

    def close(self):
        self.closed = True


class DeviceManagerThreadTests(unittest.TestCase):
    def test_each_device_owns_a_distinct_worker_thread(self):
        manager = DeviceManager()
        created = {}

        def factory(device_id):
            def create():
                device = ThreadReportingDevice()
                created[device_id] = device
                return device
            return create

        try:
            manager.add_device("DEVICE_A", factory("DEVICE_A"), interval=0.01)
            manager.add_device("DEVICE_B", factory("DEVICE_B"), interval=0.01)

            worker_a = manager.workers["DEVICE_A"]
            worker_b = manager.workers["DEVICE_B"]
            self.assertIsNot(worker_a, worker_b)
            self.assertTrue(worker_a.is_alive())
            self.assertTrue(worker_b.is_alive())
            self.assertEqual(worker_a.name, "DeviceWorker-DEVICE_A")
            self.assertEqual(worker_b.name, "DeviceWorker-DEVICE_B")
            self.assertEqual(created["DEVICE_A"].created_on, worker_a.name)
            self.assertEqual(created["DEVICE_B"].created_on, worker_b.name)
            self.assertEqual(
                manager.get_metrics("DEVICE_A")["worker_name"], worker_a.name
            )
            self.assertTrue(manager.get_metrics("DEVICE_A")["worker_alive"])
            self.assertEqual(
                manager.get_device("DEVICE_A").command_thread(), worker_a.name
            )
            self.assertEqual(
                manager.get_device("DEVICE_B").command_thread(), worker_b.name
            )
            deadline = time.monotonic() + 1.0
            snapshot = manager.read_snapshot()
            while (
                snapshot["devices"]["DEVICE_A"]["sample_id"] < 1
                and time.monotonic() < deadline
            ):
                time.sleep(0.005)
                snapshot = manager.read_snapshot()
            sample = snapshot["devices"]["DEVICE_A"]
            self.assertGreaterEqual(sample["sample_id"], 1)
            self.assertTrue(sample["sampled_at_utc"].endswith("Z"))
            self.assertTrue(sample["fresh"])
        finally:
            manager.close_all()

        self.assertTrue(created["DEVICE_A"].closed)
        self.assertTrue(created["DEVICE_B"].closed)


if __name__ == "__main__":
    unittest.main()
