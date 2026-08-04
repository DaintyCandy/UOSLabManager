from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QGroupBox, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)


class DashboardPanel(QWidget):
    """Persistent device and experiment plug-in navigation sidebar."""

    def __init__(self, manager, device_plugins, experiment_plugins,
                 open_device_callback, open_experiment_callback):
        super().__init__()
        self.manager = manager
        self.plugins = device_plugins
        self.experiment_plugins = experiment_plugins
        self.open_device_callback = open_device_callback
        self.open_experiment_callback = open_experiment_callback
        self.device_items = {}
        self.experiment_items = {}
        self.active_experiment_id = None
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
        layout.addWidget(self._build_experiment_list(), 2)
        if self.device_list.count():
            self.device_list.setCurrentRow(0)
        if self.experiment_list.count():
            self.experiment_list.setCurrentRow(0)

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
        self.device_list.itemDoubleClicked.connect(
            lambda item: self.open_device_callback(item.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self.device_list)
        return group

    def _build_experiment_list(self):
        group = QGroupBox("Experiments")
        layout = QVBoxLayout(group)
        self.experiment_list = QListWidget()
        self.experiment_list.setStyleSheet(
            "QListWidget { font-size: 12pt; font-weight: 600; }"
            "QListWidget::item { padding: 8px 6px; }"
        )
        self.experiment_list.setToolTip("Double-click an experiment to load it into Sequence")
        for experiment_id, plugin in self.experiment_plugins.items():
            item = QListWidgetItem(f"○ {plugin.display_name}")
            item.setData(Qt.ItemDataRole.UserRole, experiment_id)
            item.setToolTip(plugin.description)
            self.experiment_list.addItem(item)
            self.experiment_items[experiment_id] = item
        self.experiment_list.itemActivated.connect(
            lambda item: self.open_experiment_callback(
                item.data(Qt.ItemDataRole.UserRole)
            )
        )
        layout.addWidget(self.experiment_list)
        return group

    def refresh(self):
        self.refresh_devices()

    def refresh_devices(self):
        for device_id, item in self.device_items.items():
            connected = self.manager.get_device(device_id) is not None
            marker = "●" if connected else "○"
            item.setText(f"{marker} {self.plugins[device_id].display_name}")
            item.setForeground(QBrush(QColor("#2ecc71" if connected else "#808080")))

    def set_active_experiment(self, experiment_id):
        self.active_experiment_id = experiment_id
        for item_id, item in self.experiment_items.items():
            active = item_id == experiment_id
            marker = "●" if active else "○"
            item.setText(f"{marker} {self.experiment_plugins[item_id].display_name}")
            item.setForeground(QBrush(QColor("#2ecc71" if active else "#808080")))

    def append_log(self, _message):
        # Logs remain available in the persistent Main measurement log.
        pass

    def set_theme(self, _theme):
        pass
