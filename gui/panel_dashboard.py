from datetime import datetime

import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from .widget_graph_selection import GraphSelectionTree


class DashboardPanel(QWidget):
    def __init__(self, manager, plugins, measurement, open_device_callback, emergency_callback):
        super().__init__()
        self.manager = manager
        self.plugins = plugins
        self.measurement = measurement
        self.open_device_callback = open_device_callback
        self.emergency_callback = emergency_callback
        self.device_items = {}
        self.detail_labels = {}
        self.curves = {}
        self.curve_colors = {}
        self._build_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self._build_device_list())
        top.addWidget(self._build_graph())
        for index, factor in enumerate((1, 7)):
            top.setStretchFactor(index, factor)
        layout.addWidget(top, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(self._build_device_details())
        console_group = QGroupBox("Console / Log")
        console_layout = QVBoxLayout(console_group)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(150)
        self.console.setStyleSheet("background:#000; color:#0F0; font-family:monospace;")
        console_layout.addWidget(self.console)
        bottom.addWidget(console_group, 1)
        self.emergency_button = QPushButton("EMERGENCY\nSTOP")
        self.emergency_button.setMinimumSize(190, 150)
        self.emergency_button.setStyleSheet(
            "QPushButton { background:#c62828; color:white; font-size:20pt; font-weight:900; border:4px solid #ff8a80; border-radius:10px; }"
            "QPushButton:hover { background:#e53935; } QPushButton:pressed { background:#8e0000; }"
        )
        self.emergency_button.clicked.connect(self.emergency_callback)
        bottom.addWidget(self.emergency_button)
        layout.addLayout(bottom)
        if self.device_list.count():
            self.device_list.setCurrentRow(0)

    def _build_device_list(self):
        group = QGroupBox("Devices")
        group.setFixedWidth(210)
        layout = QVBoxLayout(group)
        self.device_list = QListWidget()
        for device_id, plugin in self.plugins.items():
            item = QListWidgetItem(plugin.display_name)
            item.setData(Qt.ItemDataRole.UserRole, device_id)
            self.device_list.addItem(item)
            self.device_items[device_id] = item
        self.device_list.currentItemChanged.connect(self.refresh_details)
        self.device_list.itemDoubleClicked.connect(
            lambda item: self.open_device_callback(item.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self.device_list)
        return group

    def _build_graph_selector(self):
        self.graph_selector = GraphSelectionTree(self.plugins)
        self.graph_selector.selection_changed.connect(self.refresh_graph)
        return self.graph_selector

    def _build_graph(self):
        group = QGroupBox("Graph Area")
        layout = QVBoxLayout(group)
        selector = self._build_graph_selector()
        selector.setMaximumHeight(150)
        layout.addWidget(selector)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Time", units="s")
        self.legend = self.plot.addLegend(offset=(-10, 10))
        for index, label in enumerate(self.measurement.columns[2:]):
            color = self.measurement.COLORS[index % len(self.measurement.COLORS)]
            self.curve_colors[label] = color
            self.curves[label] = self.plot.plot([], [], pen=pg.mkPen(color, width=2))
            self.curves[label].setVisible(False)
        layout.addWidget(self.plot)
        self._update_legend()
        return group

    def _build_device_details(self):
        group = QGroupBox("Selected Device")
        group.setFixedWidth(210)
        self.detail_layout = QVBoxLayout(group)
        self.selected_title = QLabel("-")
        self.selected_title.setStyleSheet("font-size:14pt; font-weight:bold;")
        self.detail_layout.addWidget(self.selected_title)
        self.connection_label = QLabel("Disconnected")
        self.detail_layout.addWidget(self.connection_label)
        self.detail_layout.addStretch()
        return group

    def selected_graphs(self):
        return self.graph_selector.selected_labels()

    def refresh(self):
        self.refresh_devices()
        self.refresh_graph()
        self.refresh_details()

    def refresh_graph(self):
        selected = self.selected_graphs()
        for label, curve in self.curves.items():
            connected = self.manager.get_device(self.measurement.column_devices[label]) is not None
            curve.setVisible(label in selected and connected)
            curve.setData(self.measurement.times, self.measurement.series[label])
        self._update_legend()

    def _update_legend(self):
        self.legend.clear()
        selected = self.selected_graphs()
        for label, curve in self.curves.items():
            if label in selected:
                self.legend.addItem(curve, label)
                self.legend.items[-1][1].setText(label, color=self.curve_colors[label])

    def refresh_devices(self):
        for device_id, item in self.device_items.items():
            connected = self.manager.get_device(device_id) is not None
            item.setText(f"{'●' if connected else '○'} {self.plugins[device_id].display_name}")
            item.setForeground(QBrush(QColor("#2ecc71" if connected else "#808080")))

    def refresh_details(self, *_):
        item = self.device_list.currentItem()
        if item is None:
            return
        device_id = item.data(Qt.ItemDataRole.UserRole)
        plugin = self.plugins[device_id]
        self.selected_title.setText(plugin.display_name)
        connected = self.manager.get_device(device_id) is not None
        self.connection_label.setText("Connected" if connected else "Disconnected")
        self.connection_label.setStyleSheet(f"color:{'#2ecc71' if connected else '#e74c3c'}; font-weight:bold;")
        for label in self.detail_labels.values():
            label.deleteLater()
        self.detail_labels.clear()
        latest = self.measurement.rows[-1] if self.measurement.rows else {}
        insert_at = self.detail_layout.count() - 1
        for column in plugin.columns:
            value = latest.get(column.label, "-")
            text = f"{column.label}: {value:.6g}" if isinstance(value, float) else f"{column.label}: {value}"
            label = QLabel(text)
            label.setWordWrap(True)
            self.detail_layout.insertWidget(insert_at, label)
            insert_at += 1
            self.detail_labels[column.label] = label

    def append_log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.console.append(f"[{stamp}] {message}")

    def set_theme(self, theme):
        dark = theme == "dark"
        self.plot.setBackground("#202124" if dark else "#ffffff")
        foreground = "#e8eaed" if dark else "#202124"
        for axis_name in ("left", "bottom"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(foreground)
            axis.setTextPen(foreground)
