from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QWidget


class BusySpinner(QWidget):
    """Small text-free activity wheel."""

    def __init__(self, parent=None, size=54):
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.translate(self.width() / 2, self.height() / 2)
            radius = min(self.width(), self.height()) * 0.34
            for index in range(12):
                alpha = 45 + index * 17
                pen = QPen(QColor(235, 235, 235, alpha))
                pen.setWidthF(4.0)
                pen.setStyle(Qt.PenStyle.SolidLine)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.save()
                painter.rotate(self._angle + index * 30)
                painter.drawLine(0, int(-radius * 0.62), 0, int(-radius))
                painter.restore()
        finally:
            painter.end()


class BusySpinnerDialog(QDialog):
    """Modal, frameless spinner with no status text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(92, 92)
        container = QWidget()
        container.setObjectName("spinnerContainer")
        container.setStyleSheet(
            "#spinnerContainer { background:rgba(30,30,30,220); border-radius:18px; }"
        )
        inner = QVBoxLayout(container)
        inner.addWidget(BusySpinner(container), alignment=Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(container)
