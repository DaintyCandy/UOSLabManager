import keyword

from PyQt6.QtCore import QRect, QRegularExpression, QSize, Qt
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QSyntaxHighlighter, QTextCharFormat,
    QTextCursor, QTextFormat,
)
from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        self._add_rule(
            r"\b(" + "|".join(keyword.kwlist) + r")\b", "#c586c0", True
        )
        self._add_rule(r"\b(True|False|None)\b", "#569cd6", True)
        self._add_rule(r"\b[0-9]+(?:\.[0-9]+)?\b", "#b5cea8")
        self._add_rule(r"#[^\n]*", "#6a9955")
        self._add_rule(r"'(?:\\.|[^'\\])*'", "#ce9178")
        self._add_rule(r'"(?:\\.|[^"\\])*"', "#ce9178")

    def _add_rule(self, pattern, color, bold=False):
        formatting = QTextCharFormat()
        formatting.setForeground(QColor(color))
        if bold:
            formatting.setFontWeight(QFont.Weight.Bold)
        self.rules.append((QRegularExpression(pattern), formatting))

    def highlightBlock(self, text):
        for expression, formatting in self.rules:
            iterator = expression.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(
                    match.capturedStart(), match.capturedLength(), formatting
                )


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class CodeEditor(QPlainTextEdit):
    INDENT_SIZE = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(
            self.fontMetrics().horizontalAdvance(" ") * self.INDENT_SIZE
        )
        self.setPlaceholderText("Select a plug-in file to edit")
        self.highlighter = PythonHighlighter(self.document())
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._cursor_position_changed)
        self.changed_lines = set()
        self.update_line_number_area_width()

    def line_number_area_width(self):
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _count=0):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        contents = self.contentsRect()
        self.line_number_area.setGeometry(
            QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def paint_line_numbers(self, event):
        painter = QPainter(self.line_number_area)
        painter.fillRect(event.rect(), QColor("#202124"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        current_block = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                color = QColor("#f1f3f4") if block_number == current_block else QColor("#8b949e")
                painter.setPen(color)
                if block_number == current_block:
                    painter.setFont(QFont(self.font().family(), self.font().pointSize(), QFont.Weight.Bold))
                else:
                    painter.setFont(self.font())
                painter.drawText(
                    0, top, self.line_number_area.width() - 7,
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            if block.isValid():
                bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        guide_color = QColor("#6b7280")
        guide_color.setAlpha(85)
        painter.setPen(QPen(guide_color, 1))
        space_width = self.fontMetrics().horizontalAdvance(" ")
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        while block.isValid() and top <= event.rect().bottom():
            height = self.blockBoundingRect(block).height()
            if block.isVisible() and top + height >= event.rect().top():
                text = block.text()
                expanded = text.expandtabs(self.INDENT_SIZE)
                indent = len(expanded) - len(expanded.lstrip(" "))
                for column in range(self.INDENT_SIZE, indent + 1, self.INDENT_SIZE):
                    x = self.contentOffset().x() + column * space_width
                    painter.drawLine(round(x), round(top), round(x), round(top + height))
            block = block.next()
            top += height

    def set_changed_lines(self, lines):
        self.changed_lines = {int(line) for line in lines if int(line) > 0}
        self._refresh_extra_selections()

    def clear_changed_lines(self):
        self.changed_lines.clear()
        self._refresh_extra_selections()

    def _cursor_position_changed(self):
        self.line_number_area.update()
        self._refresh_extra_selections()

    def _refresh_extra_selections(self):
        selections = []
        current = QTextEdit.ExtraSelection()
        current.format.setBackground(QColor(60, 70, 85, 85))
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)

        document = self.document()
        for line_number in sorted(self.changed_lines):
            block = document.findBlockByNumber(line_number - 1)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor(255, 235, 59, 105))
            selection.format.setProperty(
                QTextFormat.Property.FullWidthSelection, True
            )
            selection.cursor = QTextCursor(block)
            selection.cursor.clearSelection()
            selections.append(selection)
        self.setExtraSelections(selections)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText(" " * self.INDENT_SIZE)
            return
        super().keyPressEvent(event)
