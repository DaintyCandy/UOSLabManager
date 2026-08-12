from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ExperimentPanel(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager

        self._build_ui()
        self._set_value(self.setpoint.value())

    def _build_ui(self):
        self.setStyleSheet("""
            QFrame#card { background: #ffffff; border: 1px solid #dfe5ec; border-radius: 10px; }
            QLabel#title { font-size: 20px; font-weight: 700; color: #1d2939; }
            QLabel#subtitle { color: #667085; }
            QLabel#temperature { font-size: 42px; font-weight: 700; color: #155eef; }
            QLabel#status { color: #027a48; font-weight: 600; }
            QPushButton { background: #155eef; color: white; border: 0; border-radius: 6px; padding: 8px 16px; font-weight: 600; }
            QPushButton:hover { background: #004eeb; }
            QDoubleSpinBox { padding: 5px; min-height: 26px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Thermo Control")
        title.setObjectName("title")
        subtitle = QLabel("온도 설정값을 확인하고 시퀀스 제어에 사용합니다.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        card_layout.setSpacing(8)

        card_layout.addWidget(QLabel("현재 설정 온도"))
        self.temperature = QLabel()
        self.temperature.setObjectName("temperature")
        self.temperature.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.temperature)

        self.status = QLabel("● Ready")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.status)
        layout.addWidget(card)

        controls = QFrame()
        controls.setObjectName("card")
        grid = QGridLayout(controls)
        grid.setContentsMargins(20, 16, 20, 16)
        grid.setHorizontalSpacing(12)
        grid.addWidget(QLabel("목표 온도"), 0, 0)

        self.setpoint = QDoubleSpinBox()
        self.setpoint.setRange(0.0, 100.0)
        self.setpoint.setDecimals(2)
        self.setpoint.setSuffix(" °C")
        self.setpoint.setValue(0.0)
        grid.addWidget(self.setpoint, 0, 1)

        apply_button = QPushButton("적용")
        apply_button.clicked.connect(self._apply_setpoint)
        grid.addWidget(apply_button, 0, 2)
        layout.addWidget(controls)

        note = QLabel("허용 범위: 0.00–100.00 °C")
        note.setObjectName("subtitle")
        layout.addWidget(note)
        layout.addStretch()

    def _set_value(self, value):
        self.temperature.setText(f"{float(value):.2f} °C")
        self.status.setText("● Ready")

    def _apply_setpoint(self):
        self._set_value(self.setpoint.value())

    def execute_sequence_command(self, command, value):
        if command != "set_value":
            raise ValueError(f"Unsupported command: {command}")
        self.setpoint.setValue(float(value))
        self._set_value(value)
        return True  # False means Sequence should wait and poll

    def is_sequence_command_complete(self, command, value):
        return True

    def cancel_sequence_command(self):
        self.status.setText("● Ready")

    def shutdown(self):
        # This panel owns no timers, threads, or hardware resources.
        pass
