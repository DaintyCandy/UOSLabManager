from contextlib import contextmanager
import time

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
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
    """Window-modal loading indicator shared by plug-in operations."""

    SHOW_DELAY_MS = 200
    MINIMUM_VISIBLE_MS = 320

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(92, 92)
        self._shown_at = None
        self._finish_pending = False
        self._finish_callbacks = []
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_delayed)
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

    def show_after(self, delay_ms=None):
        """Show only when the operation is still running after the delay."""
        delay = self.SHOW_DELAY_MS if delay_ms is None else max(0, int(delay_ms))
        if delay:
            self._show_timer.start(delay)
        else:
            self._show_delayed()

    def _show_delayed(self):
        if not self._finish_pending:
            self.show()
            self.raise_()

    def showEvent(self, event):
        self._shown_at = time.monotonic()
        self._finish_pending = False
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            center = parent.window().frameGeometry().center()
            frame = self.frameGeometry()
            frame.moveCenter(center)
            self.move(frame.topLeft())

    def finish(self, callback=None, minimum_visible_ms=None):
        """Close after enough event-loop time for the animation to be visible."""
        if callback is not None:
            self._finish_callbacks.append(callback)
        if self._finish_pending:
            return
        self._finish_pending = True
        self._show_timer.stop()
        if not self.isVisible():
            self._finish_now()
            return
        minimum = (
            self.MINIMUM_VISIBLE_MS
            if minimum_visible_ms is None
            else max(0, int(minimum_visible_ms))
        )
        elapsed_ms = (
            minimum if self._shown_at is None
            else int((time.monotonic() - self._shown_at) * 1000)
        )
        remaining = max(0, minimum - elapsed_ms)
        if remaining:
            QTimer.singleShot(remaining, self._finish_now)
        else:
            self._finish_now()

    def _finish_now(self):
        callbacks = tuple(self._finish_callbacks)
        self._finish_callbacks.clear()
        super().close()
        try:
            for callback in callbacks:
                callback()
        finally:
            self.deleteLater()


class _TaskSignals(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(object)
    finished = pyqtSignal()


class _TaskRunnable(QRunnable):
    def __init__(self, action, signals):
        super().__init__()
        self.action = action
        self.signals = signals

    def run(self):
        try:
            self.signals.completed.emit(self.action())
        except Exception as error:
            self.signals.failed.emit(error)
        finally:
            self.signals.finished.emit()


class BusyTaskHandle(QObject):
    """Own a thread-pool task and its loading dialog until completion."""

    def __init__(self, parent, action, success, failure, key):
        super().__init__(parent)
        self.owner = parent
        self.success = success
        self.failure = failure
        self.key = key
        self.dialog = BusySpinnerDialog(parent)
        self.signals = _TaskSignals()
        self.runnable = _TaskRunnable(action, self.signals)
        self._result = None
        self._error = None
        self.signals.completed.connect(self._completed)
        self.signals.failed.connect(self._failed)
        self.signals.finished.connect(self._finished)

    def start(self):
        self.dialog.show_after()
        QThreadPool.globalInstance().start(self.runnable)

    def _completed(self, result):
        self._result = result

    def _failed(self, error):
        self._error = error

    def _finished(self):
        self.dialog.finish(self._deliver_result)

    def _deliver_result(self):
        try:
            if self._error is not None:
                if self.failure is not None:
                    self.failure(self._error)
            elif self.success is not None:
                try:
                    self.success(self._result)
                except Exception as error:
                    if self.failure is not None:
                        self.failure(error)
        finally:
            handles = getattr(self.owner, "_busy_task_handles", None)
            if handles is not None:
                handles.discard(self)
            self.deleteLater()


def run_busy_task(parent, action, success=None, failure=None, *, key="default"):
    """Run a non-UI callable without blocking Qt's event loop."""
    handles = getattr(parent, "_busy_task_handles", None)
    if handles is None:
        handles = set()
        parent._busy_task_handles = handles
    if any(handle.key == key for handle in handles):
        return None
    handle = BusyTaskHandle(
        parent, action, success, failure, key
    )
    handles.add(handle)
    handle.start()
    return handle


@contextmanager
def visible_busy_dialog(parent):
    """Show a loading surface around UI-thread-only widget construction."""
    dialog = BusySpinnerDialog(parent)
    dialog.show_after()
    try:
        yield dialog
    except Exception:
        dialog.finish(minimum_visible_ms=0)
        raise
    finally:
        if not dialog._finish_pending:
            dialog.finish()
