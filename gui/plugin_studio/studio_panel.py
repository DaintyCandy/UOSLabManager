import ast
import json
import re
import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import (
    export_experiment_plugin, get_plugin_root, import_experiment_plugin,
)
from .code_editor import CodeEditor
from .codex_panel import CodexPanel

PLUGIN_ROOT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class PluginStudioPanel(QWidget):
    reload_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plugin_root = get_plugin_root() / "experiments"
        self.device_plugin_root = Path(__file__).resolve().parents[2] / "plugins" / "devices"
        self.plugin_root.mkdir(parents=True, exist_ok=True)
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
            ("Edit ID", self.edit_plugin_id),
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
        self.tree.setMinimumWidth(230)
        self.tree.itemSelectionChanged.connect(self.open_selected)
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

    def import_plugin(self):
        if not self.maybe_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import experiment plugin",
            "",
            "UOSLab Plugin (*.uosplugin);;ZIP Archive (*.zip)",
        )
        if not path:
            return
        replace = False
        try:
            destination = import_experiment_plugin(
                Path(path), self.plugin_root, replace=False
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
                destination = import_experiment_plugin(
                    Path(path), self.plugin_root, replace=True
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
        entrypoint = destination / "plugin.py"
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
                self, "Plugin Studio", "Select an experiment plugin to export."
            )
            return
        try:
            plugin_dir.relative_to(self.plugin_root.resolve())
        except ValueError:
            QMessageBox.information(
                self,
                "Plugin Studio",
                "Built-in device plugins are part of the application and cannot be "
                "exported from Plugin Studio.",
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
            archive_path = export_experiment_plugin(plugin_dir, Path(path))
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
                lambda path: (path / "plugin.py").is_file(),
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
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", plugin_id):
                    raise ValueError(
                        "id must start with a letter and use letters, numbers, or underscores"
                    )
                if plugin_id in seen_ids:
                    raise ValueError(f"duplicate id: {plugin_id}")
                seen_ids.add(plugin_id)
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
                if path.is_dir() and (path / "plugin.py").is_file()
            ):
                device_count += 1
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
        plugin_id, accepted = QInputDialog.getText(
            self, "New experiment plugin", "Plugin ID (letters, numbers, underscores):"
        )
        plugin_id = plugin_id.strip()
        if not accepted:
            return
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", plugin_id):
            QMessageBox.warning(self, "Plugin Studio", "Invalid plugin ID.")
            return
        plugin_dir = self.plugin_root / plugin_id
        if plugin_dir.exists():
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
            "from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget\n\n\n"
            "class ExperimentPanel(QWidget):\n"
            "    def __init__(self, manager, parent=None):\n"
            "        super().__init__(parent)\n"
            "        self.manager = manager\n"
            "        layout = QVBoxLayout(self)\n"
            f"        self.status = QLabel({display_name!r})\n"
            "        layout.addWidget(self.status)\n"
            "        layout.addStretch()\n\n"
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
            plugin_dir.relative_to(self.plugin_root.resolve())
        except (OSError, ValueError):
            QMessageBox.critical(
                self, "Plugin Studio", "The selected path is not a user plugin."
            )
            return
        if plugin_dir.parent != self.plugin_root.resolve() or not plugin_dir.is_dir():
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
            plugin_dir.resolve().relative_to(self.plugin_root.resolve())
        except ValueError:
            QMessageBox.information(
                self, "Plugin Studio",
                "Device plugin IDs are defined by their DevicePlugin class and cannot "
                "be renamed from Studio.",
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
            self, "Edit plugin ID", "Plugin ID:", text=old_id
        )
        new_id = new_id.strip()
        if not accepted or new_id == old_id:
            return
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", new_id):
            QMessageBox.warning(
                self, "Plugin Studio",
                "ID must start with a letter and contain only letters, numbers, and underscores.",
            )
            return
        destination = plugin_dir.parent / new_id
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
                source = re.sub(
                    r"(experiment_id\s*=\s*)(['\"])(?:\\.|(?!\2).)*\2",
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
