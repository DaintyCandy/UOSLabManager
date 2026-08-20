"""Sequence recipe editor and Qt adapter for the headless sequence engine."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.sequence_engine import (
    SYSTEM_COMMANDS, SYSTEM_DEVICE, SequenceEngine, SequenceState,
    describe_condition, format_duration, validate_wait_condition,
)


@dataclass
class _GuiRequest:
    name: str
    args: tuple
    completed: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: Exception | None = None


class WaitConditionDialog(QDialog):
    """Collect a portable measurement condition for a sequence recipe."""

    def __init__(self, sources, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wait Until")
        form = QFormLayout(self)
        self.source = QComboBox()
        for label, device, key, unit in sources:
            self.source.addItem(label, (device, key, unit))
        self.operator = QComboBox()
        self.operator.addItems([">=", "<=", ">", "<", "Within"])
        self.target = QDoubleSpinBox()
        self.target.setRange(-1_000_000.0, 1_000_000.0)
        self.target.setDecimals(6)
        self.tolerance = QDoubleSpinBox()
        self.tolerance.setRange(0.0, 1_000_000.0)
        self.tolerance.setDecimals(6)
        self.tolerance.setValue(2.5)
        self.stable_time = QDoubleSpinBox()
        self.stable_time.setRange(0.0, 86_400.0)
        self.stable_time.setValue(3.0)
        self.stable_time.setSuffix(" s")
        self.timeout = QDoubleSpinBox()
        self.timeout.setRange(1.0, 604_800.0)
        self.timeout.setValue(600.0)
        self.timeout.setSuffix(" s")
        self.on_timeout = QComboBox()
        self.on_timeout.addItems(["Stop Sequence", "Continue"])
        form.addRow("Measurement", self.source)
        form.addRow("Condition", self.operator)
        form.addRow("Target", self.target)
        form.addRow("Tolerance (Within)", self.tolerance)
        form.addRow("Stable for", self.stable_time)
        form.addRow("Timeout", self.timeout)
        form.addRow("On timeout", self.on_timeout)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def condition(self):
        device, key, unit = self.source.currentData()
        return {
            "label": self.source.currentText(),
            "device": device,
            "key": key,
            "unit": unit,
            "operator": self.operator.currentText(),
            "target": self.target.value(),
            "tolerance": self.tolerance.value(),
            "stable_s": self.stable_time.value(),
            "timeout_s": self.timeout.value(),
            "on_timeout": "continue" if self.on_timeout.currentIndex() else "stop",
        }


class SequencePanel(QWidget):
    """Recipe editor only; execution is delegated to ``SequenceEngine``."""

    running_changed = pyqtSignal(bool)
    _engine_log = pyqtSignal(str)
    _engine_step = pyqtSignal(int)
    _engine_done = pyqtSignal(object)
    _gui_request = pyqtSignal(object)

    def __init__(self, device_manager, log_callback, device_plugins=None):
        super().__init__()
        self.manager = device_manager
        self.log = log_callback
        self.device_plugins = dict(device_plugins or {})
        self.experiment_plugins = {}
        self.engine = SequenceEngine(
            device_manager, self.device_plugins, self.experiment_plugins
        )
        self.is_running = False
        self.recipe_path = None
        self.recipe_dirty = False
        self.execute_experiment_action = None
        self.poll_experiment_action = None
        self.cancel_experiment_action = None
        self.recording_action = None
        self.marker_action = None
        self.safe_output_action = None
        self._worker_thread = None
        self._stop_message = None
        self._engine_log.connect(self.log)
        self._engine_step.connect(self.list_step_started)
        self._engine_done.connect(self._sequence_finished)
        self._gui_request.connect(self._handle_gui_request)
        self.init_ui()

    @property
    def state(self):
        return self.engine.state.name

    @property
    def current_step_idx(self):
        return self.engine.current_step

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        group = QGroupBox("Sequence Builder")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        recipe_bar = QHBoxLayout()
        recipe_bar.addWidget(QLabel("Recipe:"))
        self.recipe_label = QLabel("Untitled")
        self.recipe_label.setStyleSheet("font-weight:bold;")
        recipe_bar.addWidget(self.recipe_label)
        recipe_bar.addStretch()
        self.recipe_buttons = []
        for text, callback in (
            ("New", self.new_recipe), ("Load", self.load_recipe),
            ("Save", self.save_recipe),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            recipe_bar.addWidget(button)
            self.recipe_buttons.append(button)
        layout.addLayout(recipe_bar)

        input_box = QHBoxLayout()
        input_box.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.dev_combo = QComboBox()
        self.dev_combo.setFixedWidth(125)
        self.dev_combo.currentIndexChanged.connect(self.on_dev_changed)
        self.cmd_combo = QComboBox()
        self.cmd_combo.setFixedWidth(145)
        self.cmd_combo.currentIndexChanged.connect(self.on_cmd_changed)
        self.val_stack = QStackedWidget()
        self.val_stack.setFixedSize(170, 25)
        self.val_spin = QDoubleSpinBox()
        self.choice_combo = QComboBox()
        self.heater_combo = self.choice_combo  # compatibility for external themes
        self.marker_input = QLineEdit()
        self.marker_input.setPlaceholderText("Marker text")
        self.val_stack.addWidget(self.val_spin)
        self.val_stack.addWidget(self.choice_combo)
        self.val_stack.addWidget(self.marker_input)
        self.unit_label = QLabel("")
        self.unit_label.setFixedWidth(42)
        self.wait_unit_combo = QComboBox()
        self.wait_unit_combo.addItem("s", 1.0)
        self.wait_unit_combo.addItem("min", 60.0)
        self.wait_unit_combo.addItem("h", 3600.0)
        self.wait_unit_combo.setFixedWidth(58)
        self.add_btn = QPushButton("Add")
        self.add_btn.setFixedSize(45, 28)
        self.add_btn.clicked.connect(self.add_to_stack)
        for widget in (
            self.dev_combo, self.cmd_combo, self.val_stack, self.unit_label,
            self.wait_unit_combo, self.add_btn,
        ):
            input_box.addWidget(widget)
        layout.addLayout(input_box)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("font-weight: bold; font-size: 10pt;")
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.model().rowsMoved.connect(self.sync_sequence_after_drag)
        layout.addWidget(self.list_widget)

        bottom_box = QHBoxLayout()
        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self.delete_step)
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self.clear_all)
        self.exec_btn = QPushButton("Execute")
        self.exec_btn.setFixedHeight(35)
        self.exec_btn.clicked.connect(self.toggle_execution)
        bottom_box.addWidget(self.del_btn)
        bottom_box.addWidget(self.clear_btn)
        bottom_box.addStretch(1)
        bottom_box.addWidget(self.exec_btn, 2)
        layout.addLayout(bottom_box)
        main_layout.addWidget(group)
        self._rebuild_sources()
        self._set_running_ui(False)

    def _rebuild_sources(self):
        current = self.dev_combo.currentData()
        self.dev_combo.blockSignals(True)
        self.dev_combo.clear()
        self.dev_combo.addItem("System", SYSTEM_DEVICE)
        for plugin in self.device_plugins.values():
            if plugin.sequence_commands:
                self.dev_combo.addItem(plugin.display_name, plugin.device_id)
        for plugin_id, plugin in self.experiment_plugins.items():
            if plugin.sequence_commands:
                self.dev_combo.addItem(plugin.display_name, f"experiment:{plugin_id}")
        index = self.dev_combo.findData(current)
        self.dev_combo.setCurrentIndex(index if index >= 0 else 0)
        self.dev_combo.blockSignals(False)
        self.on_dev_changed()

    def set_device_plugins(self, plugins):
        self.device_plugins = dict(plugins)
        self.engine.set_plugins(device_plugins=self.device_plugins)
        self._rebuild_sources()

    def set_experiment_plugins(
        self, plugins, execute_callback=None, poll_callback=None,
        cancel_callback=None,
    ):
        self.experiment_plugins = dict(plugins)
        self.engine.set_plugins(experiment_plugins=self.experiment_plugins)
        if execute_callback is not None:
            self.execute_experiment_action = execute_callback
        if poll_callback is not None:
            self.poll_experiment_action = poll_callback
        if cancel_callback is not None:
            self.cancel_experiment_action = cancel_callback
        self._rebuild_sources()

    def set_common_actions(
        self, recording_callback=None, marker_callback=None,
        safe_output_callback=None,
    ):
        self.recording_action = recording_callback
        self.marker_action = marker_callback
        self.safe_output_action = safe_output_callback

    def _plugin_for_source(self, source):
        if isinstance(source, str) and source.startswith("experiment:"):
            return self.experiment_plugins.get(source.partition(":")[2])
        return self.engine.resolve_device_plugin(source)

    def wait_sources(self):
        """Build condition sources entirely from device plug-in metadata."""
        sources = []
        for plugin in self.device_plugins.values():
            for column in getattr(plugin, "columns", ()):
                if getattr(column, "wait_condition_enabled", False):
                    sources.append((
                        column.condition_label,
                        plugin.device_id,
                        column.key,
                        column.unit,
                    ))
        return tuple(sources)

    def _command_for(self, source, command):
        plugin = self._plugin_for_source(source)
        return self.engine.find_command(plugin, command)

    def on_dev_changed(self):
        source = self.dev_combo.currentData()
        self.cmd_combo.blockSignals(True)
        self.cmd_combo.clear()
        if source == SYSTEM_DEVICE:
            for command in SYSTEM_COMMANDS:
                self.cmd_combo.addItem(command, command)
        else:
            plugin = self._plugin_for_source(source)
            for command in getattr(plugin, "sequence_commands", ()):
                self.cmd_combo.addItem(command.label, command.key)
        self.cmd_combo.blockSignals(False)
        self.on_cmd_changed()

    def on_cmd_changed(self):
        source = self.dev_combo.currentData()
        command = self.cmd_combo.currentData()
        self.wait_unit_combo.setVisible(False)
        self.choice_combo.clear()
        if source == SYSTEM_DEVICE:
            self.unit_label.setVisible(False)
            if command == "Wait Time":
                self.val_stack.setCurrentWidget(self.val_spin)
                self.val_stack.setVisible(True)
                self.wait_unit_combo.setVisible(True)
                self.val_spin.setRange(0.1, 604_800.0)
                self.val_spin.setDecimals(1)
                self.val_spin.setValue(10.0)
            elif command == "Log Marker":
                self.val_stack.setCurrentWidget(self.marker_input)
                self.val_stack.setVisible(True)
            else:
                self.val_stack.setVisible(False)
            return
        action = self._command_for(source, command)
        if action is None:
            self.val_stack.setVisible(False)
            self.unit_label.setVisible(False)
            return
        self.val_stack.setVisible(action.requires_value)
        self.unit_label.setVisible(action.requires_value and bool(action.unit))
        self.unit_label.setText(action.unit)
        if action.choices:
            self.choice_combo.addItems(action.choices)
            self.choice_combo.setCurrentIndex(int(action.default))
            self.val_stack.setCurrentWidget(self.choice_combo)
        else:
            self.val_spin.setRange(action.minimum, action.maximum)
            self.val_spin.setDecimals(action.decimals)
            self.val_spin.setValue(action.default)
            self.val_stack.setCurrentWidget(self.val_spin)

    def add_to_stack(self):
        source = self.dev_combo.currentData()
        command = self.cmd_combo.currentData()
        if not command:
            return
        if source == SYSTEM_DEVICE:
            if command == "Wait Until":
                sources = self.wait_sources()
                if not sources:
                    QMessageBox.warning(
                        self, "Sequence",
                        "No device plug-in exposes a measurement for Wait Until.",
                    )
                    return
                dialog = WaitConditionDialog(sources, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                value = dialog.condition()
            elif command == "Wait Time":
                value = self.val_spin.value() * float(self.wait_unit_combo.currentData())
            elif command == "Log Marker":
                value = self.marker_input.text().strip()
                if not value:
                    QMessageBox.warning(self, "Sequence", "Enter marker text.")
                    return
            else:
                value = 0
        else:
            action = self._command_for(source, command)
            if action is None:
                return
            if not action.requires_value:
                value = 0
            elif action.choices:
                value = self.choice_combo.currentIndex()
            else:
                value = self.val_spin.value()
        self.add_recipe_item({"dev": source, "cmd": command, "val": value})
        self.mark_recipe_dirty()

    def add_recipe_item(self, step):
        index = self.list_widget.count() + 1
        source, command, value = step["dev"], step["cmd"], step["val"]
        if source == SYSTEM_DEVICE:
            label = "System"
            if command == "Wait Time":
                display = format_duration(value)
            elif command == "Wait Until":
                display = describe_condition(value)
            elif command == "Log Marker":
                display = str(value)
            else:
                display = ""
            command_label = command
        else:
            plugin = self._plugin_for_source(source)
            action = self._command_for(source, command)
            label = plugin.display_name if plugin is not None else str(source)
            command_label = action.label if action is not None else str(command)
            display = action.format_value(value) if action is not None else str(value)
        suffix = f" -> {display}" if display else ""
        item = QListWidgetItem(
            f"{index}. [{label}] {command_label}{suffix}"
        )
        item.setData(Qt.ItemDataRole.UserRole, dict(step))
        self.list_widget.addItem(item)

    def recipe_steps(self):
        return [
            dict(self.list_widget.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self.list_widget.count())
        ]

    def validate_recipe(self, payload):
        return self.engine.validate_recipe(payload)

    validate_wait_condition = staticmethod(validate_wait_condition)
    describe_condition = staticmethod(describe_condition)
    format_duration = staticmethod(format_duration)

    def sync_sequence_after_drag(self):
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            description = item.text().split(". ", 1)[-1]
            item.setText(f"{index + 1}. {description}")
        self.mark_recipe_dirty()

    def delete_step(self):
        row = self.list_widget.currentRow()
        if row >= 0 and not self.is_running:
            self.list_widget.takeItem(row)
            self.sync_sequence_after_drag()

    def clear_all(self):
        if not self.is_running:
            self.list_widget.clear()
            self.mark_recipe_dirty()

    def mark_recipe_dirty(self):
        self.recipe_dirty = True
        name = self.recipe_path.stem if self.recipe_path else "Untitled"
        self.recipe_label.setText(f"{name} *")

    def new_recipe(self):
        if self.is_running:
            QMessageBox.warning(self, "Recipe", "Stop the sequence first.")
            return
        if self.recipe_dirty and self.list_widget.count():
            answer = QMessageBox.question(
                self, "New Recipe", "Discard unsaved recipe changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.list_widget.clear()
        self.recipe_path = None
        self.recipe_dirty = False
        self.recipe_label.setText("Untitled")
        self.log("New recipe created")

    def _confirm_discard(self, title):
        if not self.recipe_dirty or not self.list_widget.count():
            return True
        answer = QMessageBox.question(
            self, title, "Discard unsaved recipe changes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def save_recipe(self):
        if self.is_running:
            QMessageBox.warning(self, "Recipe", "Stop the sequence first.")
            return
        if not self.list_widget.count():
            QMessageBox.information(self, "Recipe", "There are no steps to save.")
            return
        if self.recipe_path is None:
            recipe_dir = Path.cwd() / "data" / "recipes"
            recipe_dir.mkdir(parents=True, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Recipe", str(recipe_dir / "new_recipe.json"),
                "Recipe Files (*.json)",
            )
            if not path:
                return
            self.recipe_path = Path(path)
        payload = {
            "schema_version": 1, "name": self.recipe_path.stem,
            "steps": self.recipe_steps(),
        }
        self.recipe_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.recipe_dirty = False
        self.recipe_label.setText(self.recipe_path.stem)
        self.log(f"Recipe saved: {self.recipe_path}")

    def load_recipe(self):
        if self.is_running:
            QMessageBox.warning(self, "Recipe", "Stop the sequence first.")
            return
        if not self._confirm_discard("Load Recipe"):
            return
        recipe_dir = Path.cwd() / "data" / "recipes"
        recipe_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Recipe", str(recipe_dir), "Recipe Files (*.json)"
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            steps = self.validate_recipe(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            QMessageBox.critical(self, "Invalid Recipe", str(error))
            return
        self._replace_recipe(steps)
        self.recipe_path = Path(path)
        self.recipe_dirty = False
        self.recipe_label.setText(payload.get("name") or self.recipe_path.stem)
        self.log(f"Recipe loaded: {self.recipe_path}")

    def load_experiment(self, plugin):
        if self.is_running:
            QMessageBox.warning(self, "Experiment", "Stop the sequence first.")
            return False
        if not self._confirm_discard("Load Experiment"):
            return False
        try:
            steps = self.validate_recipe(
                {"schema_version": 1, "steps": plugin.create_recipe()}
            )
        except (ValueError, TypeError) as error:
            QMessageBox.critical(self, "Invalid Experiment", str(error))
            return False
        self._replace_recipe(steps)
        self.recipe_path = None
        self.recipe_dirty = True
        self.recipe_label.setText(f"{plugin.display_name} *")
        self.log(f"Experiment loaded: {plugin.display_name}")
        return True

    def _replace_recipe(self, steps):
        self.list_widget.clear()
        for step in steps:
            self.add_recipe_item(step)

    def toggle_execution(self):
        if self.is_running:
            self.finish_seq("Aborted.")
            return
        if not self.list_widget.count():
            return
        try:
            steps = self.validate_recipe(
                {"schema_version": 1, "steps": self.recipe_steps()}
            )
        except (ValueError, TypeError) as error:
            QMessageBox.critical(self, "Invalid Sequence", str(error))
            return
        self.engine.configure_callbacks(
            log_callback=self._engine_log.emit,
            step_callback=lambda index, _step: self._engine_step.emit(index),
            experiment_execute=self._gui_callback(
                "experiment_execute", self.execute_experiment_action
            ),
            experiment_poll=self._gui_callback(
                "experiment_poll", self.poll_experiment_action
            ),
            experiment_cancel=self._gui_callback(
                "experiment_cancel", self.cancel_experiment_action
            ),
            recording_action=self._gui_callback("recording", self.recording_action),
            marker_action=self._gui_callback("marker", self.marker_action),
            safe_output_action=self._gui_callback("safe_output", self.safe_output_action),
        )
        self.engine.load(steps)
        self._stop_message = None
        self.is_running = True
        self._set_running_ui(True)
        self.running_changed.emit(True)
        self._worker_thread = threading.Thread(
            target=self._run_sequence, name="SequenceEngine", daemon=True
        )
        self._worker_thread.start()

    def _gui_callback(self, name, callback):
        if callback is None:
            return None
        return lambda *args: self._call_gui(name, *args)

    def _call_gui(self, name, *args):
        request = _GuiRequest(name, args)
        self._gui_request.emit(request)
        if not request.completed.wait(30.0):
            raise TimeoutError(f"GUI action timed out: {name}")
        if request.error is not None:
            raise request.error
        return request.result

    def _handle_gui_request(self, request):
        callbacks = {
            "experiment_execute": self.execute_experiment_action,
            "experiment_poll": self.poll_experiment_action,
            "experiment_cancel": self.cancel_experiment_action,
            "recording": self.recording_action,
            "marker": self.marker_action,
            "safe_output": self.safe_output_action,
        }
        try:
            callback = callbacks.get(request.name)
            if callback is None:
                raise RuntimeError(f"GUI action is unavailable: {request.name}")
            request.result = callback(*request.args)
        except Exception as error:
            request.error = error
        finally:
            request.completed.set()

    def _run_sequence(self):
        self._engine_done.emit(self.engine.run())

    def list_step_started(self, index):
        if 0 <= index < self.list_widget.count():
            self.list_widget.setCurrentRow(index)

    def finish_seq(self, message="Aborted."):
        if not self.is_running:
            return
        self._stop_message = message
        self.engine.stop()

    def _sequence_finished(self, result):
        self._worker_thread = None
        self.is_running = False
        self._set_running_ui(False)
        self.running_changed.emit(False)
        message = self._stop_message or result.message
        self._stop_message = None
        self.log(f">>> {message}")

    def _set_running_ui(self, running):
        self.exec_btn.setText("Stop" if running else "Execute")
        color = "#E74C3C" if running else "#2ECC71"
        self.exec_btn.setStyleSheet(
            f"background-color: {color}; color: white; font-weight: bold; "
            "font-size: 11pt;"
        )
        for widget in (
            self.dev_combo, self.cmd_combo, self.val_stack, self.wait_unit_combo,
            self.add_btn, self.del_btn, self.clear_btn, *self.recipe_buttons,
        ):
            widget.setEnabled(not running)
        self.list_widget.setDragEnabled(not running)

    def shutdown(self, timeout=2.0):
        """Request cancellation and briefly drain queued GUI callbacks."""
        thread = self._worker_thread
        if thread is None:
            return
        self.engine.stop()
        deadline = time.monotonic() + max(0.0, timeout)
        while thread.is_alive() and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            thread.join(0.01)
