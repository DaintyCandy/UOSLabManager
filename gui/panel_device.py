from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from .widget_busy_spinner import run_busy_task


class DeviceSettingsPanel(QWidget):
    """Basic connection panel used when a device has no advanced UI."""

    def __init__(self, manager, plugin, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.plugin = plugin
        self.main_window = parent
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Log"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(120)
        self.log_box.setStyleSheet("font-family:monospace;")
        layout.addWidget(self.log_box)
        group = QGroupBox(f"{plugin.display_name} Settings")
        grid = QGridLayout(group)
        grid.addWidget(QLabel(plugin.connection_label), 0, 0)
        self.connection_input = QLineEdit(plugin.default_connection)
        grid.addWidget(self.connection_input, 0, 1)
        connect = QPushButton("Connect")
        disconnect = QPushButton("Disconnect")
        connect.clicked.connect(self.connect_device)
        disconnect.clicked.connect(self.disconnect_device)
        grid.addWidget(connect, 1, 0)
        grid.addWidget(disconnect, 1, 1)
        self.status = QLabel()
        grid.addWidget(self.status, 2, 0, 1, 2)
        layout.addWidget(group)
        layout.addStretch()
        self.sync_connection_status()

    def connect_device(self):
        connection = self.connection_input.text().strip()
        if self.manager.get_device(self.plugin.device_id) is None:
            def connect():
                self.manager.add_device(
                    self.plugin.device_id,
                    lambda: self.plugin.connect(connection),
                )

            def connected(_result):
                self.main_window.log(self.plugin.format_connected(connection))
                self.log_box.append(self.plugin.format_connected(connection))
                self._notify()

            def failed(error):
                QMessageBox.critical(self, f"{self.plugin.display_name} Error", str(error))
                self.log_box.append(str(error))
                self._notify()

            run_busy_task(
                self, connect, connected, failed,
                key="connection",
            )

    def disconnect_device(self):
        if self.manager.get_device(self.plugin.device_id) is None:
            return

        def disconnected(_result):
            message = self.plugin.format_disconnected()
            self.main_window.log(message)
            self.log_box.append(message)
            self._notify()

        def failed(error):
            QMessageBox.critical(
                self, f"{self.plugin.display_name} Error", str(error)
            )
            self.log_box.append(str(error))
            self._notify()

        run_busy_task(
            self,
            lambda: self.manager.remove_device(self.plugin.device_id),
            disconnected,
            failed,
            key="connection",
        )

    def _notify(self):
        self.sync_connection_status()
        self.main_window.update_device_status()

    def sync_connection_status(self):
        connected = self.manager.get_device(self.plugin.device_id) is not None
        self.status.setText("Connected" if connected else "Disconnected")
        color = "green" if connected else "red"
        self.status.setStyleSheet(f"color:{color}; font-weight:bold;")
