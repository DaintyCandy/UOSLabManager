import time
from datetime import datetime

import pyqtgraph as pg
from core.data_logger import DataLogger
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from .widget_graph_selection import GraphSelectionTree


class MeasurementPanels:
    COLORS = ("#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b")

    def __init__(self, manager, plugins, log_callback):
        self.manager = manager
        self.plugins = plugins
        self.log = log_callback
        self.get_rheed_profile = lambda: None 
        self.t0 = time.time()
        self.times = []
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
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Data Graphs"))
        controls.addStretch()
        self.split_graph_button = QToolButton()
        self.split_graph_button.setText("◫")
        self.split_graph_button.setToolTip("Split graph view")
        self.split_graph_button.setCheckable(True)
        self.split_graph_button.setFixedSize(36, 30)
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
        selector = GraphSelectionTree(self.plugins)
        selector.setMaximumHeight(80)
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

        # ========================================================
        # [핵심 1] 카메라 패널에서 방금 찍힌 1D 픽셀 배열을 가져옵니다.
        profile = self.get_rheed_profile() 
        
        # [핵심 2] DataLogger에 온도 데이터(row)와 픽셀 데이터(profile)를 "세트"로 넘깁니다!
        # 기존 코드: self.rows.append(row)   <-- 이 줄을 지우고 아래 줄로 바꿉니다.
        self.data_logger.append(row, rheed_profile=profile) 
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
            for curves in self.plot_curves:
                curves[label].setData(self.times, self.series[label])

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
            for curves in self.plot_curves:
                curves[label].setData([], [])
        self.t0 = time.time()
        self.log("Table cleared")
