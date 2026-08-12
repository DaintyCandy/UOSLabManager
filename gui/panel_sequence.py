import json
import time
from pathlib import Path
from core.sequence_engine import SequenceEngine
from PyQt6.QtWidgets import (QWidget, QGroupBox, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QComboBox, QDoubleSpinBox, 
                             QListWidget, QListWidgetItem, QStackedWidget, 
                             QMessageBox, QAbstractItemView, QFileDialog,
                             QDialog, QDialogButtonBox, QFormLayout, QLineEdit)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal


SYSTEM_DEVICE = "SYSTEM"
SYSTEM_COMMANDS = (
    "Wait Time", "Wait Until", "Log Marker", "Start Recording",
    "Stop Recording", "Safe Output Off",
)
WAIT_SOURCES = (
    ("CTvideo Temperature", "CTVIDEO3M", "actual_temp_C", "degC"),
    ("LS331 Temperature A", "LS331", "A_temp_K", "K"),
    ("LS331 Temperature B", "LS331", "B_temp_K", "K"),
    ("ZUP Voltage", "ZUP", "voltage_V", "V"),
    ("ZUP Current", "ZUP", "current_A", "A"),
    ("ZUP Power", "ZUP", "power_W", "W"),
)


class WaitConditionDialog(QDialog):
    """Collect a portable measurement condition for a sequence recipe."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wait Until")
        form = QFormLayout(self)
        self.source = QComboBox()
        for label, device, key, unit in WAIT_SOURCES:
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
    running_changed = pyqtSignal(bool)

    def __init__(self, device_manager, log_callback):
        super().__init__()
        self.manager = device_manager
        self.log = log_callback
        self.engine = SequenceEngine()
        
        self.sequence_steps = []
        self.current_step_idx = 0
        self.is_running = False
        
        self.state = "IDLE" 
        self.target_temp = 0.0
        self.wait_until = 0.0
        self.wait_condition = None
        self.condition_started_at = 0.0
        self.condition_met_at = None
        self.ramp_active_flag = False # Ramp가 켜져 있는지 추적
        self.recipe_path = None
        self.recipe_dirty = False
        self.experiment_plugins = {}
        self.execute_experiment_action = None
        self.poll_experiment_action = None
        self.cancel_experiment_action = None
        self.recording_action = None
        self.marker_action = None
        self.safe_output_action = None
        self.sequence_started_recording = False
        self.pending_experiment_step = None
        self.active_experiment_steps = {}

        self.engine_timer = QTimer()
        self.engine_timer.setInterval(200)
        self.engine_timer.timeout.connect(self.run_engine)

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        group = QGroupBox("Sequence Builder")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        # 1. 상단 입력부
        recipe_bar = QHBoxLayout()
        recipe_bar.addWidget(QLabel("Recipe:"))
        self.recipe_label = QLabel("Untitled")
        self.recipe_label.setStyleSheet("font-weight:bold;")
        recipe_bar.addWidget(self.recipe_label)
        recipe_bar.addStretch()
        for text, callback in (
            ("New", self.new_recipe),
            ("Load", self.load_recipe),
            ("Save", self.save_recipe),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            recipe_bar.addWidget(button)
        layout.addLayout(recipe_bar)

        input_box = QHBoxLayout()
        input_box.setAlignment(Qt.AlignmentFlag.AlignLeft)
        
        self.dev_combo = QComboBox()
        self.dev_combo.addItem("System", SYSTEM_DEVICE)
        for device_id in ("LS331", "K2400", "ZUP36-12"):
            self.dev_combo.addItem(device_id, device_id)
        self.builtin_device_count = self.dev_combo.count()
        self.dev_combo.setFixedWidth(105)
        self.dev_combo.currentTextChanged.connect(self.on_dev_changed)
        
        self.cmd_combo = QComboBox()
        self.cmd_combo.setFixedWidth(135)
        self.cmd_combo.currentTextChanged.connect(self.on_cmd_changed)
        
        self.val_stack = QStackedWidget()
        self.val_stack.setFixedSize(160, 25)
        
        self.val_spin = QDoubleSpinBox()
        self.val_spin.setRange(-200, 1000)
        self.val_spin.setValue(300.0)
        
        self.heater_combo = QComboBox()
        self.heater_combo.addItems(["Off", "Low", "Medium", "High"])

        self.marker_input = QLineEdit()
        self.marker_input.setPlaceholderText("Marker text")
        
        self.val_stack.addWidget(self.val_spin)
        self.val_stack.addWidget(self.heater_combo)
        self.val_stack.addWidget(self.marker_input)
        
        self.unit_label = QLabel("K")
        self.unit_label.setFixedWidth(25)

        self.wait_unit_combo = QComboBox()
        self.wait_unit_combo.addItem("s", 1.0)
        self.wait_unit_combo.addItem("min", 60.0)
        self.wait_unit_combo.addItem("h", 3600.0)
        self.wait_unit_combo.setFixedWidth(58)
        self.wait_unit_combo.setVisible(False)
        
        self.add_btn = QPushButton("Add")
        self.add_btn.setFixedSize(45, 28)
        self.add_btn.clicked.connect(self.add_to_stack)

        input_box.addWidget(self.dev_combo)
        input_box.addWidget(self.cmd_combo)
        input_box.addWidget(self.val_stack)
        input_box.addWidget(self.unit_label)
        input_box.addWidget(self.wait_unit_combo)
        input_box.addWidget(self.add_btn)
        layout.addLayout(input_box)

        # 2. 시퀀스 리스트 (드래그 앤 드롭 순서 변경)
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("font-weight: bold; font-size: 10pt;")
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDropIndicatorShown(True)
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.model().rowsMoved.connect(self.sync_sequence_after_drag)
        
        layout.addWidget(self.list_widget)

        # 3. 하단 버튼부
        bottom_box = QHBoxLayout()
        self.del_btn = QPushButton("Delete")
        self.del_btn.setFixedSize(70, 28)
        self.del_btn.clicked.connect(self.delete_step)
        
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.setFixedSize(70, 28)
        self.clear_btn.clicked.connect(self.clear_all)
        
        self.exec_btn = QPushButton("Execute ▶")
        self.exec_btn.setFixedHeight(35)
        self.exec_btn.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; font-size: 11pt;")
        self.exec_btn.clicked.connect(self.toggle_execution)

        bottom_box.addWidget(self.del_btn)
        bottom_box.addWidget(self.clear_btn)
        bottom_box.addStretch(1)
        bottom_box.addWidget(self.exec_btn, 2)

        layout.addLayout(bottom_box)
        main_layout.addWidget(group)
        self.on_dev_changed()

    def on_dev_changed(self):
        dev = self.dev_combo.currentData() or self.dev_combo.currentText()
        self.cmd_combo.clear()
        if dev == SYSTEM_DEVICE:
            self.cmd_combo.addItems(SYSTEM_COMMANDS)
        elif dev == "LS331":
            # "Wait for Temp" 삭제 (Set Temp에 통합됨)
            self.cmd_combo.addItems(["Set Temp", "Heater", "Apply Ramp", "Ramp Off"])
        elif dev == "K2400":
            self.cmd_combo.addItems(["Set Voltage", "Output On", "Output Off"])
        elif dev == "ZUP36-12":
            self.cmd_combo.addItems(["Set Volt", "Set Amp", "Set OVP", "Set UVP", "Output On", "Output Off"])
        elif isinstance(dev, str) and dev.startswith("experiment:"):
            plugin = self.experiment_plugins.get(dev.partition(":")[2])
            if plugin is not None:
                for command in plugin.sequence_commands:
                    self.cmd_combo.addItem(command.label, command.key)

    def set_experiment_plugins(
        self, plugins, execute_callback=None, poll_callback=None,
        cancel_callback=None,
    ):
        current = self.dev_combo.currentData()
        self.experiment_plugins = dict(plugins)
        while self.dev_combo.count() > self.builtin_device_count:
            self.dev_combo.removeItem(self.builtin_device_count)
        for plugin_id, plugin in self.experiment_plugins.items():
            if plugin.sequence_commands:
                self.dev_combo.addItem(plugin.display_name, f"experiment:{plugin_id}")
        self.execute_experiment_action = execute_callback or self.execute_experiment_action
        self.poll_experiment_action = poll_callback or self.poll_experiment_action
        self.cancel_experiment_action = cancel_callback or self.cancel_experiment_action
        index = self.dev_combo.findData(current)
        self.dev_combo.setCurrentIndex(index if index >= 0 else 0)

    def set_common_actions(
        self, recording_callback=None, marker_callback=None,
        safe_output_callback=None,
    ):
        self.recording_action = recording_callback
        self.marker_action = marker_callback
        self.safe_output_action = safe_output_callback

    def on_cmd_changed(self):
        cmd = self.cmd_combo.currentData() or self.cmd_combo.currentText()
        dev = self.dev_combo.currentData() or self.dev_combo.currentText()
        self.wait_unit_combo.setVisible(False)
        if isinstance(dev, str) and dev.startswith("experiment:"):
            plugin = self.experiment_plugins.get(dev.partition(":")[2])
            action = next(
                (item for item in plugin.sequence_commands if item.key == cmd), None
            ) if plugin is not None else None
            if action is None:
                return
            self.val_stack.setCurrentIndex(0)
            self.val_stack.setVisible(action.requires_value)
            self.unit_label.setVisible(action.requires_value)
            self.val_spin.setRange(action.minimum, action.maximum)
            self.val_spin.setDecimals(action.decimals)
            self.val_spin.setValue(action.default)
            self.unit_label.setText(action.unit)
            return

        if dev == SYSTEM_DEVICE:
            if cmd == "Wait Time":
                self.val_stack.setCurrentIndex(0)
                self.val_stack.setVisible(True)
                self.unit_label.setVisible(False)
                self.wait_unit_combo.setVisible(True)
                self.val_spin.setRange(0.1, 604_800.0)
                self.val_spin.setDecimals(1)
                self.val_spin.setValue(10.0)
            elif cmd == "Log Marker":
                self.val_stack.setCurrentIndex(2)
                self.val_stack.setVisible(True)
                self.unit_label.setVisible(False)
            else:
                self.val_stack.setVisible(False)
                self.unit_label.setVisible(False)
            return
        
        no_val_cmds = ["Output On", "Output Off", "Ramp Off"]
        needs_input = cmd not in no_val_cmds
        self.val_stack.setVisible(needs_input)
        self.unit_label.setVisible(needs_input)

        if cmd == "Heater":
            self.val_stack.setCurrentIndex(1)
        else:
            self.val_stack.setCurrentIndex(0)
            if dev == "LS331":
                self.val_spin.setRange(0, 1000)
                units = {"Set Temp": "K", "Apply Ramp": "K/m"}
                self.unit_label.setText(units.get(cmd, ""))
            elif dev == "K2400":
                self.val_spin.setRange(-200, 200)
                self.unit_label.setText("V")
            elif dev == "ZUP36-12":
                self.unit_label.setText("A" if "Amp" in cmd else "V")
                self.val_spin.setRange(0, 12.0 if "Amp" in cmd else 36.0)

    def add_to_stack(self):
        dev = self.dev_combo.currentData() or self.dev_combo.currentText()
        cmd = self.cmd_combo.currentData() or self.cmd_combo.currentText()
        if dev == SYSTEM_DEVICE:
            if cmd == "Wait Until":
                dialog = WaitConditionDialog(self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                val = dialog.condition()
                disp_val = self.describe_condition(val)
                arrow = " -> "
            elif cmd == "Wait Time":
                amount = self.val_spin.value()
                unit = self.wait_unit_combo.currentText()
                val = amount * float(self.wait_unit_combo.currentData())
                disp_val = f"{amount:g} {unit}"
                arrow = " -> "
            elif cmd == "Log Marker":
                val = self.marker_input.text().strip()
                if not val:
                    QMessageBox.warning(self, "Sequence", "Enter marker text.")
                    return
                disp_val, arrow = val, " -> "
            else:
                val, disp_val, arrow = 0, "", ""
            dev_label = self.dev_combo.currentText()
            step_text = (
                f"{self.list_widget.count() + 1}. [{dev_label}] "
                f"{cmd}{arrow}{disp_val}"
            )
            item = QListWidgetItem(step_text)
            item.setData(
                Qt.ItemDataRole.UserRole,
                {"dev": dev, "cmd": cmd, "val": val},
            )
            self.list_widget.addItem(item)
            self.mark_recipe_dirty()
            return
        experiment_action = isinstance(dev, str) and dev.startswith("experiment:")
        action = None
        if experiment_action:
            plugin = self.experiment_plugins.get(dev.partition(":")[2])
            action = next(
                (item for item in plugin.sequence_commands if item.key == cmd), None
            ) if plugin is not None else None
        
        if (action is not None and not action.requires_value) or cmd in ["Output On", "Output Off", "Ramp Off"]:
            val, disp_val, arrow = 0, "", ""
        elif cmd == "Heater":
            val = self.heater_combo.currentIndex()
            disp_val = self.heater_combo.currentText()
            arrow = " -> "
        else:
            val = self.val_spin.value()
            disp_val = f"{val} {self.unit_label.text()}".strip()
            arrow = " -> "

        dev_label = self.dev_combo.currentText()
        cmd_label = self.cmd_combo.currentText()
        step_text = f"{self.list_widget.count() + 1}. [{dev_label}] {cmd_label}{arrow}{disp_val}"
        step_data = {'dev': dev, 'cmd': cmd, 'val': val}
        
        item = QListWidgetItem(step_text)
        item.setData(Qt.ItemDataRole.UserRole, step_data)
        self.list_widget.addItem(item)
        self.mark_recipe_dirty()

    @staticmethod
    def describe_condition(condition):
        operator = condition["operator"]
        if operator == "Within":
            comparison = (
                f"within ±{condition['tolerance']:g} of "
                f"{condition['target']:g} {condition['unit']}"
            )
        else:
            comparison = (
                f"{operator} {condition['target']:g} {condition['unit']}"
            )
        stable = (
            f" for {condition['stable_s']:g} s"
            if condition["stable_s"] else ""
        )
        return (
            f"{condition['label']} {comparison}{stable} "
            f"(timeout {condition['timeout_s']:g} s)"
        )

    def sync_sequence_after_drag(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            old_text = item.text()
            if ". " in old_text:
                desc = old_text.split(". ", 1)[1]
                item.setText(f"{i+1}. {desc}")
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
            QMessageBox.warning(self, "Recipe", "Stop the sequence before creating a new recipe.")
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

    def recipe_steps(self):
        return [dict(self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.list_widget.count())]

    def save_recipe(self):
        if self.is_running:
            QMessageBox.warning(self, "Recipe", "Stop the sequence before saving the recipe.")
            return
        if not self.list_widget.count():
            QMessageBox.information(self, "Recipe", "There are no sequence steps to save.")
            return
        if self.recipe_path is None:
            recipe_dir = Path.cwd() / "data" / "recipes"
            recipe_dir.mkdir(parents=True, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(self, "Save Recipe", str(recipe_dir / "new_recipe.json"), "Recipe Files (*.json)")
            if not path:
                return
            self.recipe_path = Path(path)
        payload = {"schema_version": 1, "name": self.recipe_path.stem, "steps": self.recipe_steps()}
        self.recipe_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.recipe_dirty = False
        self.recipe_label.setText(self.recipe_path.stem)
        self.log(f"Recipe saved: {self.recipe_path}")

    def load_experiment(self, plugin):
        """Create an editable sequence recipe from an experiment plug-in."""
        if self.is_running:
            QMessageBox.warning(
                self, "Experiment", "Stop the sequence before loading an experiment."
            )
            return False
        if self.recipe_dirty and self.list_widget.count():
            answer = QMessageBox.question(
                self, "Load Experiment", "Discard unsaved recipe changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            steps = self.validate_recipe({
                "schema_version": 1,
                "steps": plugin.create_recipe(),
            })
        except (ValueError, TypeError) as error:
            QMessageBox.critical(self, "Invalid Experiment", str(error))
            return False
        self.list_widget.clear()
        for step in steps:
            self.add_recipe_item(step)
        self.recipe_path = None
        self.recipe_dirty = True
        self.recipe_label.setText(f"{plugin.display_name} *")
        self.log(f"Experiment loaded: {plugin.display_name}")
        return True

    def load_recipe(self):
        if self.is_running:
            QMessageBox.warning(self, "Recipe", "Stop the sequence before loading a recipe.")
            return
        if self.recipe_dirty and self.list_widget.count():
            answer = QMessageBox.question(
                self, "Load Recipe", "Discard unsaved recipe changes?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        recipe_dir = Path.cwd() / "data" / "recipes"
        recipe_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "Load Recipe", str(recipe_dir), "Recipe Files (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            steps = self.validate_recipe(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            QMessageBox.critical(self, "Invalid Recipe", str(error))
            return
        self.list_widget.clear()
        for step in steps:
            self.add_recipe_item(step)
        self.recipe_path = Path(path)
        self.recipe_dirty = False
        self.recipe_label.setText(payload.get("name") or self.recipe_path.stem)
        self.log(f"Recipe loaded: {self.recipe_path}")

    def validate_recipe(self, payload):
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("Unsupported or missing recipe schema_version.")
        steps = payload.get("steps")
        if not isinstance(steps, list):
            raise ValueError("Recipe steps must be a list.")
        allowed = {
            "LS331": {"Set Temp", "Heater", "Apply Ramp", "Ramp Off"},
            "K2400": {"Set Voltage", "Output On", "Output Off"},
            "ZUP36-12": {"Set Volt", "Set Amp", "Set OVP", "Set UVP", "Output On", "Output Off"},
            SYSTEM_DEVICE: set(SYSTEM_COMMANDS),
        }
        validated = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"Step {index} must be an object.")
            device, command, value = step.get("dev"), step.get("cmd"), step.get("val")
            # Recipes saved by older versions placed Wait Time under LS331 and
            # stored the duration in minutes.
            if device == "LS331" and command == "Wait Time":
                if not isinstance(value, (int, float)) or value < 0:
                    raise ValueError(f"Step {index} has an invalid wait time.")
                device, value = SYSTEM_DEVICE, float(value) * 60.0
            if device == SYSTEM_DEVICE:
                if command not in allowed[SYSTEM_DEVICE]:
                    raise ValueError(f"Step {index} contains an unsupported system command.")
                if command == "Wait Time":
                    if not isinstance(value, (int, float)) or value < 0:
                        raise ValueError(f"Step {index} has an invalid wait time.")
                elif command == "Wait Until":
                    self.validate_wait_condition(value, index)
                elif command == "Log Marker":
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f"Step {index} has an empty log marker.")
                    value = value.strip()
                validated.append({"dev": device, "cmd": command, "val": value})
                continue
            if isinstance(device, str) and device.startswith("experiment:"):
                plugin = self.experiment_plugins.get(device.partition(":")[2])
                action = next(
                    (item for item in plugin.sequence_commands if item.key == command),
                    None,
                ) if plugin is not None else None
                if action is None:
                    raise ValueError(f"Step {index} contains an unavailable experiment command.")
                if action.requires_value and not isinstance(value, (int, float)):
                    raise ValueError(f"Step {index} value must be numeric.")
                validated.append({"dev": device, "cmd": command, "val": value})
                continue
            if device not in allowed or command not in allowed[device]:
                raise ValueError(f"Step {index} contains an unsupported device or command.")
            if not isinstance(value, (int, float)):
                raise ValueError(f"Step {index} value must be numeric.")
            if command == "Heater" and (int(value) != value or not 0 <= int(value) <= 3):
                raise ValueError(f"Step {index} has an invalid heater range.")
            validated.append({"dev": device, "cmd": command, "val": value})
        return validated

    @staticmethod
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
            if not isinstance(condition[key], (int, float)):
                raise ValueError(f"{prefix} {key} must be numeric.")
        if condition["tolerance"] < 0 or condition["stable_s"] < 0:
            raise ValueError(f"{prefix} tolerance and stable time cannot be negative.")
        if condition["timeout_s"] <= 0:
            raise ValueError(f"{prefix} timeout must be greater than zero.")
        if condition["on_timeout"] not in {"stop", "continue"}:
            raise ValueError(f"{prefix} has an invalid timeout action.")

    def add_recipe_item(self, step):
        index = self.list_widget.count() + 1
        device, command, value = step["dev"], step["cmd"], step["val"]
        if device == SYSTEM_DEVICE:
            if command == "Wait Time":
                display = f" -> {self.format_duration(value)}"
            elif command == "Wait Until":
                display = f" -> {self.describe_condition(value)}"
            elif command == "Log Marker":
                display = f" -> {value}"
            else:
                display = ""
            item = QListWidgetItem(
                f"{index}. [System] {command}{display}"
            )
            item.setData(Qt.ItemDataRole.UserRole, dict(step))
            self.list_widget.addItem(item)
            return
        if isinstance(device, str) and device.startswith("experiment:"):
            plugin = self.experiment_plugins.get(device.partition(":")[2])
            action = next(
                (item for item in plugin.sequence_commands if item.key == command),
                None,
            ) if plugin is not None else None
            device_label = plugin.display_name if plugin is not None else device
            command_label = action.label if action is not None else command
            display = (
                f" -> {value:g} {action.unit}".rstrip()
                if action is not None and action.requires_value else ""
            )
            item = QListWidgetItem(
                f"{index}. [{device_label}] {command_label}{display}"
            )
            item.setData(Qt.ItemDataRole.UserRole, dict(step))
            self.list_widget.addItem(item)
            return
        if command in {"Output On", "Output Off", "Ramp Off"}:
            display = ""
        elif command == "Heater":
            display = f" -> {(('Off', 'Low', 'Medium', 'High'))[int(value)]}"
        else:
            units = {"Set Temp": "K", "Apply Ramp": "K/min", "Set Voltage": "V", "Set Volt": "V", "Set Amp": "A", "Set OVP": "V", "Set UVP": "V"}
            display = f" -> {value:g} {units.get(command, '')}".rstrip()
        item = QListWidgetItem(f"{index}. [{device}] {command}{display}")
        item.setData(Qt.ItemDataRole.UserRole, dict(step))
        self.list_widget.addItem(item)

    @staticmethod
    def format_duration(seconds):
        seconds = float(seconds)
        if seconds >= 3600 and seconds % 3600 == 0:
            return f"{seconds / 3600:g} h"
        if seconds >= 60 and seconds % 60 == 0:
            return f"{seconds / 60:g} min"
        return f"{seconds:g} s"

    def toggle_execution(self):
        if self.list_widget.count() == 0: return
        if not self.is_running:
            ls = self.manager.get_device("LS331")
            zup = self.manager.get_device("ZUP")
            if ls: ls.write("MODE 1"); time.sleep(0.3); ls.write("RAMP 1,0,1.0")
            if zup: zup.write(":RMT1;")
            
            self.is_running = True
            self.current_step_idx = 0
            self.active_experiment_steps = {}
            self.state = "NEXT"
            self.wait_condition = None
            self.condition_met_at = None
            self.sequence_started_recording = False
            self.ramp_active_flag = False
            self.exec_btn.setText("Stop ⏹")
            self.exec_btn.setStyleSheet("background-color: #E74C3C; color: white; font-weight: bold; font-size: 11pt;")
            self.running_changed.emit(True)
            self.engine_timer.start()
        else:
            self.finish_seq("Aborted.")

    def finish_seq(self, msg):
        if msg != "Sequence Complete." and self.active_experiment_steps:
            if self.cancel_experiment_action is not None:
                for step in self.active_experiment_steps.values():
                    try:
                        self.cancel_experiment_action(step)
                    except Exception as error:
                        self.log(f"Experiment cancel warning: {error}")
        self.pending_experiment_step = None
        self.active_experiment_steps = {}
        if self.sequence_started_recording and self.recording_action is not None:
            try:
                self.recording_action(False)
            except Exception as error:
                self.log(f"Recording stop warning: {error}")
        self.sequence_started_recording = False
        self.wait_condition = None
        self.condition_met_at = None
        self.is_running = False
        self.engine_timer.stop()
        self.exec_btn.setText("Execute ▶")
        self.exec_btn.setStyleSheet("background-color: #2ECC71; color: white; font-weight: bold; font-size: 11pt;")
        self.running_changed.emit(False)
        self.log(f">>> {msg}")

    def run_engine(self):
        if not self.is_running: return
        if self.state == "NEXT":
            if self.current_step_idx >= self.list_widget.count():
                self.finish_seq("Sequence Complete.")
                return

            item = self.list_widget.item(self.current_step_idx)
            self.list_widget.setCurrentRow(self.current_step_idx)
            step = item.data(Qt.ItemDataRole.UserRole)

            if isinstance(step.get('dev'), str) and step['dev'].startswith("experiment:"):
                if self.execute_experiment_action is None:
                    self.finish_seq("Error: experiment sequence actions are unavailable.")
                    return
                try:
                    complete = self.execute_experiment_action(step)
                except Exception as error:
                    self.finish_seq(f"Experiment error: {error}")
                    return
                self.active_experiment_steps[step["dev"]] = dict(step)
                self.pending_experiment_step = dict(step)
                if complete:
                    self.pending_experiment_step = None
                    self.go_next()
                else:
                    self.state = "WAIT_FOR_EXPERIMENT"
                return

            if step.get("dev") == SYSTEM_DEVICE:
                try:
                    self.execute_system_step(step)
                except Exception as error:
                    self.finish_seq(f"System action error: {error}")
                return
            
            dev_name = "ZUP" if step['dev'] == "ZUP36-12" else step['dev']
            dev = self.manager.get_device(dev_name)
            if not dev: self.finish_seq(f"Error: {step['dev']} disconnected."); return
            
            cmd, val = step['cmd'], step['val']
            self.log(f"Step {self.current_step_idx+1}: {cmd}")

            if step['dev'] == "LS331":
                if cmd == "Heater": dev.set_heater_range(int(val)); time.sleep(0.3); self.go_next()
                elif cmd == "Apply Ramp": 
                    dev.set_ramp(True, val, loop=1)
                    self.ramp_active_flag = True # 램프 활성화 상태 기억
                    time.sleep(0.3); self.go_next()
                elif cmd == "Ramp Off": 
                    dev.set_ramp(False, 1.0, loop=1)
                    self.ramp_active_flag = False # 램프 비활성화 상태 기억
                    time.sleep(0.3); self.go_next()
                elif cmd == "Set Temp":
                    dev.set_setpoint(val, loop=1)
                    self.target_temp = val
                    # [핵심] 램프가 켜져 있으면 도착할 때까지 대기 상태로 전환
                    if self.ramp_active_flag:
                        self.state = "WAIT_FOR_TEMP"
                        self.log(f"Ramping to {val}K... Please wait.")
                    else:
                        time.sleep(0.3); self.go_next()

            elif step['dev'] == "ZUP36-12":
                if cmd == "Set Volt": dev.set_voltage(val)
                elif cmd == "Set Amp": dev.set_current(val)
                elif cmd == "Set OVP": dev.set_ovp(val)
                elif cmd == "Set UVP": dev.set_uvp(val)
                elif cmd == "Output On": dev.output_on()
                elif cmd == "Output Off": dev.output_off()
                time.sleep(0.3); self.go_next()

            elif step['dev'] == "K2400":
                if cmd == "Set Voltage": dev.set_voltage_source(val)
                elif cmd == "Output On": dev.output_on()
                elif cmd == "Output Off": dev.output_off()
                time.sleep(0.3); self.go_next()

        elif self.state == "WAIT_FOR_TEMP":
            try:
                ls = self.manager.get_device("LS331")
                # 장비가 램프 동작을 마쳤거나(RAMPST), 온도 오차가 작으면 통과
                if not ls.is_ramping(loop=1) or (abs(ls.read_temp("A") - self.target_temp) < 2.5):
                    # 도착하면 안전을 위해 램프를 끄고 다음으로 넘어감
                    ls.set_ramp(False, 1.0, loop=1)
                    self.ramp_active_flag = False 
                    self.log(">>> Target reached. Ramp Auto-OFF.")
                    time.sleep(0.5); self.go_next()
            except Exception as error:
                self.finish_seq(f"Temperature wait error: {error}")
            
        elif self.state == "WAIT_FOR_TIME":
            if time.monotonic() >= self.wait_until:
                self.go_next()

        elif self.state == "WAIT_FOR_CONDITION":
            self.poll_wait_condition()

        elif self.state == "WAIT_FOR_EXPERIMENT":
            try:
                if self.poll_experiment_action(self.pending_experiment_step):
                    self.pending_experiment_step = None
                    self.go_next()
            except Exception as error:
                self.finish_seq(f"Experiment error: {error}")

    def execute_system_step(self, step):
        command, value = step["cmd"], step["val"]
        self.log(f"Step {self.current_step_idx + 1}: {command}")
        if command == "Wait Time":
            self.wait_until = time.monotonic() + float(value)
            self.state = "WAIT_FOR_TIME"
            self.log(f"Waiting for {self.format_duration(value)}")
        elif command == "Wait Until":
            self.validate_wait_condition(value)
            self.wait_condition = dict(value)
            self.condition_started_at = time.monotonic()
            self.condition_met_at = None
            self.state = "WAIT_FOR_CONDITION"
            self.log(f"Waiting until {self.describe_condition(value)}")
        elif command == "Log Marker":
            if self.marker_action is not None:
                self.marker_action(str(value))
            self.log(f"=== MARKER: {value} ===")
            self.go_next()
        elif command == "Start Recording":
            if self.recording_action is None:
                self.finish_seq("Error: data recording action is unavailable.")
                return
            started_here = self.recording_action(True)
            self.sequence_started_recording = (
                self.sequence_started_recording or bool(started_here)
            )
            self.go_next()
        elif command == "Stop Recording":
            if self.recording_action is None:
                self.finish_seq("Error: data recording action is unavailable.")
                return
            self.recording_action(False)
            self.sequence_started_recording = False
            self.go_next()
        elif command == "Safe Output Off":
            if self.safe_output_action is None:
                self.finish_seq("Error: safe-output action is unavailable.")
                return
            self.safe_output_action()
            self.log("All connected outputs changed to their safe state")
            self.go_next()
        else:
            self.finish_seq(f"Error: unsupported system command: {command}")

    def poll_wait_condition(self):
        condition = self.wait_condition
        if not condition:
            self.finish_seq("Error: Wait Until condition is unavailable.")
            return
        now = time.monotonic()
        elapsed = now - self.condition_started_at
        if elapsed >= condition["timeout_s"]:
            message = f"Wait Until timed out: {self.describe_condition(condition)}"
            if condition["on_timeout"] == "continue":
                self.log(f">>> {message}; continuing")
                self.go_next()
            else:
                if self.safe_output_action is not None:
                    try:
                        self.safe_output_action()
                    except Exception as error:
                        self.log(f"Safe-output warning after timeout: {error}")
                self.finish_seq(f"Error: {message}")
            return

        metrics = self.manager.get_metrics(condition["device"])
        if not metrics.get("connected"):
            self.finish_seq(
                f"Error: {condition['label']} device is disconnected."
            )
            return
        age_ms = metrics.get("age_ms")
        if age_ms is None or age_ms > 2000:
            self.condition_met_at = None
            return
        value = self.manager.get_latest(condition["device"]).get(condition["key"])
        try:
            value = float(value)
        except (TypeError, ValueError):
            self.condition_met_at = None
            return
        operator = condition["operator"]
        target = condition["target"]
        met = {
            ">=": value >= target,
            "<=": value <= target,
            ">": value > target,
            "<": value < target,
            "Within": abs(value - target) <= condition["tolerance"],
        }[operator]
        if not met:
            self.condition_met_at = None
            return
        if self.condition_met_at is None:
            self.condition_met_at = now
        if now - self.condition_met_at >= condition["stable_s"]:
            self.log(
                f">>> Condition reached: {condition['label']} = "
                f"{value:g} {condition['unit']}"
            )
            self.go_next()

    def go_next(self):
        self.current_step_idx += 1
        self.state = "NEXT"
