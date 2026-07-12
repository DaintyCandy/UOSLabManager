import time
from datetime import datetime

import pyqtgraph as pg
from core.data_logger import DataLogger
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .widget_graph_selection import GraphSelectionTree


class MeasurementPanels:
    COLORS = ("#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b")

    def __init__(self, manager, plugins, log_callback):
        self.manager = manager
        self.plugins = plugins
        self.log = log_callback
        self.t0 = time.time()
        self.times = []
        self.series = {}
        self.curves = {}
        self.curve_colors = {}
        self.column_devices = {}
        self.columns = ["datetime", "elapsed_s"]
        for device_id, plugin in plugins.items():
            for column in plugin.columns:
                self.columns.append(column.label)
                self.column_devices[column.label] = device_id
                self.series[column.label] = []
        self.data_logger = DataLogger(self.columns)
        self.rows = self.data_logger.rows
        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update)
        self.graph_widget = self._build_graph_widget()
        self.table_widget = self._build_table_widget()
        self.log_widget = self._build_log_widget()

    def _build_graph_widget(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.graph_selector = GraphSelectionTree(self.plugins)
        self.graph_selector.setMaximumHeight(180)
        self.graph_selector.selection_changed.connect(self.apply_selection)
        layout.addWidget(self.graph_selector)

        pg.setConfigOption("background", "#202124")
        pg.setConfigOption("foreground", "#e8eaed")
        graph_group = QGroupBox("Graph Area")
        graph_layout = QVBoxLayout(graph_group)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Time", units="s")
        self.legend = self.plot.addLegend(offset=(-10, 10))
        for index, label in enumerate(self.columns[2:]):
            color = self.COLORS[index % len(self.COLORS)]
            self.curve_colors[label] = color
            self.curves[label] = self.plot.plot(
                [], [], pen=pg.mkPen(color, width=2)
            )
            self.curves[label].setVisible(False)
        graph_layout.addWidget(self.plot)
        layout.addWidget(graph_group, 1)
        self._update_legend()
        return panel

    def _build_table_widget(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Data Table"))
        save = QPushButton("Save Selected CSV")
        clear = QPushButton("Clear")
        save.clicked.connect(self.save_csv)
        clear.clicked.connect(self.clear)
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
        self.log_box.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        layout.addWidget(self.log_box)
        return group

    def selected_columns(self):
        return ["datetime", "elapsed_s"] + [
            label for label in self.columns[2:]
            if label in self.graph_selector.selected_labels()
        ]

    def apply_selection(self, _checked=None):
        selected = set(self.selected_columns())
        for index, label in enumerate(self.columns[2:], start=2):
            connected = self.manager.get_device(self.column_devices[label]) is not None
            visible = label in selected and connected
            self.table.setColumnHidden(index, not visible)
            self.curves[label].setVisible(visible)
        self._update_legend()

    def _update_legend(self):
        self.legend.clear()
        selected = set(self.selected_columns())
        for label, curve in self.curves.items():
            if label in selected:
                self.legend.addItem(curve, label)
                self.legend.items[-1][1].setText(label, color=self.curve_colors[label])

    def start(self):
        if not self.timer.isActive():
            self.timer.start()

    def set_theme(self, theme):
        dark = theme == "dark"
        self.plot.setBackground("#202124" if dark else "#ffffff")
        foreground = "#e8eaed" if dark else "#202124"
        for axis_name in ("left", "bottom"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(foreground)
            axis.setTextPen(foreground)

    def stop_if_empty(self):
        if not self.manager.devices:
            self.timer.stop()

    def sync_columns(self):
        self.apply_selection()

    def update(self):
        data = self.manager.read_all()
        alarm = data.get("ZUP", {}).get("alarm", "AL00000")
        if alarm and alarm != "AL00000":
            self.log(f"ZUP ALARM DETECTED: {alarm}")
        row = {"datetime": datetime.now().isoformat(timespec="seconds"), "elapsed_s": time.time() - self.t0}
        for device_id, plugin in self.plugins.items():
            values = data.get(device_id, {})
            for column in plugin.columns:
                row[column.label] = values.get(column.key, "")
        self.rows.append(row)
        self.times.append(row["elapsed_s"])
        self._append_table_row(row)
        for label in self.columns[2:]:
            value = row.get(label, "")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                numeric = float("nan")
            self.series[label].append(numeric)
            self.curves[label].setData(self.times, self.series[label])

    def _append_table_row(self, row):
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
        path, _ = QFileDialog.getSaveFileName(self.table, "Save Data", "experiment_data.csv", "CSV Files (*.csv)")
        if path:
            self.data_logger.save_csv(path, self.selected_columns())
            self.log(f"Saved selected CSV: {path}")

    def clear(self):
        self.data_logger.clear()
        self.table.setRowCount(0)
        self.times.clear()
        for label in self.series:
            self.series[label].clear()
            self.curves[label].setData([], [])
        self.t0 = time.time()
        self.log("Table cleared")
