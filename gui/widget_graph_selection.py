from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QSizePolicy,
)


class GraphSelectionTree(QGroupBox):
    """Compact device/value graph selector with independent multi-selection state."""

    selection_changed = pyqtSignal()

    def __init__(self, plugins, parent=None):
        super().__init__("Graph Selection", parent)
        self.plugins = plugins
        self.states = {
            column.label: False
            for plugin in plugins.values()
            for column in plugin.columns
        }
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 5)
        layout.setSpacing(6)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(QLabel("Device"))
        self.device_combo = QComboBox()
        for device_id, plugin in plugins.items():
            self.device_combo.addItem(plugin.display_name, device_id)
        layout.addWidget(self.device_combo)
        layout.addWidget(QLabel("Value"))
        self.value_combo = QComboBox()
        layout.addWidget(self.value_combo, 1)
        self.show_value = QCheckBox("Show")
        layout.addWidget(self.show_value)
        self.select_all = QCheckBox("Select All")
        layout.addWidget(self.select_all)
        self.device_combo.currentIndexChanged.connect(self.populate_values)
        self.value_combo.currentIndexChanged.connect(self.sync_current_state)
        self.show_value.toggled.connect(self.set_current_state)
        self.select_all.toggled.connect(self.set_all_checked)
        self.populate_values()

    def selected_labels(self):
        return {label for label, checked in self.states.items() if checked}

    def populate_values(self, _index=None):
        device_id = self.device_combo.currentData()
        self.value_combo.blockSignals(True)
        self.value_combo.clear()
        if device_id in self.plugins:
            for column in self.plugins[device_id].columns:
                self.value_combo.addItem(column.label, column.label)
        self.value_combo.blockSignals(False)
        self.sync_current_state()

    def sync_current_state(self, _index=None):
        label = self.value_combo.currentData()
        self.show_value.blockSignals(True)
        self.show_value.setChecked(bool(label and self.states[label]))
        self.show_value.blockSignals(False)

    def set_current_state(self, checked):
        label = self.value_combo.currentData()
        if not label:
            return
        self.states[label] = checked
        self._sync_select_all()
        self.selection_changed.emit()

    def set_all_checked(self, checked):
        for label in self.states:
            self.states[label] = checked
        self.sync_current_state()
        self.selection_changed.emit()

    def _sync_select_all(self):
        self.select_all.blockSignals(True)
        self.select_all.setChecked(bool(self.states) and all(self.states.values()))
        self.select_all.blockSignals(False)
