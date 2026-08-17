import ast
import difflib
import html
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from dataclasses import asdict, is_dataclass
from pathlib import Path

from core.plugin_manager import validate_plugin_id
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QTextOption
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTextBrowser,
    QTextEdit, QVBoxLayout, QWidget,
)


EDITABLE_SUFFIXES = {".py", ".json", ".md", ".txt"}


class CodexWorker(QThread):
    completed = pyqtSignal(str, object)
    failed = pyqtSignal(str)
    ready = pyqtSignal()
    workflow = pyqtSignal(str, str)

    def __init__(self, workspace, plugin_kind, model, effort, parent=None):
        super().__init__(parent)
        self.workspace = Path(workspace)
        self.plugin_kind = plugin_kind
        self.model = model
        self.effort = effort
        self.requests = queue.Queue()
        self.stop_requested = False
        self.turn_handle = None

    def run(self):
        try:
            from openai_codex import Codex, Sandbox
        except ImportError:
            self.failed.emit(
                "Codex SDK is not installed. Install the 'openai-codex' package."
            )
            return
        instructions = (
            f"You are editing one UOSLabManager {self.plugin_kind} plugin in an isolated "
            "workspace. Only edit files inside the current workspace. Do not use "
            "network access, do not access hardware, and do not modify files outside "
            "this workspace. Preserve plugin.json, ExperimentPlugin API compatibility, "
            "and safe shutdown behavior. Keep all QWidget creation and mutation on the "
            "Qt GUI thread. Run blocking connection, device, file, and analysis work "
            "through DeviceManager workers, QThread, or "
            "gui.widget_busy_spinner.run_busy_task. Let that helper show its shared "
            "text-free spinner only when a user-triggered task exceeds the loading "
            "delay; never instantiate or show the spinner manually. Never call "
            "time.sleep or wait for hardware on the GUI thread, prevent duplicate "
            "starts, and release timers/threads in shutdown(). Consume measurement "
            "data through DeviceManager snapshots and retain sample timestamps, IDs, "
            "and freshness metadata instead of repeatedly logging cached values. "
            "When plugin.json declares a composite device, you may create additional "
            "Python modules and nested packages inside the workspace for independent "
            "resources, services, platform resolvers, mocks, and tests. "
            "Inspect existing files only as needed. Make "
            "the requested edits directly, then summarize the changes briefly."
        )
        try:
            codex = self._start_codex(Codex)
            with codex:
                thread = codex.thread_start(
                    cwd=str(self.workspace),
                    model=self.model,
                    sandbox=Sandbox.workspace_write,
                    developer_instructions=instructions,
                    ephemeral=True,
                )
                self.ready.emit()
                while not self.stop_requested:
                    prompt = self.requests.get()
                    if prompt is None or self.stop_requested:
                        break
                    try:
                        self.turn_handle = thread.turn(
                            prompt,
                            effort=self.effort,
                            sandbox=Sandbox.workspace_write,
                        )
                        from openai_codex._run import _collect_turn_result

                        def observed_events():
                            reasoning_parts = []
                            for event in self.turn_handle.stream():
                                if event.method == "item/reasoning/summaryTextDelta":
                                    delta = getattr(event.payload, "delta", "")
                                    if delta:
                                        reasoning_parts.append(delta)
                                    yield event
                                    continue
                                item = getattr(event.payload, "item", None)
                                item = getattr(item, "root", item)
                                is_reasoning_complete = (
                                    event.method == "item/completed"
                                    and getattr(item, "type", None) == "reasoning"
                                )
                                if is_reasoning_complete:
                                    summary = "".join(reasoning_parts).strip()
                                    if not summary:
                                        summary = "\n".join(
                                            getattr(item, "summary", ()) or ()
                                        ).strip()
                                    if summary:
                                        self.workflow.emit("REASONING", summary)
                                    reasoning_parts.clear()
                                    yield event
                                    continue
                                if event.method == "turn/completed" and reasoning_parts:
                                    summary = "".join(reasoning_parts).strip()
                                    if summary:
                                        self.workflow.emit("REASONING", summary)
                                    reasoning_parts.clear()
                                workflow = self._workflow_message(event)
                                if workflow is not None:
                                    self.workflow.emit(*workflow)
                                yield event

                        result = _collect_turn_result(
                            observed_events(), turn_id=self.turn_handle.id
                        )
                        self.completed.emit(
                            result.final_response
                            or "Codex finished without a response.",
                            self._usage_dict(result.usage),
                        )
                    except Exception as error:
                        self.failed.emit(str(error))
                    finally:
                        self.turn_handle = None
        except Exception as error:
            self.failed.emit(str(error))

    @staticmethod
    def _start_codex(codex_class):
        """Start the bundled Codex runtime without opening a Windows console."""
        if os.name != "nt":
            return codex_class()
        import openai_codex.client as codex_client

        original_popen = codex_client.subprocess.Popen

        def hidden_popen(*args, **kwargs):
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
            )
            return original_popen(*args, **kwargs)

        codex_client.subprocess.Popen = hidden_popen
        try:
            return codex_class()
        finally:
            codex_client.subprocess.Popen = original_popen

    def submit(self, prompt):
        self.requests.put(prompt)

    @staticmethod
    def _value(value):
        return getattr(value, "value", value)

    @classmethod
    def _workflow_message(cls, event):
        method = event.method
        payload = event.payload
        if method == "turn/started":
            return "TURN", "Started"
        if method == "turn/plan/updated":
            steps = [
                f"[{cls._value(step.status)}] {step.step}"
                for step in getattr(payload, "plan", ())
            ]
            explanation = getattr(payload, "explanation", None)
            message = "\n".join(filter(None, [explanation, *steps]))
            return "PLAN", message or "Plan updated"
        if method == "turn/diff/updated":
            return "WORKFLOW", "Proposed file diff updated"
        if method == "item/mcpToolCall/progress":
            return "TOOL", getattr(payload, "message", "Tool call in progress")
        if method not in {"item/started", "item/completed"}:
            return None

        item = getattr(payload, "item", None)
        item = getattr(item, "root", item)
        item_type = getattr(item, "type", None)
        phase = "START" if method == "item/started" else "DONE"
        if item_type == "commandExecution":
            command = getattr(item, "command", "")
            if phase == "START":
                return "COMMAND", command
            status = cls._value(getattr(item, "status", "completed"))
            exit_code = getattr(item, "exit_code", None)
            suffix = f" (exit {exit_code})" if exit_code is not None else ""
            return "COMMAND", f"{status}{suffix}: {command}"
        if item_type == "fileChange":
            changes = getattr(item, "changes", ())
            paths = []
            for change in changes:
                path = getattr(change, "path", None)
                if path:
                    paths.append(str(path))
            status = cls._value(getattr(item, "status", phase.lower()))
            detail = ", ".join(paths) if paths else "plugin files"
            return "FILE", f"{status}: {detail}"
        if item_type == "mcpToolCall":
            server = getattr(item, "server", "MCP")
            tool = getattr(item, "tool", "tool")
            status = cls._value(getattr(item, "status", phase.lower()))
            return "TOOL", f"{server}.{tool}: {status}"
        if item_type == "reasoning" and phase == "DONE":
            summary = "\n".join(getattr(item, "summary", ()) or ())
            return "REASONING", summary or "Reasoning step completed"
        return None

    def stop(self):
        self.stop_requested = True
        if self.turn_handle is not None:
            try:
                self.turn_handle.interrupt()
            except Exception:
                pass
        self.requests.put(None)

    @staticmethod
    def _usage_dict(usage):
        if usage is None:
            return {}
        if is_dataclass(usage):
            return asdict(usage)
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if hasattr(usage, "to_dict"):
            return usage.to_dict()
        if hasattr(usage, "__dict__"):
            return dict(usage.__dict__)
        return {"usage": str(usage)}


class CodexPanel(QWidget):
    changes_applied = pyqtSignal(str, object)
    REASONING_LEVELS = ("low", "medium", "high", "xhigh", "max", "ultra")

    def __init__(self, parent=None, prepare_callback=None):
        super().__init__(parent)
        self.prepare_callback = prepare_callback
        self.plugin_dir = None
        self.plugin_kind = None
        self.staging_root = None
        self.staging_dir = None
        self.original_files = {}
        self.worker = None
        self.pending_request = None
        self.request_active = False
        self.model_efforts = {
            "gpt-5.6-terra": "medium",
            "gpt-5.6-sol": "low",
        }
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        title = QLabel("Codex")
        title.setStyleSheet("font-size:13pt; font-weight:700;")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("Model"))
        self.model_combo = QComboBox()
        self.model_combo.addItem("GPT-5.6 Terra", "gpt-5.6-terra")
        self.model_combo.addItem("GPT-5.6 Sol", "gpt-5.6-sol")
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        header.addWidget(self.model_combo)
        header.addWidget(QLabel("Reasoning"))
        self.reasoning_combo = QComboBox()
        for effort in self.REASONING_LEVELS:
            self.reasoning_combo.addItem(effort.capitalize(), effort)
        self.reasoning_combo.currentIndexChanged.connect(self._reasoning_changed)
        header.addWidget(self.reasoning_combo)
        self._set_reasoning_for_model(self.current_model())
        layout.addLayout(header)
        self.status = QLabel("Select a plugin to start")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.log_view = QTextBrowser()
        self.log_view.setPlaceholderText(
            "Codex responses, proposed changes, and validation results appear here"
        )
        self.log_view.setFont(self.font())
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_view.setWordWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self.log_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        layout.addWidget(self.log_view, 1)
        # Compatibility alias for callers that previously targeted validation output.
        self.activity_view = self.log_view

        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText(
            "Ask Codex to modify the selected plugin…\n"
            "Example: Add a sequence command that changes the setpoint."
        )
        self.prompt.setMaximumHeight(100)
        layout.addWidget(self.prompt)
        send_row = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_prompt)
        send_row.addWidget(self.send_button)
        send_row.addStretch()
        self.staged_label = QLabel("NO STAGED CHANGES")
        self.staged_label.setStyleSheet(
            "color:#8b949e; font-weight:700; letter-spacing:1px;"
        )
        send_row.addWidget(self.staged_label)
        self.apply_button = QPushButton("Apply")
        self.apply_button.clicked.connect(self.apply_changes)
        self.reject_button = QPushButton("Reject")
        self.reject_button.clicked.connect(self.reject_changes)
        send_row.addWidget(self.apply_button)
        send_row.addWidget(self.reject_button)
        layout.addLayout(send_row)
        self.send_button.setEnabled(False)
        self._set_staging_state(False)

    def _log(self, category, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        escaped_message = html.escape(str(message)).replace("\n", "<br>")
        self.log_view.append(
            f"<div><b>[{timestamp}] [{html.escape(category)}]</b><br>"
            f"{escaped_message}</div>"
        )
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _model_changed(self):
        if self.request_active:
            return
        self._stop_worker()
        self._set_reasoning_for_model(self.current_model())
        if self.plugin_dir is not None:
            self._update_selection_status()
            self._log(
                "SYSTEM",
                f"Model changed to {self.current_model()} "
                f"(reasoning: {self.current_effort()})",
            )

    def _reasoning_changed(self):
        model = self.current_model()
        effort = self.current_effort()
        if model and effort:
            self.model_efforts[model] = effort
        if self.plugin_dir is not None and not self.request_active:
            self._stop_worker()
            self._update_selection_status()
            self._log("SYSTEM", f"Reasoning changed to {effort}")

    def _set_reasoning_for_model(self, model):
        effort = self.model_efforts.get(model, "medium")
        index = self.reasoning_combo.findData(effort)
        self.reasoning_combo.blockSignals(True)
        self.reasoning_combo.setCurrentIndex(max(0, index))
        self.reasoning_combo.blockSignals(False)

    def _update_selection_status(self):
        if self.plugin_dir is not None:
            self.status.setText(
                f"Plugin: {self.plugin_dir.name}\n"
                f"Model: {self.current_model()} / reasoning: {self.current_effort()}"
            )

    def current_model(self):
        return self.model_combo.currentData()

    def current_effort(self):
        return self.reasoning_combo.currentData()

    def _set_staging_state(self, staged):
        self.apply_button.setEnabled(staged)
        self.reject_button.setEnabled(staged)
        if staged:
            self.staged_label.setText("STAGED CHANGES READY")
            self.staged_label.setStyleSheet(
                "color:#f9ab00; font-weight:800; letter-spacing:1px;"
            )
            self.apply_button.setStyleSheet(
                "QPushButton { background:#188038; color:white; font-weight:700; "
                "border:1px solid #34a853; padding:5px 14px; }"
                "QPushButton:hover { background:#1e8e3e; }"
            )
            self.reject_button.setStyleSheet(
                "QPushButton { background:#b3261e; color:white; font-weight:700; "
                "border:1px solid #ea4335; padding:5px 14px; }"
                "QPushButton:hover { background:#c5221f; }"
            )
        else:
            self.staged_label.setText("NO STAGED CHANGES")
            self.staged_label.setStyleSheet(
                "color:#8b949e; font-weight:700; letter-spacing:1px;"
            )
            self.apply_button.setStyleSheet("")
            self.reject_button.setStyleSheet("")

    def select_plugin(self, plugin_dir):
        plugin_dir = Path(plugin_dir).resolve()
        if self.plugin_dir == plugin_dir:
            return
        if self.request_active:
            QMessageBox.information(
                self, "Codex", "Wait for the current Codex request to finish."
            )
            return
        self._stop_worker()
        self._clear_staging()
        self.plugin_dir = plugin_dir
        try:
            manifest = json.loads(
                (plugin_dir / "plugin.json").read_text(encoding="utf-8")
            )
            self.plugin_kind = manifest.get("type")
        except (OSError, ValueError, json.JSONDecodeError):
            self.plugin_kind = None
        if self.plugin_kind not in {"experiment", "device"}:
            self.plugin_kind = "device"
        self.log_view.clear()
        self._set_staging_state(False)
        self.send_button.setEnabled(plugin_dir.is_dir())
        self._update_selection_status()
        self._log("SYSTEM", f"Selected plugin: {plugin_dir.name}")

    def clear_plugin(self):
        self._stop_worker()
        self._clear_staging()
        self.plugin_dir = None
        self.send_button.setEnabled(False)
        self._set_staging_state(False)
        self.status.setText("Select a plugin to start")
        self.log_view.clear()

    def send_prompt(self):
        request = self.prompt.toPlainText().strip()
        if not request or self.plugin_dir is None or self.request_active:
            return
        if self.prepare_callback is not None and not self.prepare_callback():
            return
        if (
            self.staging_dir is not None
            and self._read_editable_files(self.plugin_dir) != self.original_files
        ):
            QMessageBox.warning(
                self, "Codex",
                "The plugin changed after this Codex draft started. Reject the draft "
                "before sending another request.",
            )
            return
        try:
            if self.staging_dir is None:
                self._create_staging()
        except OSError as error:
            QMessageBox.critical(self, "Codex staging failed", str(error))
            return
        self.prompt.clear()
        self._log("YOU", request)
        self.status.setText("Codex is working…")
        self.send_button.setEnabled(False)
        self.model_combo.setEnabled(False)
        self.reasoning_combo.setEnabled(False)
        self.request_active = True
        if self.worker is None or not self.worker.isRunning():
            self.pending_request = request
            self.worker = CodexWorker(
                self.staging_dir, self.plugin_kind, self.current_model(),
                self.current_effort(), self,
            )
            self.worker.completed.connect(self._codex_completed)
            self.worker.failed.connect(self._codex_failed)
            self.worker.ready.connect(self._worker_ready)
            self.worker.workflow.connect(self._workflow_event)
            self.worker.finished.connect(self._worker_finished)
            self.worker.start()
        else:
            self.worker.submit(request)

    def _worker_ready(self):
        if self.pending_request is not None and self.worker is not None:
            request = self.pending_request
            self.pending_request = None
            self.worker.submit(request)

    def _workflow_event(self, category, message):
        self._log(category, message)

    def _codex_completed(self, response, _usage):
        self._log("CODEX", response)
        diff = self._build_diff()
        self._set_staging_state(bool(diff))
        self._log("PROPOSED CHANGES", diff or "No editable plugin files changed.")
        self._log("VALIDATION", self._validate_staged())
        self.status.setText("Review the proposed changes")
        self.request_active = False
        self.model_combo.setEnabled(True)
        self.reasoning_combo.setEnabled(True)
        self.send_button.setEnabled(self.plugin_dir is not None)

    def _codex_failed(self, error):
        self._log("CODEX ERROR", error)
        self.status.setText("Codex request failed")
        self.request_active = False
        self.model_combo.setEnabled(True)
        self.reasoning_combo.setEnabled(True)
        self.send_button.setEnabled(self.plugin_dir is not None)

    def _worker_finished(self):
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.pending_request = None
        self.request_active = False
        self.model_combo.setEnabled(True)
        self.reasoning_combo.setEnabled(True)
        self.send_button.setEnabled(self.plugin_dir is not None)

    def _update_usage(self, usage):
        flat = {}

        def flatten(value, prefix=""):
            if isinstance(value, dict):
                for key, child in value.items():
                    flatten(child, f"{prefix}.{key}" if prefix else str(key))
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                flat[prefix.lower()] = int(value)

        flatten(usage)

        def normalized(value):
            return "".join(character for character in value.lower() if character.isalnum())

        def find(section, *names):
            wanted = {normalized(name) for name in names}
            for key, value in flat.items():
                parts = key.split(".")
                if normalized(parts[-1]) not in wanted:
                    continue
                if section is None or normalized(section) in {
                    normalized(part) for part in parts[:-1]
                }:
                    return value
            return 0

        current = {
            "input": find("last", "input_tokens"),
            "cached": find("last", "cached_input_tokens", "cached_tokens"),
            "output": find("last", "output_tokens"),
            "total": find("last", "total_tokens"),
        }
        if not any(current.values()):
            current = {
                "input": find(None, "input_tokens"),
                "cached": find(None, "cached_input_tokens", "cached_tokens"),
                "output": find(None, "output_tokens"),
                "total": find(None, "total_tokens"),
            }
        if not current["total"]:
            current["total"] = current["input"] + current["output"]
        sdk_session_total = find("total", "total_tokens")
        if sdk_session_total:
            self.cumulative_usage["total"] = sdk_session_total
        else:
            self.cumulative_usage["total"] += current["total"]
        context_window = find(
            None, "model_context_window", "context_window", "context_window_tokens"
        ) or 1_050_000
        context_used = sdk_session_total or self.cumulative_usage["total"]
        context_percent = min(100.0, context_used * 100.0 / context_window)
        self.context_bar.setValue(round(context_percent * 10))
        self.context_bar.setFormat(f"Context usage: {context_percent:.1f}%")
        self.usage_label.setText(
            "Last: input {input:,} / cached {cached:,} / output {output:,} / "
            "total {total:,}\nSession total: {session:,}".format(
                **current, session=self.cumulative_usage["total"]
            )
        )

    def _create_staging(self):
        self.staging_root = Path(tempfile.mkdtemp(prefix="uoslab-codex-plugin-"))
        self.staging_dir = self.staging_root / self.plugin_dir.name
        self.staging_dir.mkdir()
        self.original_files = self._read_editable_files(self.plugin_dir)
        for relative, contents in self.original_files.items():
            target = self.staging_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
        if self.plugin_kind == "device":
            try:
                manifest = json.loads(
                    (self.plugin_dir / "plugin.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError):
                manifest = {}
            profile = manifest.get("profile", "standard")
            api_notes = (
                "# UOSLabManager device plugin\n\n"
                f"This is a `{profile}` device package. Keep `plugin.json` and "
                "`plugin.py` exporting a `DevicePlugin` instance. Device packages "
                "normally contain `driver.py`, `panel.py`, and `plugin.py`. The driver "
                "must implement `read_all()` returning a dictionary and `close()`. "
                "Optional sequence commands belong in the DevicePlugin's "
                "`sequence_commands` tuple. Declare each command with "
                "`SequenceCommand` metadata and an executor accepting "
                "`(device, value, context)`; do not add device dispatch branches to "
                "the sequence GUI. "
                "Connect and run panel device commands with `run_busy_task` so no "
                "DeviceProxy call blocks the GUI. Let its delayed shared spinner "
                "remain text-free; do not show a custom spinner. QWidget updates "
                "belong on the GUI thread, while hardware and blocking work belong on "
                "the device worker. Consume timestamped DeviceManager snapshots for "
                "measurement data and do not duplicate cached samples. Panels must "
                "safely stop timers and threads in `shutdown()`. Do not "
                "send commands to real hardware while editing or validating. "
                + (
                    "You may create any additional `.py` modules or nested Python "
                    "packages needed for independent resources, platform resolvers, "
                    "services, or tests. Keep every new file inside this plug-in "
                    "workspace and give each blocking resource one owning thread.\n"
                    if profile == "composite"
                    else "Keep the standard package small and prefer the shared panel.\n"
                )
            )
        else:
            api_notes = (
                "# UOSLabManager experiment plugin\n\n"
                "Keep `plugin.json` and `plugin.py`. Panel plugins expose an "
                "`ExperimentPlugin` object. Optional Sequence commands are declared "
                "with `SequenceCommand` in plugin.py and implemented by "
                "`execute_sequence_command`, `is_sequence_command_complete`, and "
                "`cancel_sequence_command` in panel.py. Run blocking work with "
                "`run_busy_task` or QThread and use the delayed shared text-free "
                "spinner instead of showing a custom loader. "
                "Keep QWidget access on the GUI thread, avoid duplicate task starts, "
                "and consume timestamped snapshots without logging cached samples "
                "again. Always implement `shutdown` "
                "for timers, threads, and hardware cleanup.\n"
            )
        (self.staging_dir / "PLUGIN_API.md").write_text(
            api_notes, encoding="utf-8"
        )

    @staticmethod
    def _read_editable_files(root):
        files = {}
        for path in root.rglob("*"):
            if (
                path.is_file()
                and not path.is_symlink()
                and path.suffix.lower() in EDITABLE_SUFFIXES
                and path.stat().st_size <= 1_000_000
                and "__pycache__" not in path.parts
            ):
                files[path.relative_to(root)] = path.read_text(encoding="utf-8")
        return files

    def _staged_files(self):
        files = self._read_editable_files(self.staging_dir)
        files.pop(Path("PLUGIN_API.md"), None)
        return files

    def _build_diff(self):
        staged = self._staged_files()
        chunks = []
        for relative in sorted(set(self.original_files) | set(staged), key=str):
            before = self.original_files.get(relative, "").splitlines(keepends=True)
            after = staged.get(relative, "").splitlines(keepends=True)
            chunks.extend(difflib.unified_diff(
                before, after,
                fromfile=f"a/{relative.as_posix()}",
                tofile=f"b/{relative.as_posix()}",
            ))
        return "".join(chunks)

    def _validate_staged(self):
        if self.staging_dir is None:
            return "No staged changes to validate."
        errors = []
        python_files = list(self.staging_dir.rglob("*.py"))
        for source_path in python_files:
            try:
                ast.parse(source_path.read_text(encoding="utf-8"), str(source_path))
            except (OSError, UnicodeError, SyntaxError) as error:
                errors.append(f"{source_path.relative_to(self.staging_dir)}: {error}")
        if self.plugin_kind in {"experiment", "device"}:
            manifest_path = self.staging_dir / "plugin.json"
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                plugin_id = manifest.get("id")
                if manifest.get("type") != self.plugin_kind:
                    raise ValueError(f"type must be {self.plugin_kind!r}")
                if (
                    self.plugin_kind == "device"
                    and manifest.get("profile", "standard")
                    not in {"standard", "composite"}
                ):
                    raise ValueError(
                        "profile must be 'standard' or 'composite'"
                    )
                validate_plugin_id(plugin_id)
                source_name, separator, export_name = manifest.get(
                    "entrypoint", "plugin.py:plugin"
                ).partition(":")
                source_path = (self.staging_dir / source_name).resolve()
                if (
                    not separator
                    or not export_name
                    or source_path.parent != self.staging_dir.resolve()
                    or not source_path.is_file()
                ):
                    raise ValueError("invalid or missing entrypoint")
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
                errors.append(f"plugin.json: {error}")
        if errors:
            return "VALIDATION FAILED\n\n" + "\n".join(f"- {error}" for error in errors)
        return (
            "VALIDATION PASSED\n\n"
            f"- {len(python_files)} Python file(s): syntax OK\n"
            "- Plugin manifest: OK"
        )

    def _changed_line_map(self, staged):
        changed = {}
        for relative, after_text in staged.items():
            before_lines = self.original_files.get(relative, "").splitlines()
            after_lines = after_text.splitlines()
            lines = set()
            matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
            for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
                if tag in {"replace", "insert"}:
                    lines.update(range(j1 + 1, j2 + 1))
                elif tag == "delete" and after_lines:
                    lines.add(min(j1 + 1, len(after_lines)))
            if lines:
                changed[relative.as_posix()] = sorted(lines)
        return changed

    def apply_changes(self):
        if self.plugin_dir is None or self.staging_dir is None:
            return
        try:
            if self._read_editable_files(self.plugin_dir) != self.original_files:
                raise RuntimeError(
                    "The plugin changed after Codex started. Reject and run again."
                )
            staged = self._staged_files()
            changed_lines = self._changed_line_map(staged)
            for relative in set(self.original_files) - set(staged):
                target = (self.plugin_dir / relative).resolve()
                target.relative_to(self.plugin_dir)
                target.unlink()
            for relative, contents in staged.items():
                target = (self.plugin_dir / relative).resolve()
                target.relative_to(self.plugin_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(contents, encoding="utf-8")
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.critical(self, "Apply Codex changes", str(error))
            return
        plugin_name = self.plugin_dir.name
        self._stop_worker()
        self._clear_staging()
        self._set_staging_state(False)
        self.status.setText(f"Applied changes to {plugin_name}")
        self._log("APPLY", f"Applied staged changes to {plugin_name}")
        self.changes_applied.emit(str(self.plugin_dir), changed_lines)

    def reject_changes(self):
        self._stop_worker()
        self._clear_staging()
        self._set_staging_state(False)
        self.status.setText(
            f"Changes rejected — Plugin: {self.plugin_dir.name}"
            if self.plugin_dir else "Changes rejected"
        )
        self._log("REJECT", "Discarded staged changes")

    def set_activity(self, message):
        self._log("PLUGIN", message)

    def _clear_staging(self):
        if self.staging_root is not None and self.staging_root.is_dir():
            shutil.rmtree(self.staging_root, ignore_errors=True)
        self.staging_root = None
        self.staging_dir = None
        self.original_files = {}

    def _stop_worker(self):
        worker = self.worker
        if worker is None:
            return
        if worker.isRunning():
            worker.stop()
            worker.wait(5000)
        self.worker = None
        self.pending_request = None
        self.request_active = False

    def shutdown(self):
        self._stop_worker()
        self._clear_staging()
