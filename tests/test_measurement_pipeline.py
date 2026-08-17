import unittest
from types import SimpleNamespace

from core.measurement_pipeline import MeasurementPipeline
from core.plugin_manager import DataColumn


class MeasurementPipelineTests(unittest.TestCase):
    def setUp(self):
        self.plugins = {
            "A": SimpleNamespace(columns=(DataColumn("temperature", "A_K"),)),
            "B": SimpleNamespace(columns=(DataColumn("voltage", "B_V"),)),
        }
        self.pipeline = MeasurementPipeline(self.plugins, start_monotonic=10.0)

    @staticmethod
    def snapshot(sample_a=1, sample_b=1, *, fresh_b=True):
        return {
            "captured_at_utc": "2026-08-17T01:02:03.000Z",
            "captured_monotonic": 12.5,
            "devices": {
                "A": {
                    "values": {"temperature": 100.0},
                    "sample_id": sample_a,
                    "sampled_at_utc": "2026-08-17T01:02:02.900Z",
                    "age_ms": 100.0,
                    "fresh": True,
                    "response_ms": 12.5,
                },
                "B": {
                    "values": {"voltage": 5.0},
                    "sample_id": sample_b,
                    "sampled_at_utc": "2026-08-17T01:02:00.000Z",
                    "age_ms": 3000.0 if not fresh_b else 100.0,
                    "fresh": fresh_b,
                    "response_ms": 8.0,
                },
            },
        }

    def test_cached_snapshot_is_not_logged_twice(self):
        first = self.pipeline.ingest(self.snapshot())
        duplicate = self.pipeline.ingest(self.snapshot())
        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)

    def test_row_preserves_acquisition_provenance_and_freshness(self):
        row = self.pipeline.ingest(self.snapshot(fresh_b=False))
        self.assertEqual(row["datetime"], "2026-08-17T01:02:03.000Z")
        self.assertEqual(row["elapsed_s"], 2.5)
        self.assertEqual(row["updated_devices"], "A | B")
        self.assertEqual(row["stale_devices"], "B")
        self.assertEqual(row["A__sample_id"], 1)
        self.assertEqual(
            row["A__sampled_at_utc"], "2026-08-17T01:02:02.900Z"
        )
        self.assertEqual(row["B__age_ms"], 3000.0)
        self.assertFalse(row["B__fresh"])
        self.assertEqual(row["A__response_ms"], 12.5)
        self.assertEqual(row["A_K"], 100.0)
        self.assertEqual(row["B_V"], 5.0)

    def test_only_changed_device_is_reported_on_next_row(self):
        self.pipeline.ingest(self.snapshot())
        row = self.pipeline.ingest(self.snapshot(sample_a=2))
        self.assertEqual(row["updated_devices"], "A")

    def test_marker_creates_a_row_without_a_new_device_sample(self):
        snapshot = self.snapshot()
        self.pipeline.ingest(snapshot)
        row = self.pipeline.ingest(snapshot, markers=("target reached",))
        self.assertEqual(row["updated_devices"], "")
        self.assertEqual(row["sequence_marker"], "target reached")

    def test_freshness_transition_is_recorded_without_a_new_sample(self):
        self.pipeline.ingest(self.snapshot())
        row = self.pipeline.ingest(self.snapshot(fresh_b=False))
        self.assertIsNotNone(row)
        self.assertEqual(row["updated_devices"], "")
        self.assertEqual(row["freshness_changed_devices"], "B")
        self.assertEqual(row["stale_devices"], "B")


if __name__ == "__main__":
    unittest.main()
