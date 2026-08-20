import os
import time
from collections import deque
from datetime import datetime, timezone

import pyqtgraph as pg
from core import MeasurementPipeline, storage_dir
from core.data_logger import DataLogger
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from .widget_graph_selection import GraphSelectionTree


_MISSING = object()


class MeasurementPanels:
    COLORS = ("#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b")
    DEFAULT_UPDATE_INTERVAL_MS = 1000
    DEFAULT_BUFFER_ROWS = 10_000
    LOG_BUFFER_LINES = 2000

    def __init__(self, manager, plugins, log_callback):
        self.manager = manager
        self.plugins = plugins
        self.log = log_callback
        self.settings = QSettings("UOSLabManager", "UOSLabManager")
        self.update_interval_ms = max(
            50,
            int(self.settings.value(
                "data/update_interval_ms", self.DEFAULT_UPDATE_INTERVAL_MS
            )),
        )
        self.buffer_rows = max(
            100,
            int(self.settings.value("data/buffer_rows", self.DEFAULT_BUFFER_ROWS)),
        )
        self.times = deque(maxlen=self.buffer_rows)
        self.series = {}
        self.curves = {}
        self.curve_colors = {}
        self.graph_selectors = []
        self.graph_panes = []
        self.plots = []
        self.legends = []
        self.plot_curves = []
        self.column_devices = {}
        self.columns = ["datetime", "elapsed_s"]
        for device_id, plugin in plugins.items():
            for column in plugin.columns:
                self.columns.append(column.label)
                self.column_devices[column.label] = device_id
                self.series[column.label] = deque(maxlen=self.buffer_rows)
        self.measurement_pipeline = MeasurementPipeline(plugins)
        self.provenance_columns = self.measurement_pipeline.provenance_columns
        self.data_logger = DataLogger(
            self.columns + self.provenance_columns + ["sequence_marker"],
            max_rows=self.buffer_rows,
        )
        self.rows = self.data_logger.rows
        self.pending_sequence_markers = []
        self._compat_sample_id = 0
        self._last_alarm_values = {}
        self.recording = False
        self.timer = QTimer()
        self.timer.setInterval(self.update_interval_ms)
        self.timer.timeout.connect(self.update)
        self.graph_widget = self._build_graph_widget()
        self.table_widget = self._build_table_widget()
        self.log_widget = self._build_log_widget()

    def _build_graph_widget(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Data Graphs"))
        controls.addStretch()
        self.split_graph_button = QToolButton()
        self.split_graph_button.setText("◫")
        self.split_graph_button.setToolTip("Split graph view")
        self.split_graph_button.setCheckable(True)
        self.split_graph_button.setFixedSize(32, 26)
        self.split_graph_button.setStyleSheet("font-size:17pt; font-weight:bold;")
        self.split_graph_button.toggled.connect(self.set_split_graph)
        controls.addWidget(self.split_graph_button)
        layout.addLayout(controls)
        pg.setConfigOption("background", "#202124")
        pg.setConfigOption("foreground", "#e8eaed")
        self.graph_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.graph_splitter.setHandleWidth(0)
        self.graph_splitter.setChildrenCollapsible(False)
        self.graph_splitter.addWidget(self._build_plot_pane(1))
        self.graph_splitter.addWidget(self._build_plot_pane(2))
        self.graph_splitter.handle(1).setEnabled(False)
        self.graph_panes[1].setVisible(False)
        layout.addWidget(self.graph_splitter, 1)
        self.graph_selector = self.graph_selectors[0]
        self.plot = self.plots[0]
        self.legend = self.legends[0]
        self.curves = self.plot_curves[0]
        self._update_legends()
        return panel

    def _build_plot_pane(self, number):
        pane = QWidget()
        pane_layout = QVBoxLayout(pane)
        pane_layout.setContentsMargins(0, 0, 0, 0)
        pane_layout.setSpacing(4)
        selector = GraphSelectionTree(self.plugins)
        selector.setFixedHeight(58)
        selector.selection_changed.connect(self.apply_selection)
        pane_layout.addWidget(selector)
        graph_group = QGroupBox(f"Graph {number}")
        graph_layout = QVBoxLayout(graph_group)
        # Keep the axis titles away from the group-box border without changing
        # the spacing between axis titles and tick values.
        graph_layout.setContentsMargins(20, 20, 20, 30)
        plot = pg.PlotWidget()
        plot.setLabel("bottom", "Time", units="s")
        # qdarktheme uses a taller label font than pyqtgraph's automatic axis
        # geometry reserves, so leave space *outside* the axis title.
        plot.getAxis("bottom").setHeight(30)
        legend = plot.addLegend(offset=(-10, 10))
        curves = {}
        for index, label in enumerate(self.columns[2:]):
            color = self.COLORS[index % len(self.COLORS)]
            self.curve_colors[label] = color
            curves[label] = plot.plot([], [], pen=pg.mkPen(color, width=2))
            curves[label].setVisible(False)
        graph_layout.addWidget(plot)
        pane_layout.addWidget(graph_group, 1)
        self.graph_selectors.append(selector)
        self.graph_panes.append(pane)
        self.plots.append(plot)
        self.legends.append(legend)
        self.plot_curves.append(curves)
        return pane

    def set_split_graph(self, enabled):
        minimum_width = 420 if enabled else 0
        for pane in self.graph_panes:
            pane.setMinimumWidth(minimum_width)
        self.graph_panes[1].setVisible(enabled)
        self.split_graph_button.setText("▣" if enabled else "◫")
        self.split_graph_button.setToolTip("Merge graph view" if enabled else "Split graph view")
        if enabled:
            self.graph_splitter.setSizes([1, 1])
        self.apply_selection()

    def _build_table_widget(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Data Table"))
        controls.addWidget(QLabel("Update (ms)"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(50, 60_000)
        self.interval_spin.setSingleStep(50)
        self.interval_spin.setValue(self.update_interval_ms)
        self.interval_spin.setToolTip(
            "Sampling interval for the table, graph, and recording"
        )
        self.interval_spin.valueChanged.connect(self.set_update_interval)
        controls.addWidget(self.interval_spin)
        controls.addWidget(QLabel("Buffer rows"))
        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(100, 1_000_000)
        self.buffer_spin.setSingleStep(1000)
        self.buffer_spin.setValue(self.buffer_rows)
        self.buffer_spin.setToolTip(
            "Maximum rows retained in memory; oldest rows are discarded"
        )
        self.buffer_spin.valueChanged.connect(self.set_buffer_rows)
        controls.addWidget(self.buffer_spin)
        controls.addStretch()
        self.record_button = QPushButton("Start Recording")
        self.record_button.setCheckable(True)
        self.record_button.toggled.connect(self.set_recording)
        save = QPushButton("Save Selected CSV")
        clear = QPushButton("Clear")
        save.clicked.connect(self.save_csv)
        clear.clicked.connect(self.clear)
        controls.addWidget(self.record_button)
        controls.addWidget(save)
        controls.addWidget(clear)
        layout.addLayout(controls)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        layout.addWidget(self.table)
        return panel

    def _build_log_widget(self):
        group = QGroupBox("System Log")
        layout = QVBoxLayout(group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.document().setMaximumBlockCount(self.LOG_BUFFER_LINES)
        self.log_box.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        layout.addWidget(self.log_box)
        return group

    def selected_columns(self):
        selected_labels = set(self.graph_selectors[0].selected_labels())
        if self.split_graph_button.isChecked():
            selected_labels.update(self.graph_selectors[1].selected_labels())
        return ["datetime", "elapsed_s"] + [
            label for label in self.columns[2:]
            if label in selected_labels
        ]

    def apply_selection(self, _checked=None):
        selected = set(self.selected_columns())
        for index, label in enumerate(self.columns[2:], start=2):
            connected = self.manager.get_device(self.column_devices[label]) is not None
            visible = label in selected and connected
            self.table.setColumnHidden(index, not visible)
        for graph_index, curves in enumerate(self.plot_curves):
            graph_selected = self.graph_selectors[graph_index].selected_labels()
            pane_visible = graph_index == 0 or self.split_graph_button.isChecked()
            for label, curve in curves.items():
                connected = self.manager.get_device(self.column_devices[label]) is not None
                curve.setVisible(pane_visible and label in graph_selected and connected)
        self._update_legends()

    def _update_legends(self):
        for graph_index, legend in enumerate(self.legends):
            legend.clear()
            selected = self.graph_selectors[graph_index].selected_labels()
            for label, curve in self.plot_curves[graph_index].items():
                connected = self.manager.get_device(self.column_devices[label]) is not None
                if label in selected and connected:
                    legend.addItem(curve, label)
                    legend.items[-1][1].setText(label, color=self.curve_colors[label])

    def start(self):
        if not self.timer.isActive():
            self.timer.start()

    def set_update_interval(self, interval_ms):
        self.update_interval_ms = max(50, int(interval_ms))
        self.timer.setInterval(self.update_interval_ms)
        self.settings.setValue("data/update_interval_ms", self.update_interval_ms)

    def set_buffer_rows(self, max_rows):
        self.buffer_rows = max(100, int(max_rows))
        self.settings.setValue("data/buffer_rows", self.buffer_rows)
        self.times = deque(self.times, maxlen=self.buffer_rows)
        for label, values in tuple(self.series.items()):
            self.series[label] = deque(values, maxlen=self.buffer_rows)
        self.data_logger.set_max_rows(self.buffer_rows)
        self.rows = self.data_logger.rows
        while self.table.rowCount() > self.buffer_rows:
            self.table.removeRow(0)
        self._refresh_curves()

    def _refresh_curves(self):
        times = list(self.times)
        for label, values in self.series.items():
            samples = list(values)
            for curves in self.plot_curves:
                curves[label].setData(times, samples)

    def set_theme(self, theme):
        dark = theme == "dark"
        foreground = "#e8eaed" if dark else "#202124"
        for plot in self.plots:
            plot.setBackground("#202124" if dark else "#ffffff")
            for axis_name in ("left", "bottom"):
                axis = plot.getAxis(axis_name)
                axis.setPen(foreground)
                axis.setTextPen(foreground)

    def stop_if_empty(self):
        if not self.manager.devices:
            self.timer.stop()

    def sync_columns(self):
        self.apply_selection()

    def set_plugins(self, plugins):
        """Refresh snapshot provenance after a safe plug-in reload."""
        self.plugins = dict(plugins)
        self._last_alarm_values.clear()
        self.measurement_pipeline.plugins = dict(plugins)
        self.provenance_columns = self.measurement_pipeline.provenance_columns
        self.data_logger.columns = (
            self.columns + self.provenance_columns + ["sequence_marker"]
        )

    def _measurement_snapshot(self):
        if hasattr(self.manager, "read_snapshot"):
            return self.manager.read_snapshot()
        # Compatibility for lightweight managers used by tests and plug-ins.
        self._compat_sample_id += 1
        captured_monotonic = time.monotonic()
        sampled_at = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        devices = {
            device_id: {
                "values": values,
                "sample_id": self._compat_sample_id,
                "sampled_at_utc": sampled_at,
                "age_ms": 0.0,
                "fresh": True,
                "response_ms": None,
            }
            for device_id, values in self.manager.read_all().items()
        }
        return {
            "captured_at_utc": sampled_at,
            "captured_monotonic": captured_monotonic,
            "devices": devices,
        }

    def update(self):
        snapshot = self._measurement_snapshot()
        data = {
            device_id: state.get("values", {})
            for device_id, state in snapshot["devices"].items()
        }
        self._check_alarms(data)

        row = self.measurement_pipeline.ingest(
            snapshot, tuple(self.pending_sequence_markers)
        )
        if row is None:
            return
        self.pending_sequence_markers.clear()

        # ========================================================
        # [핵심 1] 카메라 패널에서 방금 찍힌 1D 픽셀 배열을 가져옵니다.
        # [핵심 2] DataLogger에 온도 데이터(row)와 픽셀 데이터(profile)를 "세트"로 넘깁니다!
        # 기존 코드: self.rows.append(row)   <-- 이 줄을 지우고 아래 줄로 바꿉니다.
        if self.recording:
            self.data_logger.append(row)
        # ========================================================

        # (이하 화면의 그래프와 표를 업데이트하는 기존 코드는 동일하게 유지)
        self.times.append(row["elapsed_s"])
        self._append_table_row(row)
        for label in self.columns[2:]:
            value = row.get(label, "")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = float("nan")
            self.series[label].append(numeric)
        self._refresh_curves()

    def _check_alarms(self, data):
        """Report plug-in-declared alarms only when their value changes."""
        configured = set()
        for device_id, plugin in self.plugins.items():
            values = data.get(device_id, {})
            for rule in getattr(plugin, "alarms", ()):
                cache_key = (device_id, rule.key)
                configured.add(cache_key)
                value = values.get(rule.key)
                previous = self._last_alarm_values.get(cache_key, _MISSING)
                if rule.is_active(value) and value != previous:
                    self.log(rule.format_message(plugin.display_name, value))
                self._last_alarm_values[cache_key] = value
        for cache_key in set(self._last_alarm_values) - configured:
            self._last_alarm_values.pop(cache_key, None)

    def _append_table_row(self, row):
        while self.table.rowCount() >= self.buffer_rows:
            self.table.removeRow(0)
        table_row = self.table.rowCount()
        self.table.insertRow(table_row)
        for index, key in enumerate(self.columns):
            value = row.get(key, "")
            text = f"{value:.6g}" if isinstance(value, float) else str(value)
            self.table.setItem(table_row, index, QTableWidgetItem(text))

    def save_csv(self):
        if not self.rows:
            QMessageBox.information(self.table, "Save CSV", "No data to save.")
            return
        settings = QSettings("UOSLabManager", "UOSLabManager")
        default_directory = str(storage_dir("data"))
        output_directory = settings.value("data/output_dir", default_directory)
        os.makedirs(output_directory, exist_ok=True)
        default_path = os.path.join(output_directory, "experiment_data.csv")
        path, _ = QFileDialog.getSaveFileName(self.table, "Save Data", default_path, "CSV Files (*.csv)")
        if path:
            self.data_logger.save_csv(
                path,
                self.selected_columns()
                + self.provenance_columns
                + ["sequence_marker"],
            )
            self.log(f"Saved selected CSV: {path}")

    def add_sequence_marker(self, marker):
        marker = str(marker).strip()
        if marker:
            self.pending_sequence_markers.append(marker)

    def flush_sequence_markers(self):
        if not self.pending_sequence_markers:
            return
        if self.rows:
            marker = " | ".join(self.pending_sequence_markers)
            existing = self.rows[-1].get("sequence_marker", "")
            self.rows[-1]["sequence_marker"] = " | ".join(
                value for value in (existing, marker) if value
            )
        self.pending_sequence_markers.clear()

    def set_recording(self, enabled):
        self.recording = bool(enabled)
        self.record_button.setText("Stop Recording" if enabled else "Start Recording")
        if enabled:
            self.data_logger.clear()
            self.pending_sequence_markers.clear()
            self.log("Data recording started")
        else:
            self.log(f"Data recording stopped ({len(self.rows)} rows captured)")

    def clear(self):
        self.data_logger.clear()
        self.table.setRowCount(0)
        self.times.clear()
        for label in self.series:
            self.series[label].clear()
            for curves in self.plot_curves:
                curves[label].setData([], [])
        self.measurement_pipeline.reset()
        self.log("Table cleared")
