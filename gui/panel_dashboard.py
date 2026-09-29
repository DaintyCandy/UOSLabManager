from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QGroupBox, QListView, QListWidget, QListWidgetItem,
    QSizePolicy, QVBoxLayout, QWidget,
)


class AdaptivePluginList(QListWidget):
    """Vertical sidebar items or wrapping horizontal top-navigation tiles."""

    def __init__(self):
        super().__init__()
        self.layout_mode = "compact"
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWordWrap(False)
        self.setSpacing(4)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet(
            "QListWidget { font-size: 11pt; font-weight: 600; }"
            "QListWidget::item { padding: 6px 10px; }"
        )
        self.setFixedHeight(48)
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.resize_to_contents)

    def set_layout_mode(self, mode):
        self.layout_mode = mode
        compact = mode == "compact"
        self.setViewMode(QListView.ViewMode.IconMode if compact else QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.LeftToRight if compact else QListView.Flow.TopToBottom)
        self.setWrapping(compact)
        self.setMinimumHeight(48 if compact else 0)
        self.setMaximumHeight(100 if compact else 16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed if compact
                           else QSizePolicy.Policy.Expanding)
        self.layout_timer.start(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "layout_timer"):
            self.layout_timer.start(0)

    def showEvent(self, event):
        super().showEvent(event)
        self.layout_timer.start(0)

    def resize_to_contents(self):
        self.ensurePolished()
        available = max(1, self.viewport().width() - 2 * self.spacing())
        metrics = self.fontMetrics()
        items = [self.item(i) for i in range(self.count())]
        for item in items:
            size = QSize(min(available, metrics.horizontalAdvance(item.text()) + 32), 40)
            if item.sizeHint() != size:
                item.setSizeHint(size)
        self.doItemsLayout()
        if self.layout_mode != "compact":
            return
        bottom = max((self.visualItemRect(item).bottom() + 1 for item in items), default=40)
        height = bottom + self.verticalScrollBar().value() + 2 * self.frameWidth() + self.spacing()
        height = min(100, max(48, height))
        if self.height() != height:
            self.setFixedHeight(height)


class DashboardPanel(QWidget):
    """Side navigation in wide mode and top navigation in compact mode."""

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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
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
        self.device_list = AdaptivePluginList()
        for device_id, plugin in self.plugins.items():
            item = QListWidgetItem(plugin.display_name)
            item.setData(Qt.ItemDataRole.UserRole, device_id)
            self.device_list.addItem(item)
            self.device_items[device_id] = item
        self.device_list.itemActivated.connect(
            lambda item: self.open_device_callback(item.data(Qt.ItemDataRole.UserRole))
        )
        layout.addWidget(self.device_list)
        return group

    def _build_experiment_list(self):
        group = QGroupBox("Experiments")
        layout = QVBoxLayout(group)
        self.experiment_list = AdaptivePluginList()
        self.experiment_list.setToolTip("Double-click or press Enter to open an experiment")
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

    def set_experiment_plugins(self, experiment_plugins):
        self.experiment_plugins = experiment_plugins
        self.experiment_items.clear()
        self.experiment_list.clear()
        for experiment_id, plugin in self.experiment_plugins.items():
            item = QListWidgetItem(plugin.display_name)
            item.setData(Qt.ItemDataRole.UserRole, experiment_id)
            item.setToolTip(plugin.description)
            self.experiment_list.addItem(item)
            self.experiment_items[experiment_id] = item
        self.set_active_experiment(self.active_experiment_id)
        self.experiment_list.layout_timer.start(0)

    def set_device_plugins(self, device_plugins):
        self.plugins = device_plugins
        self.device_items.clear()
        self.device_list.clear()
        for device_id, plugin in self.plugins.items():
            item = QListWidgetItem(plugin.display_name)
            item.setData(Qt.ItemDataRole.UserRole, device_id)
            self.device_list.addItem(item)
            self.device_items[device_id] = item
        self.refresh_devices()
        self.device_list.layout_timer.start(0)

    def refresh(self):
        self.refresh_devices()

    def refresh_devices(self):
        for device_id, item in self.device_items.items():
            connected = self.manager.get_device(device_id) is not None
            metrics = self.manager.get_metrics(device_id)
            marker = "●" if connected else "○"
            item.setText(f"{marker} {self.plugins[device_id].display_name}")
            item.setForeground(QBrush(QColor("#2ecc71" if connected else "#808080")))
            worker_name = metrics.get("worker_name")
            if worker_name:
                state = "running" if metrics.get("worker_alive") else "stopped"
                item.setToolTip(f"Thread: {worker_name} ({state})")
            else:
                item.setToolTip("No device worker")

    def set_active_experiment(self, experiment_id):
        if experiment_id not in self.experiment_plugins:
            experiment_id = None
        self.active_experiment_id = experiment_id
        for item_id, item in self.experiment_items.items():
            active = item_id == experiment_id
            marker = "●" if active else "○"
            item.setText(f"{marker} {self.experiment_plugins[item_id].display_name}")
            item.setForeground(QBrush(QColor("#2ecc71" if active else "#808080")))

    def append_log(self, _message):
        # Logs remain available in the persistent Main measurement log.
        pass

    def set_layout_mode(self, mode):
        compact = mode == "compact"
        self.setMinimumWidth(0 if compact else 180)
        self.setMaximumWidth(16777215 if compact else 240)
        self.setMaximumHeight(280 if compact else 16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Maximum if compact else QSizePolicy.Policy.Expanding)
        for plugin_list in (self.device_list, self.experiment_list):
            plugin_list.set_layout_mode(mode)

    def set_theme(self, _theme):
        for plugin_list in (self.device_list, self.experiment_list):
            plugin_list.layout_timer.start(0)
