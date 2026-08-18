from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.widget_busy_spinner import run_busy_task


class ExperimentPanel(QWidget):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        layout = QVBoxLayout(self)
        self.status = QLabel('Thermo')
        layout.addWidget(self.status)
        layout.addStretch()

    def run_background(self, action, success, failure):
        """Run blocking work with the shared text-free loader."""
        return run_busy_task(
            self, action, success, failure, key="plugin_task"
        )

    def execute_sequence_command(self, command, value):
        if command != "set_value":
            raise ValueError(f"Unsupported command: {command}")
        self.status.setText(f"Value: {value}")
        return True  # False means Sequence should wait and poll

    def is_sequence_command_complete(self, command, value):
        return True

    def cancel_sequence_command(self):
        pass

    def shutdown(self):
        pass
