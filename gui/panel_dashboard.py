from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QGroupBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)


class DashboardPanel(QWidget):
    """Persistent device navigation and selected-device status sidebar."""

    def __init__(self, manager, plugins, measurement, open_device_callback, emergency_callback=None):
        super().__init__()
        self.manager = manager
        self.plugins = plugins
        self.measurement = measurement
        self.open_device_callback = open_device_callback
        self.device_items = {}
        self.detail_labels = {}
        self.setMinimumWidth(220)
        self._build_ui()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(1000)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._build_device_list(), 3)
        layout.addWidget(self._build_device_details(), 2)
        if self.device_list.count():
            self.device_list.setCurrentRow(0)

    def _build_device_list(self):
        group = QGroupBox("Devices")
        layout = QVBoxLayout(group)
        self.device_list = QListWidget()
        self.device_list.setStyleSheet(
            "QListWidget { font-size: 13pt; font-weight: 600; }"
            "QListWidget::item { padding: 8px 6px; }"
        )
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

    def _build_device_details(self):
        group = QGroupBox("Selected Device")
        self.detail_layout = QVBoxLayout(group)
        self.selected_title = QLabel("-")
        self.selected_title.setStyleSheet("font-size:14pt; font-weight:bold;")
        self.detail_layout.addWidget(self.selected_title)
        self.connection_label = QLabel("Disconnected")
        self.detail_layout.addWidget(self.connection_label)
        self.response_label = QLabel("Response: -")
        self.detail_layout.addWidget(self.response_label)
        self.detail_layout.addStretch()
        return group

    def refresh(self):
        self.refresh_devices()
        self.refresh_details()

    def refresh_devices(self):
        for device_id, item in self.device_items.items():
            connected = self.manager.get_device(device_id) is not None
            marker = "●" if connected else "○"
            item.setText(f"{marker} {self.plugins[device_id].display_name}")
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
        self.connection_label.setStyleSheet(
            f"color:{'#2ecc71' if connected else '#e74c3c'}; font-weight:bold;"
        )
        metrics = self.manager.get_metrics(device_id)
        response = metrics["response_ms"]
        self.response_label.setText("Response: -" if response is None else f"Response: {response:.1f} ms")
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

    def append_log(self, _message):
        # Logs remain available in the persistent Main measurement log.
        pass

    def set_theme(self, _theme):
        pass
