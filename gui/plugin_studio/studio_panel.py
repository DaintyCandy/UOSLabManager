import ast
import json
import re
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
    QMenu, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import (
    export_plugin, get_plugin_root, import_plugin, resolve_plugin_python_path,
    validate_plugin_id,
)
from .code_editor import CodeEditor
from .codex_panel import CodexPanel

PLUGIN_ROOT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class PluginStudioPanel(QWidget):
    reload_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plugin_base_root = get_plugin_root()
        self.plugin_root = self.plugin_base_root / "experiments"
        self.device_plugin_root = self.plugin_base_root / "devices"
        self.plugin_root.mkdir(parents=True, exist_ok=True)
        self.device_plugin_root.mkdir(parents=True, exist_ok=True)
        self.current_path = None
        self.codex_changed_lines = {}
        self._loading = False
        self._build_ui()
        self.refresh_tree()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()
        title = QLabel("Plugin Studio")
        title.setStyleSheet("font-size:14pt; font-weight:700;")
        toolbar.addWidget(title)
        toolbar.addStretch()
        for text, callback in (
            ("New Plugin", self.create_plugin),
            ("Import", self.import_plugin),
            ("Export", self.export_plugin),
            ("Remove", self.remove_plugin),
            ("Save", self.save_current),
            ("Validate", self.validate_all),
            ("Reload Plugins", self.request_reload),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Plugins")
        self.tree.setMinimumWidth(180)
        self.tree.itemSelectionChanged.connect(self.open_selected)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(
            self._show_tree_context_menu
        )
        splitter.addWidget(self.tree)

        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        self.path_label = QLabel("No file selected")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.editor = CodeEditor()
        self.editor.textChanged.connect(self._mark_modified)
        editor_layout.addWidget(self.path_label)
        editor_layout.addWidget(self.editor, 1)
        splitter.addWidget(editor_container)

        self.codex_panel = CodexPanel(self, prepare_callback=self.save_current)
        self.codex_panel.changes_applied.connect(self._codex_changes_applied)
        splitter.addWidget(self.codex_panel)
        self.output = self.codex_panel
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([220, 700, 480])
        layout.addWidget(splitter, 1)

        save_action = QAction(self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.save_current)
        self.addAction(save_action)

    def _selected_plugin_dir(self):
        items = self.tree.selectedItems()
        if not items:
            return None
        value = items[0].data(0, PLUGIN_ROOT_ROLE)
        return Path(value).resolve() if value else None

    @staticmethod
    def _read_manifest(plugin_dir):
        manifest_path = Path(plugin_dir) / "plugin.json"
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _plugin_id_in_use(self, root, plugin_id, exclude=None):
        """Check IDs case-insensitively so packages stay portable to Windows."""
        root = Path(root).resolve()
        exclude = Path(exclude).resolve() if exclude is not None else None
        for manifest_path in root.glob("*/plugin.json"):
            if exclude is not None and manifest_path.parent.resolve() == exclude:
                continue
            try:
                existing_id = self._read_manifest(manifest_path.parent)["id"]
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
            if str(existing_id).casefold() == plugin_id.casefold():
                return True
        return False

    def _show_tree_context_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        plugin_dir = self._selected_plugin_dir()
        if plugin_dir is None:
            return
        try:
            manifest = self._read_manifest(plugin_dir)
        except (OSError, ValueError, json.JSONDecodeError):
            return
        is_composite = (
            manifest.get("type") == "device"
            and manifest.get("profile", "standard") == "composite"
        )
        menu = QMenu(self.tree)
        edit_id = menu.addAction("Edit Plugin ID...")
        add_python = None
        add_with_codex = None
        if is_composite:
            menu.addSeparator()
            add_python = menu.addAction("Add Python File...")
            add_with_codex = menu.addAction("Add Python File with Codex...")
        selected = menu.exec(self.tree.viewport().mapToGlobal(position))
        if selected == edit_id:
            self.edit_plugin_id()
        elif add_python is not None and selected == add_python:
            self.add_composite_python_file(plugin_dir)
        elif add_with_codex is not None and selected == add_with_codex:
            self.add_composite_python_file_with_codex(plugin_dir)

    def add_composite_python_file(self, plugin_dir=None):
        """Add a safe relative Python module to a composite device package."""
        plugin_dir = plugin_dir or self._selected_plugin_dir()
        if plugin_dir is None:
            QMessageBox.warning(
                self, "Plugin Studio", "Select a composite device plugin first."
            )
            return False
        plugin_dir = Path(plugin_dir).resolve()
        try:
            plugin_dir.relative_to(self.device_plugin_root.resolve())
            manifest = self._read_manifest(plugin_dir)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            QMessageBox.warning(
                self, "Plugin Studio", "Select a composite device plugin first."
            )
            return False
        if not (
            manifest.get("type") == "device"
            and manifest.get("profile", "standard") == "composite"
        ):
            QMessageBox.warning(
                self, "Plugin Studio",
                "Python modules can be added from the tree only to composite devices.",
            )
            return False
        if self.codex_panel.staging_dir is not None:
            QMessageBox.information(
                self, "Plugin Studio",
                "Apply or reject the current Codex draft before adding a file.",
            )
            return False
        if not self.maybe_discard_changes():
            return False
        relative_text, accepted = QInputDialog.getText(
            self,
            "Add Python File",
            "Relative path (for example services/calibration.py):",
        )
        if not accepted:
            return False
        try:
            target = resolve_plugin_python_path(plugin_dir, relative_text)
        except ValueError:
            QMessageBox.warning(
                self, "Plugin Studio",
                "Use a relative .py path with valid Python package names.",
            )
            return False
        if target.exists():
            QMessageBox.warning(self, "Plugin Studio", "That file already exists.")
            return False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            package_dir = target.parent
            while package_dir != plugin_dir:
                initializer = package_dir / "__init__.py"
                if not initializer.exists():
                    initializer.write_text(
                        '"""Composite device package."""\n', encoding="utf-8"
                    )
                package_dir = package_dir.parent
            target.write_text(
                '"""Composite device extension module."""\n', encoding="utf-8"
            )
        except OSError as error:
            QMessageBox.critical(self, "Plugin Studio", str(error))
            return False
        self.refresh_tree(target)
        self.codex_panel.select_plugin(plugin_dir)
        self._write_output(f"Added Python file: {target.relative_to(plugin_dir)}")
        return True

    def add_composite_python_file_with_codex(self, plugin_dir=None):
        """Start a staged Codex request for a new composite-device module."""
        plugin_dir = plugin_dir or self._selected_plugin_dir()
        if plugin_dir is None:
            return False
        plugin_dir = Path(plugin_dir).resolve()
        try:
            plugin_dir.relative_to(self.device_plugin_root.resolve())
            manifest = self._read_manifest(plugin_dir)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if not (
            manifest.get("type") == "device"
            and manifest.get("profile", "standard") == "composite"
        ):
            return False
        if self.codex_panel.request_active:
            QMessageBox.information(
                self, "Plugin Studio", "Wait for the current Codex request to finish."
            )
            return False
        relative_text, accepted = QInputDialog.getText(
            self,
            "Add Python File with Codex",
            "Relative path (for example services/camera_worker.py):",
        )
        if not accepted:
            return False
        try:
            target = resolve_plugin_python_path(plugin_dir, relative_text)
        except ValueError as error:
            QMessageBox.warning(self, "Plugin Studio", str(error))
            return False
        if target.exists():
            QMessageBox.warning(self, "Plugin Studio", "That file already exists.")
            return False
        self.codex_panel.select_plugin(plugin_dir)
        relative = target.relative_to(plugin_dir).as_posix()
        self.codex_panel.prompt.setPlainText(
            f"Create a new Python module at {relative}. Implement a clean scaffold "
            "appropriate for this composite device, keep blocking resources on "
            "their owning worker threads, and integrate it only where needed. "
            "Do not access real hardware while editing or validating."
        )
        self.codex_panel.send_prompt()
        return True

    def import_plugin(self):
        if not self.maybe_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import plugin",
            "",
            "UOSLab Plugin (*.uosplugin);;ZIP Archive (*.zip)",
        )
        if not path:
            return
        replace = False
        try:
            destination = import_plugin(
                Path(path), self.plugin_base_root, replace=False
            )
        except FileExistsError as error:
            existing = Path(str(error)).name
            answer = QMessageBox.question(
                self,
                "Replace plugin",
                f"Plugin '{existing}' is already installed. Replace it with the "
                "imported version?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            replace = True
            try:
                destination = import_plugin(
                    Path(path), self.plugin_base_root, replace=True
                )
            except Exception as import_error:
                QMessageBox.critical(
                    self, "Plugin import failed", str(import_error)
                )
                return
        except Exception as error:
            QMessageBox.critical(self, "Plugin import failed", str(error))
            return

        self.current_path = None
        self.editor.clear()
        self.editor.document().setModified(False)
        try:
            entrypoint_name = self._read_manifest(destination).get(
                "entrypoint", "plugin.py:plugin"
            ).partition(":")[0]
        except (OSError, ValueError, json.JSONDecodeError):
            entrypoint_name = "plugin.py"
        entrypoint = destination / entrypoint_name
        self.refresh_tree(entrypoint if entrypoint.is_file() else destination / "plugin.json")
        self.codex_panel.select_plugin(destination)
        action = "Replaced" if replace else "Imported"
        self._write_output(f"{action} plugin: {destination.name}\nReloading plugins...")
        self.reload_requested.emit()

    def export_plugin(self):
        if not self.save_current():
            return
        plugin_dir = self._selected_plugin_dir()
        if plugin_dir is None:
            QMessageBox.information(
                self, "Plugin Studio", "Select a plugin to export."
            )
            return
        suggested = str(Path.home() / f"{plugin_dir.name}.uosplugin")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export experiment plugin",
            suggested,
            "UOSLab Plugin (*.uosplugin)",
        )
        if not path:
            return
        try:
            archive_path = export_plugin(plugin_dir, Path(path))
        except Exception as error:
            QMessageBox.critical(self, "Plugin export failed", str(error))
            return
        self._write_output(f"Exported plugin: {archive_path}")

    def refresh_tree(self, select_path=None):
        selected = Path(select_path).resolve() if select_path else self.current_path
        self.tree.clear()
        target_item = None
        categories = (
            (
                "Experiments", self.plugin_root,
                lambda path: (path / "plugin.json").is_file(),
            ),
            (
                "Devices", self.device_plugin_root,
                lambda path: (path / "plugin.json").is_file(),
            ),
        )
        for title, root, is_plugin in categories:
            category_item = QTreeWidgetItem([title])
            category_item.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(category_item)
            if root.is_dir():
                for plugin_dir in sorted(
                    path for path in root.iterdir()
                    if path.is_dir() and is_plugin(path)
                ):
                    plugin_item = QTreeWidgetItem([plugin_dir.name])
                    plugin_item.setData(0, Qt.ItemDataRole.UserRole, str(plugin_dir))
                    plugin_item.setData(0, PLUGIN_ROOT_ROLE, str(plugin_dir))
                    category_item.addChild(plugin_item)
                    for path in sorted(plugin_dir.rglob("*"), key=lambda item: str(item)):
                        if (
                            not path.is_file()
                            or path.suffix not in {".py", ".json", ".md", ".txt"}
                            or "__pycache__" in path.parts
                        ):
                            continue
                        label = str(path.relative_to(plugin_dir))
                        item = QTreeWidgetItem([label])
                        item.setData(0, Qt.ItemDataRole.UserRole, str(path))
                        item.setData(
                            0, PLUGIN_ROOT_ROLE, str(plugin_dir)
                        )
                        plugin_item.addChild(item)
                        if selected and path.resolve() == Path(selected).resolve():
                            target_item = item
                    plugin_item.setExpanded(True)
            category_item.setExpanded(True)
        if target_item is not None:
            self.tree.setCurrentItem(target_item)

    def open_selected(self):
        items = self.tree.selectedItems()
        if not items:
            return
        path_value = items[0].data(0, Qt.ItemDataRole.UserRole)
        plugin_value = items[0].data(0, PLUGIN_ROOT_ROLE)
        if not path_value or not plugin_value:
            return
        path = Path(path_value)
        plugin_dir = Path(plugin_value)
        if path.is_dir():
            self.codex_panel.select_plugin(plugin_dir)
            return
        if not path.is_file() or path == self.current_path:
            return
        if not self.maybe_discard_changes():
            self.tree.blockSignals(True)
            self.tree.clearSelection()
            self.tree.blockSignals(False)
            return
        try:
            contents = path.read_text(encoding="utf-8")
        except OSError as error:
            self._write_output(f"ERROR: {error}")
            return
        self.current_path = path.resolve()
        self._loading = True
        self.editor.setPlainText(contents)
        self.editor.document().setModified(False)
        self.editor.set_changed_lines(
            self.codex_changed_lines.get(self.current_path, set())
        )
        self._loading = False
        self.editor.setEnabled(True)
        self.path_label.setText(str(self.current_path))
        self.editor.setFocus()
        self.codex_panel.select_plugin(plugin_dir)

    def _mark_modified(self):
        if not self._loading and self.current_path is not None:
            self.path_label.setText(str(self.current_path) + "  • modified")

    def save_current(self):
        if self.current_path is None or not self.editor.document().isModified():
            return True
        try:
            self.current_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, "Plugin Studio", str(error))
            return False
        self.editor.document().setModified(False)
        self.path_label.setText(str(self.current_path))
        self._write_output(f"Saved: {self.current_path.name}")
        return True

    def maybe_discard_changes(self):
        if not self.editor.document().isModified():
            return True
        answer = QMessageBox.question(
            self, "Unsaved plugin changes", "Save changes before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_current()
        return True

    def validate_all(self):
        if not self.save_current():
            return False
        errors = []
        experiment_count = 0
        device_count = 0
        seen_ids = set()
        seen_device_ids = set()
        for plugin_dir in sorted(
            path for path in self.plugin_root.iterdir()
            if path.is_dir() and (path / "plugin.json").is_file()
        ):
            manifest_path = plugin_dir / "plugin.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                plugin_id = manifest["id"]
                if manifest.get("type") != "experiment":
                    raise ValueError("type must be 'experiment'")
                validate_plugin_id(plugin_id)
                normalized_id = plugin_id.casefold()
                if normalized_id in seen_ids:
                    raise ValueError(f"duplicate id: {plugin_id}")
                seen_ids.add(normalized_id)
                entrypoint = manifest.get("entrypoint", "plugin.py:plugin")
                source_name, separator, export_name = entrypoint.partition(":")
                if not separator or not export_name:
                    raise ValueError("entrypoint must look like plugin.py:plugin")
                source_path = plugin_dir / source_name
                if source_path.resolve().parent != plugin_dir.resolve():
                    raise ValueError("entrypoint must stay inside the plugin folder")
                if not source_path.is_file():
                    raise ValueError(f"missing entrypoint file: {source_name}")
                experiment_count += 1
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"{plugin_dir.name}/plugin.json: {error}")
            for source_path in plugin_dir.rglob("*.py"):
                try:
                    ast.parse(source_path.read_text(encoding="utf-8"), str(source_path))
                except (OSError, SyntaxError) as error:
                    errors.append(f"{plugin_dir.name}/{source_path.name}: {error}")
        if self.device_plugin_root.is_dir():
            for plugin_dir in sorted(
                path for path in self.device_plugin_root.iterdir()
                if path.is_dir() and (path / "plugin.json").is_file()
            ):
                manifest_path = plugin_dir / "plugin.json"
                try:
                    manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    plugin_id = manifest["id"]
                    if manifest.get("type") != "device":
                        raise ValueError("type must be 'device'")
                    if manifest.get("profile", "standard") not in {
                        "standard", "composite",
                    }:
                        raise ValueError(
                            "profile must be 'standard' or 'composite'"
                        )
                    validate_plugin_id(plugin_id)
                    normalized_id = plugin_id.casefold()
                    if normalized_id in seen_device_ids:
                        raise ValueError(f"duplicate device id: {plugin_id}")
                    seen_device_ids.add(normalized_id)
                    entrypoint = manifest.get(
                        "entrypoint", "plugin.py:plugin"
                    )
                    source_name, separator, export_name = entrypoint.partition(":")
                    if not separator or not export_name:
                        raise ValueError(
                            "entrypoint must look like plugin.py:plugin"
                        )
                    source_path = (plugin_dir / source_name).resolve()
                    if (
                        source_path.parent != plugin_dir.resolve()
                        or not source_path.is_file()
                    ):
                        raise ValueError("invalid or missing entrypoint")
                    device_count += 1
                except (
                    OSError, KeyError, TypeError, ValueError,
                    json.JSONDecodeError,
                ) as error:
                    errors.append(f"{plugin_dir.name}/plugin.json: {error}")
                for source_path in plugin_dir.rglob("*.py"):
                    if "__pycache__" in source_path.parts:
                        continue
                    try:
                        ast.parse(
                            source_path.read_text(encoding="utf-8"),
                            str(source_path),
                        )
                    except (OSError, SyntaxError) as error:
                        errors.append(
                            f"Devices/{plugin_dir.name}/"
                            f"{source_path.relative_to(plugin_dir)}: {error}"
                        )
        if errors:
            self._write_output("Validation failed:\n" + "\n".join(f"• {e}" for e in errors))
            return False
        self._write_output(
            f"Validation passed: {experiment_count} experiment plugins, "
            f"{device_count} device plugins"
        )
        return True

    def request_reload(self):
        if self.validate_all():
            self.reload_requested.emit()

    def create_plugin(self):
        choices = (
            "Experiment",
            "Standard Device",
            "Composite Device",
        )
        choice, accepted = QInputDialog.getItem(
            self, "New Plugin", "Plugin type:", choices, 0, False
        )
        if not accepted:
            return
        if choice == "Experiment":
            self._create_experiment_plugin()
        else:
            profile = "composite" if choice == "Composite Device" else "standard"
            self._create_device_plugin(profile)

    def _create_experiment_plugin(self):
        plugin_id, accepted = QInputDialog.getText(
            self, "New experiment plugin",
            "Plugin ID (1-64 characters; start with a letter; use ASCII "
            "letters, numbers, or underscores):",
        )
        if not accepted:
            return
        plugin_id = plugin_id.strip()
        try:
            validate_plugin_id(plugin_id)
        except ValueError as error:
            QMessageBox.warning(self, "Plugin Studio", str(error))
            return
        plugin_dir = self.plugin_root / plugin_id
        if plugin_dir.exists() or self._plugin_id_in_use(
            self.plugin_root, plugin_id
        ):
            QMessageBox.warning(self, "Plugin Studio", "That plugin already exists.")
            return
        display_name = plugin_id.replace("_", " ").title()
        plugin_dir.mkdir(parents=True)
        manifest = {
            "schema_version": 1, "id": plugin_id, "name": display_name,
            "type": "experiment", "entrypoint": "plugin.py:plugin",
            "enabled": True, "api_version": "1",
        }
        (plugin_dir / "plugin.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        source = (
            "from core.plugin_manager import ExperimentPlugin, SequenceCommand\n\n\n"
            "def create_panel(manager, parent):\n"
            "    from .panel import ExperimentPanel\n"
            "    return ExperimentPanel(manager, parent)\n\n\n"
            "plugin = ExperimentPlugin(\n"
            f"    experiment_id={plugin_id!r},\n"
            f"    display_name={display_name!r},\n"
            "    panel_factory=create_panel,\n"
            "    sequence_commands=(\n"
            "        SequenceCommand(\n"
            "            key=\"set_value\", label=\"Set Value\", unit=\"\",\n"
            "            minimum=0.0, maximum=100.0, default=0.0, decimals=2,\n"
            "        ),\n"
            "    ),\n"
            "    description=\"User experiment panel\",\n"
            "    order=100,\n"
            ")\n"
        )
        panel_source = (
            "from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget\n\n"
            "from gui.widget_busy_spinner import run_busy_task\n\n\n"
            "class ExperimentPanel(QWidget):\n"
            "    def __init__(self, manager, parent=None):\n"
            "        super().__init__(parent)\n"
            "        self.manager = manager\n"
            "        layout = QVBoxLayout(self)\n"
            f"        self.status = QLabel({display_name!r})\n"
            "        layout.addWidget(self.status)\n"
            "        layout.addStretch()\n\n"
            "    def run_background(self, action, success, failure):\n"
            "        \"\"\"Run blocking work with the shared text-free loader.\"\"\"\n"
            "        return run_busy_task(\n"
            "            self, action, success, failure, key=\"plugin_task\"\n"
            "        )\n\n"
            "    def execute_sequence_command(self, command, value):\n"
            "        if command != \"set_value\":\n"
            "            raise ValueError(f\"Unsupported command: {command}\")\n"
            "        self.status.setText(f\"Value: {value}\")\n"
            "        return True  # False means Sequence should wait and poll\n\n"
            "    def is_sequence_command_complete(self, command, value):\n"
            "        return True\n\n"
            "    def cancel_sequence_command(self):\n"
            "        pass\n\n"
            "    def shutdown(self):\n"
            "        pass\n"
        )
        (plugin_dir / "panel.py").write_text(panel_source, encoding="utf-8")
        source_path = plugin_dir / "plugin.py"
        source_path.write_text(source, encoding="utf-8")
        self.refresh_tree(source_path)
        self.codex_panel.select_plugin(plugin_dir)
        self._write_output(f"Created panel plugin: {plugin_id}")

    def _create_device_plugin(self, profile):
        plugin_id, accepted = QInputDialog.getText(
            self,
            f"New {profile} device plugin",
            "Device ID (1-64 characters; start with a letter; use ASCII "
            "letters, numbers, or underscores):",
        )
        if not accepted:
            return
        plugin_id = plugin_id.strip()
        try:
            validate_plugin_id(plugin_id)
        except ValueError as error:
            QMessageBox.warning(self, "Plugin Studio", str(error))
            return
        plugin_dir = self.device_plugin_root / plugin_id
        if plugin_dir.exists() or self._plugin_id_in_use(
            self.device_plugin_root, plugin_id
        ):
            QMessageBox.warning(self, "Plugin Studio", "That device already exists.")
            return
        display_name = plugin_id.replace("_", " ").title()
        plugin_dir.mkdir(parents=True)
        manifest = {
            "schema_version": 1,
            "api_version": "1",
            "type": "device",
            "profile": profile,
            "id": plugin_id,
            "name": display_name,
            "version": "0.1.0",
            "entrypoint": "plugin.py:plugin",
            "enabled": True,
            "resources": [
                {
                    "id": "primary",
                    "roles": ["measurement", "control"],
                    "thread": "device_worker",
                }
            ],
            "permissions": [],
        }
        if profile == "composite":
            manifest["resources"].append({
                "id": "secondary",
                "roles": ["stream"],
                "thread": "dedicated_qthread",
            })
        (plugin_dir / "plugin.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (plugin_dir / "__init__.py").write_text(
            '"""User device plug-in package."""\n', encoding="utf-8"
        )
        driver_source = (
            '"""Hardware driver. Do not import or access Qt here."""\n\n\n'
            "class DeviceDriver:\n"
            "    def __init__(self, connection):\n"
            "        self.connection = connection\n"
            "        raise NotImplementedError(\"Implement the hardware connection\")\n\n"
            "    def read_all(self):\n"
            "        return {\"value\": 0.0}\n\n"
            "    def close(self):\n"
            "        pass\n"
        )
        (plugin_dir / "driver.py").write_text(driver_source, encoding="utf-8")
        (plugin_dir / "mock_driver.py").write_text(
            '"""Hardware-free driver used by validation and tests."""\n\n\n'
            "class MockDeviceDriver:\n"
            "    def __init__(self, _connection=\"mock\"):\n"
            "        self.closed = False\n\n"
            "    def read_all(self):\n"
            "        return {\"value\": 0.0}\n\n"
            "    def close(self):\n"
            "        self.closed = True\n",
            encoding="utf-8",
        )
        if profile == "composite":
            panel_class = "CompositeDevicePanel"
            panel_source = (
                '"""Custom GUI for a composite device."""\n\n'
                "from gui.panel_device import DeviceSettingsPanel\n\n\n"
                "class CompositeDevicePanel(DeviceSettingsPanel):\n"
                "    \"\"\"Extend this panel for secondary resources or streams.\"\"\"\n\n"
                "    def shutdown(self):\n"
                "        pass\n"
            )
        else:
            panel_class = "StandardDevicePanel"
            panel_source = (
                '"""Default GUI for a standard device."""\n\n'
                "from gui.panel_device import DeviceSettingsPanel\n\n\n"
                "class StandardDevicePanel(DeviceSettingsPanel):\n"
                "    \"\"\"Basic connection panel ready for device controls.\"\"\"\n\n"
                "    pass\n"
            )
        (plugin_dir / "panel.py").write_text(panel_source, encoding="utf-8")
        panel_factory_import = (
            f"from .panel import {panel_class}\n"
            f"    return {panel_class}(manager, plugin, parent)"
        )
        plugin_source = (
            "from core.plugin_manager import DataColumn, DevicePlugin\n\n\n"
            "def create_settings_panel(manager, parent):\n"
            f"    {panel_factory_import}\n\n\n"
            f"class {plugin_id}Plugin(DevicePlugin):\n"
            f"    device_id = {plugin_id!r}\n"
            f"    display_name = {display_name!r}\n"
            f"    profile = {profile!r}\n"
            "    connection_label = \"Connection\"\n"
            "    default_connection = \"\"\n"
            "    columns = (DataColumn(\"value\", "
            f"{(plugin_id + '_value')!r}),)\n"
            "    settings_factory = staticmethod(create_settings_panel)\n\n"
            "    def connect(self, connection):\n"
            "        from .driver import DeviceDriver\n"
            "        return DeviceDriver(connection)\n\n\n"
            f"plugin = {plugin_id}Plugin()\n"
        )
        source_path = plugin_dir / "plugin.py"
        source_path.write_text(plugin_source, encoding="utf-8")
        (plugin_dir / "README.md").write_text(
            f"# {display_name}\n\n"
            f"Device profile: `{profile}`. Complete `driver.py`, update the "
            "measurement columns, and add contract tests before connecting hardware.\n",
            encoding="utf-8",
        )
        self.refresh_tree(source_path)
        self.codex_panel.select_plugin(plugin_dir)
        self._write_output(
            f"Created {profile} device plugin: {plugin_id}"
        )

    def remove_plugin(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(
                self, "Plugin Studio", "Select a plugin or one of its files first."
            )
            return
        plugin_value = items[0].data(0, PLUGIN_ROOT_ROLE)
        if not plugin_value:
            return
        plugin_dir = Path(plugin_value)
        try:
            plugin_dir = plugin_dir.resolve()
            category_root = next(
                root.resolve()
                for root in (self.plugin_root, self.device_plugin_root)
                if plugin_dir.parent == root.resolve()
            )
        except (OSError, ValueError):
            QMessageBox.critical(
                self, "Plugin Studio", "The selected path is not a user plugin."
            )
            return
        except StopIteration:
            QMessageBox.critical(
                self, "Plugin Studio", "The selected path is not a plugin folder."
            )
            return
        if plugin_dir.parent != category_root or not plugin_dir.is_dir():
            QMessageBox.critical(
                self, "Plugin Studio", "The selected path is not a plugin folder."
            )
            return
        answer = QMessageBox.warning(
            self,
            "Remove plugin",
            f"Remove '{plugin_dir.name}' and all files in its plugin folder?\n\n"
            "This cannot be undone from Plugin Studio.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.maybe_discard_changes():
            return
        try:
            shutil.rmtree(plugin_dir)
        except OSError as error:
            QMessageBox.critical(self, "Plugin Studio", f"Could not remove plugin: {error}")
            return
        removed_id = plugin_dir.name
        self.codex_panel.clear_plugin()
        self.current_path = None
        self.editor.clear()
        self.editor.document().setModified(False)
        self.path_label.setText("No file selected")
        self.refresh_tree()
        self._write_output(f"Removed plugin: {removed_id}")
        self.reload_requested.emit()

    def edit_plugin_id(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(
                self, "Plugin Studio", "Select a plugin or one of its files first."
            )
            return
        plugin_value = items[0].data(0, PLUGIN_ROOT_ROLE)
        if not plugin_value:
            return
        plugin_dir = Path(plugin_value)
        try:
            plugin_dir = plugin_dir.resolve()
            if plugin_dir.parent not in {
                self.plugin_root.resolve(), self.device_plugin_root.resolve()
            }:
                raise ValueError("plugin is outside the editable roots")
        except (OSError, ValueError):
            QMessageBox.critical(
                self, "Plugin Studio", "The selected path is not an editable plugin."
            )
            return
        manifest_path = plugin_dir / "plugin.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            old_id = manifest["id"]
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.critical(self, "Plugin Studio", f"Cannot read manifest: {error}")
            return
        new_id, accepted = QInputDialog.getText(
            self, "Edit plugin ID",
            "Plugin ID (1-64 characters; start with a letter; use ASCII "
            "letters, numbers, or underscores):",
            text=old_id,
        )
        if not accepted:
            return
        new_id = new_id.strip()
        if new_id == old_id:
            return
        try:
            validate_plugin_id(new_id)
        except ValueError as error:
            QMessageBox.warning(self, "Plugin Studio", str(error))
            return
        destination = plugin_dir.parent / new_id
        if self._plugin_id_in_use(plugin_dir.parent, new_id, exclude=plugin_dir):
            QMessageBox.warning(self, "Plugin Studio", "That plugin ID already exists.")
            return
        if destination.exists() and destination.resolve() != plugin_dir.resolve():
            QMessageBox.warning(self, "Plugin Studio", "That plugin ID already exists.")
            return
        if not self.maybe_discard_changes():
            return
        try:
            manifest["id"] = new_id
            manifest_path.write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
            entrypoint = manifest.get("entrypoint", "plugin.py:plugin").partition(":")[0]
            source_path = plugin_dir / entrypoint
            if source_path.is_file():
                source = source_path.read_text(encoding="utf-8")
                identifier_field = (
                    "device_id" if manifest.get("type") == "device"
                    else "experiment_id"
                )
                source = re.sub(
                    rf"({identifier_field}\s*=\s*)(['\"])(?:\\.|(?!\2).)*\2",
                    lambda match: match.group(1) + repr(new_id),
                    source,
                    count=1,
                )
                source_path.write_text(source, encoding="utf-8")
            if destination != plugin_dir:
                if destination.exists():
                    temporary = plugin_dir.parent / f".__rename_{old_id}__"
                    plugin_dir.rename(temporary)
                    temporary.rename(destination)
                else:
                    plugin_dir.rename(destination)
            self.current_path = None
            self.editor.clear()
            self.editor.document().setModified(False)
            self.path_label.setText("No file selected")
            target = destination / entrypoint
            self.refresh_tree(target if target.is_file() else destination / "plugin.json")
            self.codex_panel.select_plugin(destination)
            self._write_output(f"Changed plugin ID: {old_id} → {new_id}")
        except OSError as error:
            QMessageBox.critical(self, "Plugin Studio", f"Could not change ID: {error}")

    def _write_output(self, message):
        self.codex_panel.set_activity(message)

    def _codex_changes_applied(self, plugin_dir, changed_lines):
        plugin_root = Path(plugin_dir).resolve()
        self.codex_changed_lines = {
            path: lines
            for path, lines in self.codex_changed_lines.items()
            if plugin_root not in path.parents and path != plugin_root
        }
        for relative_path, lines in changed_lines.items():
            path = (plugin_root / relative_path).resolve()
            if path.is_file():
                self.codex_changed_lines[path] = set(lines)

        current = self.current_path
        self.current_path = None
        self.refresh_tree(current if current and current.exists() else None)
        if current is not None and current.exists():
            self._loading = True
            self.editor.setPlainText(current.read_text(encoding="utf-8"))
            self.editor.document().setModified(False)
            self.editor.set_changed_lines(
                self.codex_changed_lines.get(current.resolve(), set())
            )
            self._loading = False
            self.current_path = current
            self.path_label.setText(str(current))
        else:
            self._loading = True
            self.editor.clear()
            self.editor.document().setModified(False)
            self.editor.clear_changed_lines()
            self._loading = False
            self.path_label.setText("No file selected")
        self.validate_all()

    def shutdown(self):
        self.codex_panel.shutdown()
