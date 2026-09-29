"""Opt-in layout adaptation; never recreate widgets or touch device services."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout, QGridLayout, QLayout, QSizePolicy, QSpacerItem, QSplitter, QWidget,
)


def validate_layout_mode(mode):
    if mode not in ("wide", "compact"):
        raise ValueError(f"Unknown layout mode: {mode!r}")


class AdaptiveRowLayout(QGridLayout):
    """A horizontal row in wide mode, a small grid in compact mode."""

    def __init__(self, parent=None, *, compact_columns=2):
        super().__init__(parent)
        self.compact_columns = compact_columns
        if compact_columns < 1:
            raise ValueError("compact_columns must be positive")
        self._entries = []
        self._compact_positions = {}
        self._layout_mode = "wide"

    def addWidget(self, widget, stretch=0, alignment=Qt.AlignmentFlag(0)):
        column = len(self._entries)
        super().addWidget(widget, 0, column, 1, 1, alignment)
        self.setColumnStretch(column, stretch)
        self._entries.append((widget, stretch, alignment))

    def addStretch(self, stretch=0):
        column = len(self._entries)
        item = QSpacerItem(
            0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum,
        )
        super().addItem(item, 0, column)
        self.setColumnStretch(column, stretch or 1)
        self._entries.append((item, stretch or 1, Qt.AlignmentFlag(0)))

    def set_compact_position(self, widget, row, column, row_span=1, column_span=1):
        """Keep headings and label/input pairs together when a row wraps."""
        self._compact_positions[widget] = (row, column, row_span, column_span)

    def set_layout_mode(self, mode):
        validate_layout_mode(mode)
        if mode == self._layout_mode:
            return
        while self.count():
            self.takeAt(0)
        for column in range(len(self._entries)):
            self.setColumnStretch(column, 0)
        compact_index = 0
        for wide_column, (target, stretch, alignment) in enumerate(self._entries):
            spacer = isinstance(target, QSpacerItem)
            if mode == "compact":
                if spacer:
                    continue
                row, column = divmod(compact_index, self.compact_columns)
                compact_index += 1
                position = self._compact_positions.get(target, (row, column, 1, 1))
                super().addWidget(target, *position, alignment)
                for column in range(position[1], position[1] + position[3]):
                    self.setColumnStretch(column, 1)
            else:
                if spacer:
                    super().addItem(target, 0, wide_column)
                else:
                    super().addWidget(target, 0, wide_column, 1, 1, alignment)
                self.setColumnStretch(wide_column, stretch)
        self._layout_mode = mode
        self.invalidate()


class AdaptiveGridLayout(QGridLayout):
    """Preserve a dashboard grid in wide mode, stack its sections in compact."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wide_items = None
        self._layout_mode = "wide"

    def set_layout_mode(self, mode):
        validate_layout_mode(mode)
        if self._wide_items is None:
            self._wide_items = []
            for index in range(self.count()):
                item = self.itemAt(index)
                if item.widget() is not None:
                    target, kind = item.widget(), "widget"
                elif item.layout() is not None:
                    target, kind = item.layout(), "layout"
                else:
                    target, kind = item.spacerItem(), "spacer"
                # Qt deletes QWidgetItem on removeWidget(). Cache the QWidget,
                # not that wrapper, so a plugin can also reorder its sections.
                self._wide_items.append((
                    target, kind, self.getItemPosition(index), item.alignment(),
                ))
            self._wide_rows = [self.rowStretch(i) for i in range(self.rowCount())]
            self._wide_columns = [
                self.columnStretch(i) for i in range(self.columnCount())
            ]
        if mode == self._layout_mode:
            return
        while self.count():
            self.takeAt(0)
        for row in range(self.rowCount()):
            self.setRowStretch(row, 0)
        for column in range(self.columnCount()):
            self.setColumnStretch(column, 0)
        for index, (target, kind, position, alignment) in enumerate(self._wide_items):
            position = (index, 0, 1, 1) if mode == "compact" else position
            if kind == "widget":
                super().addWidget(target, *position, alignment)
            elif kind == "layout":
                super().addLayout(target, *position, alignment)
            else:
                super().addItem(target, *position, alignment)
        if mode == "wide":
            for row, stretch in enumerate(self._wide_rows):
                self.setRowStretch(row, stretch)
            for column, stretch in enumerate(self._wide_columns):
                self.setColumnStretch(column, stretch)
        else:
            self.setColumnStretch(0, 1)
        self._layout_mode = mode
        self.invalidate()


class AdaptiveSplitter(QSplitter):
    """An independently sized horizontal/vertical split without state resets."""

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._layout_mode = "compact" if orientation == Qt.Orientation.Vertical else "wide"
        self._mode_sizes = {}

    def restoreState(self, state):
        restored = super().restoreState(state)
        if restored:
            self._layout_mode = (
                "compact" if self.orientation() == Qt.Orientation.Vertical else "wide"
            )
        return restored

    def mode_sizes(self):
        return {**self._mode_sizes, self._layout_mode: self.sizes()}

    def restore_mode_sizes(self, mode, sizes):
        validate_layout_mode(mode)
        try:
            sizes = [int(value) for value in sizes]
        except (TypeError, ValueError):
            return
        if len(sizes) != self.count() or any(value < 0 for value in sizes) or not any(sizes):
            return
        self._mode_sizes[mode] = sizes
        if mode == self._layout_mode:
            self.setSizes(sizes)

    def set_layout_mode(self, mode):
        validate_layout_mode(mode)
        if mode == self._layout_mode:
            return
        self._mode_sizes[self._layout_mode] = self.sizes()
        self.setOrientation(
            Qt.Orientation.Vertical if mode == "compact"
            else Qt.Orientation.Horizontal
        )
        self._layout_mode = mode
        sizes = self._mode_sizes.get(mode)
        if sizes is None:
            extent = self.height() if mode == "compact" else self.width()
            sizes = [max(1, extent // max(1, self.count()))] * self.count()
        self.setSizes(sizes)


def apply_panel_layout(panel, mode):
    """Apply only layouts explicitly opted in by a built-in panel."""
    validate_layout_mode(mode)
    for kind in (AdaptiveRowLayout, AdaptiveGridLayout, AdaptiveSplitter):
        for child in panel.findChildren(kind):
            child.set_layout_mode(mode)
    for form in panel.findChildren(QFormLayout):
        if not hasattr(form, "_wide_wrap_policy"):
            form._wide_wrap_policy = form.rowWrapPolicy()
        form.setRowWrapPolicy(
            QFormLayout.RowWrapPolicy.WrapLongRows
            if mode == "compact" else form._wide_wrap_policy
        )
    # Nested tabs/box layouts may have cached a wide size hint while their
    # child rows were still being changed. Invalidate bottom-up once complete.
    for layout in reversed(panel.findChildren(QLayout)):
        layout.invalidate()
    for widget in reversed(panel.findChildren(QWidget)):
        widget.updateGeometry()
    panel.updateGeometry()


class AdaptivePanelMixin:
    """Optional host contract shared by the built-in QWidget plug-ins."""

    def set_layout_mode(self, mode):
        apply_panel_layout(self, mode)
        self.layout_mode = mode
