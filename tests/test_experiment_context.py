import unittest

from core.experiment_context import ExperimentContext


class FakeManager:
    def get_device(self, name):
        return f"proxy:{name}"

    def get_latest(self, name):
        return {"device": name, "value": 12}

    def get_metrics(self, name):
        return {"device": name, "connected": True}

    def read_all(self):
        return {"D1": {"value": 12}}


class FakeCameras:
    def get_frame_packet(self, index):
        return f"frame:{index}", index + 10


class FakePanel:
    def execute_sequence_command(self, command, value):
        return command, value

    def is_sequence_command_complete(self, command, value):
        return command == "go" and value == 3


class ExperimentContextTests(unittest.TestCase):
    def setUp(self):
        self.panel = FakePanel()
        self.context = ExperimentContext(
            FakeManager(), FakeCameras(),
            lambda experiment_id, create=False: (
                self.panel if experiment_id == "experiment" else None
            ),
        )

    def test_namespaced_services(self):
        self.assertEqual(self.context.devices.get("D1"), "proxy:D1")
        self.assertEqual(self.context.data.latest("D1")["value"], 12)
        self.assertEqual(self.context.cameras.frame_packet(1), ("frame:1", 11))
        self.assertEqual(
            self.context.experiments.execute("experiment", "go", 3),
            ("go", 3),
        )
        self.assertTrue(
            self.context.experiments.is_complete("experiment", "go", 3)
        )

    def test_legacy_device_manager_methods_remain_compatible(self):
        self.assertEqual(self.context.get_device("D1"), "proxy:D1")
        self.assertEqual(self.context.get_latest("D1")["value"], 12)
        self.assertTrue(self.context.get_metrics("D1")["connected"])
        self.assertIn("D1", self.context.read_all())


if __name__ == "__main__":
    unittest.main()
