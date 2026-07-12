from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QGroupBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout


class GraphSelectionTree(QGroupBox):
    selection_changed = pyqtSignal()

    def __init__(self, plugins, parent=None):
        super().__init__("Graph Selection", parent)
        self.child_items = {}
        layout = QVBoxLayout(self)
        self.select_all = QCheckBox("Select All")
        self.select_all.setChecked(False)
        self.select_all.toggled.connect(self.set_all_checked)
        layout.addWidget(self.select_all)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self.item_changed)
        layout.addWidget(self.tree)

        self.tree.blockSignals(True)
        for device_id, plugin in plugins.items():
            parent_item = QTreeWidgetItem([plugin.display_name])
            parent_item.setData(0, Qt.ItemDataRole.UserRole, device_id)
            parent_item.setFlags(parent_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            parent_item.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(parent_item)
            for column in plugin.columns:
                child = QTreeWidgetItem([column.label])
                child.setData(0, Qt.ItemDataRole.UserRole, column.label)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                parent_item.addChild(child)
                self.child_items[column.label] = child
            parent_item.setExpanded(True)
        self.tree.blockSignals(False)

    def selected_labels(self):
        return {
            label for label, item in self.child_items.items()
            if item.checkState(0) == Qt.CheckState.Checked
        }

    def set_all_checked(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            parent.setCheckState(0, state)
            for child_index in range(parent.childCount()):
                parent.child(child_index).setCheckState(0, state)
        self.tree.blockSignals(False)
        self.selection_changed.emit()

    def item_changed(self, item, _column):
        self.tree.blockSignals(True)
        if item.parent() is None:
            state = item.checkState(0)
            if state != Qt.CheckState.PartiallyChecked:
                for index in range(item.childCount()):
                    item.child(index).setCheckState(0, state)
        else:
            parent = item.parent()
            states = [parent.child(index).checkState(0) for index in range(parent.childCount())]
            if all(state == Qt.CheckState.Checked for state in states):
                parent.setCheckState(0, Qt.CheckState.Checked)
            elif all(state == Qt.CheckState.Unchecked for state in states):
                parent.setCheckState(0, Qt.CheckState.Unchecked)
            else:
                parent.setCheckState(0, Qt.CheckState.PartiallyChecked)
        all_checked = bool(self.child_items) and all(
            child.checkState(0) == Qt.CheckState.Checked for child in self.child_items.values()
        )
        self.select_all.blockSignals(True)
        self.select_all.setChecked(all_checked)
        self.select_all.blockSignals(False)
        self.tree.blockSignals(False)
        self.selection_changed.emit()
