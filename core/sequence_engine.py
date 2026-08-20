"""UI-independent sequence validation and execution."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable


SYSTEM_DEVICE = "SYSTEM"
SYSTEM_COMMANDS = (
    "Wait Time", "Wait Until", "Log Marker", "Start Recording",
    "Stop Recording", "Safe Output Off",
)


class SequenceState(Enum):
    IDLE = auto()
    RUNNING = auto()
    WAITING = auto()
    STOPPING = auto()
    STOPPED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class SequenceResult:
    state: SequenceState
    message: str
    error: Exception | None = None


class SequenceStopped(RuntimeError):
    pass


class SequenceContext:
    """Small capability object exposed to declarative device executors."""

    def __init__(self, manager, stop_event, log_callback, runtime):
        self.manager = manager
        self._stop_event = stop_event
        self._log = log_callback
        self._runtime = runtime

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def wait(self, seconds: float) -> bool:
        return not self._stop_event.wait(max(0.0, float(seconds)))

    def log(self, message: str) -> None:
        self._log(str(message))

    def get_runtime(self, key: str, default: Any = None) -> Any:
        return self._runtime.get(key, default)

    def set_runtime(self, key: str, value: Any) -> None:
        self._runtime[key] = value


class SequenceEngine:
    """Execute recipes without importing Qt or accessing GUI widgets.

    ``run`` is blocking by design. Desktop frontends should call it from a
    worker thread; all engine waits remain immediately cancellable.
    """

    def __init__(
        self, manager=None, device_plugins=None, experiment_plugins=None, *,
        log_callback: Callable[[str], None] | None = None,
        step_callback: Callable[[int, dict[str, Any]], None] | None = None,
        experiment_execute: Callable[[dict[str, Any]], bool] | None = None,
        experiment_poll: Callable[[dict[str, Any]], bool] | None = None,
        experiment_cancel: Callable[[dict[str, Any]], Any] | None = None,
        recording_action: Callable[[bool], Any] | None = None,
        marker_action: Callable[[str], Any] | None = None,
        safe_output_action: Callable[[], Any] | None = None,
        poll_interval: float = 0.2,
    ):
        self.manager = manager
        self.device_plugins = dict(device_plugins or {})
        self.experiment_plugins = dict(experiment_plugins or {})
        self.log_callback = log_callback or (lambda _message: None)
        self.step_callback = step_callback or (lambda _index, _step: None)
        self.experiment_execute = experiment_execute
        self.experiment_poll = experiment_poll
        self.experiment_cancel = experiment_cancel
        self.recording_action = recording_action
        self.marker_action = marker_action
        self.safe_output_action = safe_output_action
        self.poll_interval = max(0.01, float(poll_interval))
        self.steps: list[dict[str, Any]] = []
        self.current_step = 0
        self.state = SequenceState.IDLE
        self._stop_event = threading.Event()
        self._runtime: dict[str, Any] = {}
        self._active_experiments: dict[str, dict[str, Any]] = {}
        self._sequence_started_recording = False

    @property
    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    def set_plugins(self, device_plugins=None, experiment_plugins=None) -> None:
        if self.state in {SequenceState.RUNNING, SequenceState.WAITING}:
            raise RuntimeError("Cannot replace plug-ins while a sequence is running")
        if device_plugins is not None:
            self.device_plugins = dict(device_plugins)
        if experiment_plugins is not None:
            self.experiment_plugins = dict(experiment_plugins)

    def configure_callbacks(self, **callbacks) -> None:
        for name, callback in callbacks.items():
            if not hasattr(self, name):
                raise AttributeError(name)
            setattr(self, name, callback)

    def load(self, steps) -> None:
        if self.state in {SequenceState.RUNNING, SequenceState.WAITING}:
            raise RuntimeError("Cannot load a recipe while a sequence is running")
        self.steps = [dict(step) for step in steps]
        self.current_step = 0
        self.state = SequenceState.IDLE
        self._stop_event.clear()
        self._runtime.clear()
        self._active_experiments.clear()
        self._sequence_started_recording = False

    def start(self) -> None:
        """Backward-compatible transition; frontends normally call run()."""
        self._stop_event.clear()
        self.state = SequenceState.RUNNING

    def stop(self) -> None:
        self._stop_event.set()
        if self.state in {SequenceState.RUNNING, SequenceState.WAITING}:
            self.state = SequenceState.STOPPING

    def validate_recipe(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("Unsupported or missing recipe schema_version.")
        steps = payload.get("steps")
        if not isinstance(steps, list):
            raise ValueError("Recipe steps must be a list.")
        validated = []
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                raise ValueError(f"Step {index} must be an object.")
            device = raw_step.get("dev")
            command = raw_step.get("cmd")
            value = raw_step.get("val")
            plugin = None
            if (
                device != SYSTEM_DEVICE
                and not (isinstance(device, str) and device.startswith("experiment:"))
            ):
                plugin = self.resolve_device_plugin(device)
                migration = (
                    None if plugin is None
                    else plugin.get_recipe_migration(command)
                )
                if migration is not None:
                    try:
                        migrated = migration.apply(value)
                    except (TypeError, ValueError) as error:
                        raise ValueError(f"Step {index}: {error}") from error
                    device = migrated["dev"]
                    command = migrated["cmd"]
                    value = migrated["val"]
            if device == SYSTEM_DEVICE:
                value = self._validate_system_step(index, command, value)
            elif isinstance(device, str) and device.startswith("experiment:"):
                plugin = self.experiment_plugins.get(device.partition(":")[2])
                action = self.find_command(plugin, command)
                if action is None:
                    raise ValueError(
                        f"Step {index} contains an unavailable experiment command."
                    )
                value = self._validate_action(action, value, index)
            else:
                plugin = self.resolve_device_plugin(device)
                action = self.find_command(plugin, command)
                if action is None:
                    raise ValueError(
                        f"Step {index} contains an unsupported device or command."
                    )
                value = self._validate_action(action, value, index)
                device = plugin.device_id
            validated.append({"dev": device, "cmd": command, "val": value})
        return validated

    @staticmethod
    def _validate_action(action, value, index):
        try:
            return action.validate(value)
        except ValueError as error:
            raise ValueError(f"Step {index}: {error}") from error

    def resolve_device_plugin(self, device_id: Any):
        plugin = self.device_plugins.get(device_id)
        if plugin is not None:
            return plugin
        for candidate in self.device_plugins.values():
            if device_id in getattr(candidate, "sequence_aliases", ()):
                return candidate
        return None

    @staticmethod
    def find_command(plugin, key):
        if plugin is None:
            return None
        if hasattr(plugin, "get_sequence_command"):
            return plugin.get_sequence_command(key)
        return next(
            (item for item in getattr(plugin, "sequence_commands", ()) if item.key == key),
            None,
        )

    @staticmethod
    def _number(value, label):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label} must be numeric.")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{label} must be finite.")
        return number

    def _validate_system_step(self, index, command, value):
        if command not in SYSTEM_COMMANDS:
            raise ValueError(f"Step {index} contains an unsupported system command.")
        if command == "Wait Time":
            value = self._number(value, f"Step {index} wait time")
            if value < 0:
                raise ValueError(f"Step {index} has an invalid wait time.")
        elif command == "Wait Until":
            validate_wait_condition(value, index)
            value = dict(value)
        elif command == "Log Marker":
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Step {index} has an empty log marker.")
            value = value.strip()
        else:
            value = 0
        return value

    def run(self) -> SequenceResult:
        # ``load`` owns reset. Clearing here would lose a stop requested in the
        # small window between starting the worker thread and entering run().
        self.state = SequenceState.RUNNING
        context = SequenceContext(
            self.manager, self._stop_event, self.log_callback, self._runtime
        )
        result = None
        try:
            for index, step in enumerate(self.steps):
                self._raise_if_stopped()
                self.current_step = index
                self.step_callback(index, dict(step))
                self.log_callback(f"Step {index + 1}: {step['cmd']}")
                self._execute_step(step, context)
            self.current_step = len(self.steps)
            self.state = SequenceState.COMPLETED
            result = SequenceResult(self.state, "Sequence Complete.")
        except SequenceStopped:
            self.state = SequenceState.STOPPED
            result = SequenceResult(self.state, "Sequence stopped.")
        except Exception as error:
            self.state = SequenceState.FAILED
            result = SequenceResult(self.state, f"Error: {error}", error)
        finally:
            self._cleanup(result is not None and result.state == SequenceState.COMPLETED)
        return result

    def _execute_step(self, step, context):
        device_id = step["dev"]
        if device_id == SYSTEM_DEVICE:
            self._execute_system(step, context)
            return
        if isinstance(device_id, str) and device_id.startswith("experiment:"):
            self._execute_experiment(step, context)
            return
        plugin = self.resolve_device_plugin(device_id)
        action = self.find_command(plugin, step["cmd"])
        if plugin is None or action is None:
            raise RuntimeError(f"Unsupported device command: {device_id}/{step['cmd']}")
        if self.manager is None:
            raise RuntimeError("Device manager is unavailable")
        device = self.manager.get_device(plugin.device_id)
        if device is None:
            raise RuntimeError(f"{plugin.display_name} is disconnected")
        action.execute(device, step["val"], context)
        self._raise_if_stopped()
        if action.settle_seconds and not context.wait(action.settle_seconds):
            raise SequenceStopped()

    def _execute_system(self, step, context):
        command, value = step["cmd"], step["val"]
        if command == "Wait Time":
            self.state = SequenceState.WAITING
            self.log_callback(f"Waiting for {format_duration(value)}")
            if not context.wait(float(value)):
                raise SequenceStopped()
            self.state = SequenceState.RUNNING
        elif command == "Wait Until":
            self._wait_until(value, context)
        elif command == "Log Marker":
            if self.marker_action is not None:
                self.marker_action(str(value))
            self.log_callback(f"=== MARKER: {value} ===")
        elif command in {"Start Recording", "Stop Recording"}:
            if self.recording_action is None:
                raise RuntimeError("Data recording action is unavailable")
            enabled = command == "Start Recording"
            changed = self.recording_action(enabled)
            if enabled:
                self._sequence_started_recording |= bool(changed)
            else:
                self._sequence_started_recording = False
        elif command == "Safe Output Off":
            if self.safe_output_action is None:
                raise RuntimeError("Safe-output action is unavailable")
            self.safe_output_action()
            self.log_callback("All connected outputs changed to their safe state")
        else:
            raise RuntimeError(f"Unsupported system command: {command}")

    def _wait_until(self, condition, context):
        validate_wait_condition(condition)
        self.state = SequenceState.WAITING
        self.log_callback(f"Waiting until {describe_condition(condition)}")
        started_at = time.monotonic()
        met_at = None
        while True:
            self._raise_if_stopped()
            now = time.monotonic()
            if now - started_at >= condition["timeout_s"]:
                message = f"Wait Until timed out: {describe_condition(condition)}"
                if condition["on_timeout"] == "continue":
                    self.log_callback(f">>> {message}; continuing")
                    self.state = SequenceState.RUNNING
                    return
                if self.safe_output_action is not None:
                    try:
                        self.safe_output_action()
                    except Exception as error:
                        self.log_callback(f"Safe-output warning after timeout: {error}")
                raise TimeoutError(message)
            metrics = self.manager.get_metrics(condition["device"])
            if not metrics.get("connected"):
                raise RuntimeError(f"{condition['label']} device is disconnected")
            age_ms = metrics.get("age_ms")
            value = self.manager.get_latest(condition["device"]).get(condition["key"])
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
            if age_ms is None or age_ms > 2000 or value is None:
                met_at = None
            elif condition_met(value, condition):
                if met_at is None:
                    met_at = now
                if now - met_at >= condition["stable_s"]:
                    self.log_callback(
                        f">>> Condition reached: {condition['label']} = "
                        f"{value:g} {condition['unit']}"
                    )
                    self.state = SequenceState.RUNNING
                    return
            else:
                met_at = None
            if not context.wait(self.poll_interval):
                raise SequenceStopped()

    def _execute_experiment(self, step, context):
        if self.experiment_execute is None:
            raise RuntimeError("Experiment sequence actions are unavailable")
        device_id = step["dev"]
        self._active_experiments[device_id] = dict(step)
        complete = bool(self.experiment_execute(dict(step)))
        while not complete:
            if self.experiment_poll is None:
                raise RuntimeError("Experiment polling action is unavailable")
            self.state = SequenceState.WAITING
            if not context.wait(self.poll_interval):
                raise SequenceStopped()
            complete = bool(self.experiment_poll(dict(step)))
        self.state = SequenceState.RUNNING
        self._active_experiments.pop(device_id, None)

    def _raise_if_stopped(self):
        if self._stop_event.is_set():
            raise SequenceStopped()

    def _cleanup(self, completed):
        if not completed and self.experiment_cancel is not None:
            for step in tuple(self._active_experiments.values()):
                try:
                    self.experiment_cancel(dict(step))
                except Exception as error:
                    self.log_callback(f"Experiment cancel warning: {error}")
        self._active_experiments.clear()
        if self._sequence_started_recording and self.recording_action is not None:
            try:
                self.recording_action(False)
            except Exception as error:
                self.log_callback(f"Recording stop warning: {error}")
        self._sequence_started_recording = False


def validate_wait_condition(condition, step_index=0):
    prefix = f"Step {step_index}" if step_index else "Wait Until"
    if not isinstance(condition, dict):
        raise ValueError(f"{prefix} condition must be an object.")
    required = {
        "label", "device", "key", "unit", "operator", "target",
        "tolerance", "stable_s", "timeout_s", "on_timeout",
    }
    if not required.issubset(condition):
        raise ValueError(f"{prefix} condition is incomplete.")
    if condition["operator"] not in {">=", "<=", ">", "<", "Within"}:
        raise ValueError(f"{prefix} has an invalid comparison operator.")
    for key in ("target", "tolerance", "stable_s", "timeout_s"):
        value = condition[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{prefix} {key} must be numeric.")
        if not math.isfinite(float(value)):
            raise ValueError(f"{prefix} {key} must be finite.")
    if condition["tolerance"] < 0 or condition["stable_s"] < 0:
        raise ValueError(f"{prefix} tolerance and stable time cannot be negative.")
    if condition["timeout_s"] <= 0:
        raise ValueError(f"{prefix} timeout must be greater than zero.")
    if condition["on_timeout"] not in {"stop", "continue"}:
        raise ValueError(f"{prefix} has an invalid timeout action.")


def condition_met(value, condition):
    target = condition["target"]
    return {
        ">=": value >= target,
        "<=": value <= target,
        ">": value > target,
        "<": value < target,
        "Within": abs(value - target) <= condition["tolerance"],
    }[condition["operator"]]


def describe_condition(condition):
    if condition["operator"] == "Within":
        comparison = (
            f"within +/-{condition['tolerance']:g} of "
            f"{condition['target']:g} {condition['unit']}"
        )
    else:
        comparison = (
            f"{condition['operator']} {condition['target']:g} {condition['unit']}"
        )
    stable = f" for {condition['stable_s']:g} s" if condition["stable_s"] else ""
    return (
        f"{condition['label']} {comparison}{stable} "
        f"(timeout {condition['timeout_s']:g} s)"
    )


def format_duration(seconds):
    seconds = float(seconds)
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds / 3600:g} h"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds / 60:g} min"
    return f"{seconds:g} s"
