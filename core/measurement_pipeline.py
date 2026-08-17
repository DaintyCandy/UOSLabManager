"""UI-independent measurement snapshot to row conversion."""

from __future__ import annotations

import time


class MeasurementPipeline:
    """Build provenance-rich rows while suppressing duplicate cached samples."""

    SUMMARY_COLUMNS = (
        "row_id",
        "updated_devices",
        "freshness_changed_devices",
        "stale_devices",
        "disconnected_devices",
    )

    def __init__(self, plugins, start_monotonic=None):
        self.plugins = dict(plugins)
        self.start_monotonic = (
            time.monotonic() if start_monotonic is None
            else float(start_monotonic)
        )
        self.last_sample_ids = {}
        self.last_freshness = {}
        self.last_connected_devices = set()
        self.row_id = 0

    @property
    def provenance_columns(self):
        columns = list(self.SUMMARY_COLUMNS)
        for device_id in self.plugins:
            columns.extend((
                f"{device_id}__sample_id",
                f"{device_id}__sampled_at_utc",
                f"{device_id}__age_ms",
                f"{device_id}__fresh",
                f"{device_id}__response_ms",
            ))
        return columns

    def reset(self, start_monotonic=None):
        self.start_monotonic = (
            time.monotonic() if start_monotonic is None
            else float(start_monotonic)
        )
        self.last_sample_ids.clear()
        self.last_freshness.clear()
        self.last_connected_devices.clear()
        self.row_id = 0

    def ingest(self, snapshot, markers=()):
        devices = dict(snapshot.get("devices") or {})
        connected = set(devices)
        markers = tuple(
            str(marker).strip() for marker in markers if str(marker).strip()
        )
        updated = []
        for device_id, state in devices.items():
            sample_id = int(state.get("sample_id") or 0)
            if sample_id != self.last_sample_ids.get(device_id, 0):
                updated.append(device_id)

        freshness_changed = [
            device_id for device_id, state in devices.items()
            if device_id in self.last_freshness
            and bool(state.get("fresh", False))
            != self.last_freshness[device_id]
        ]

        connection_changed = connected != self.last_connected_devices
        if (
            not updated
            and not freshness_changed
            and not connection_changed
            and not markers
        ):
            return None

        self.row_id += 1
        captured_monotonic = float(
            snapshot.get("captured_monotonic", time.monotonic())
        )
        row = {
            "datetime": snapshot.get("captured_at_utc", ""),
            "elapsed_s": max(0.0, captured_monotonic - self.start_monotonic),
            "row_id": self.row_id,
            "updated_devices": " | ".join(sorted(updated)),
            "freshness_changed_devices": " | ".join(
                sorted(freshness_changed)
            ),
            "stale_devices": " | ".join(sorted(
                device_id for device_id, state in devices.items()
                if not state.get("fresh", False)
            )),
            "disconnected_devices": " | ".join(sorted(
                set(self.plugins) - connected
            )),
            "sequence_marker": " | ".join(markers),
        }
        for device_id, plugin in self.plugins.items():
            state = devices.get(device_id, {})
            values = state.get("values") or {}
            for column in plugin.columns:
                row[column.label] = values.get(column.key, "")
            prefix = f"{device_id}__"
            row[prefix + "sample_id"] = state.get("sample_id", "")
            row[prefix + "sampled_at_utc"] = state.get("sampled_at_utc") or ""
            age_ms = state.get("age_ms")
            row[prefix + "age_ms"] = "" if age_ms is None else float(age_ms)
            row[prefix + "fresh"] = bool(state.get("fresh", False))
            response_ms = state.get("response_ms")
            row[prefix + "response_ms"] = (
                "" if response_ms is None else float(response_ms)
            )

        self.last_sample_ids = {
            device_id: int(state.get("sample_id") or 0)
            for device_id, state in devices.items()
        }
        self.last_freshness = {
            device_id: bool(state.get("fresh", False))
            for device_id, state in devices.items()
        }
        self.last_connected_devices = connected
        return row
