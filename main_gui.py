import sys
import csv
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit, QComboBox,
    QMessageBox, QFileDialog
)
from PyQt6.QtCore import QTimer

import pyqtgraph as pg

from lakeshore331 import LakeShore331


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Measurement System Monitor")
        self.resize(900, 600)

        self.ls = None
        self.is_logging = False
        self.csv_file = None
        self.csv_writer = None

        self.t0 = time.time()
        self.times = []
        self.temp_a_data = []
        self.temp_b_data = []

        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_measurement)

        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)

        # Connection area
        conn_layout = QHBoxLayout()

        self.port_input = QLineEdit("COM3")
        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")

        self.connect_btn.clicked.connect(self.connect_device)
        self.disconnect_btn.clicked.connect(self.disconnect_device)

        conn_layout.addWidget(QLabel("Port:"))
        conn_layout.addWidget(self.port_input)
        conn_layout.addWidget(self.connect_btn)
        conn_layout.addWidget(self.disconnect_btn)

        main_layout.addLayout(conn_layout)

        # Display area
        display_layout = QGridLayout()

        self.status_label = QLabel("Disconnected")
        self.temp_a_label = QLabel("-- K")
        self.temp_b_label = QLabel("-- K")
        self.setpoint_label = QLabel("-- K")
        self.heater_label = QLabel("--")

        display_layout.addWidget(QLabel("Status:"), 0, 0)
        display_layout.addWidget(self.status_label, 0, 1)

        display_layout.addWidget(QLabel("Input A:"), 1, 0)
        display_layout.addWidget(self.temp_a_label, 1, 1)

        display_layout.addWidget(QLabel("Input B:"), 2, 0)
        display_layout.addWidget(self.temp_b_label, 2, 1)

        display_layout.addWidget(QLabel("Setpoint:"), 3, 0)
        display_layout.addWidget(self.setpoint_label, 3, 1)

        display_layout.addWidget(QLabel("Heater Range:"), 4, 0)
        display_layout.addWidget(self.heater_label, 4, 1)

        main_layout.addLayout(display_layout)

        # Control area
        control_layout = QHBoxLayout()

        self.setpoint_input = QLineEdit("301.05")
        self.setpoint_btn = QPushButton("Set Setpoint")

        self.heater_range_combo = QComboBox()
        self.heater_range_combo.addItems(["0: Off", "1: Low", "2: Medium", "3: High"])
        self.heater_range_btn = QPushButton("Set Heater Range")
        self.heater_off_btn = QPushButton("Heater Off")

        self.setpoint_btn.clicked.connect(self.set_setpoint)
        self.heater_range_btn.clicked.connect(self.set_heater_range)
        self.heater_off_btn.clicked.connect(self.heater_off)

        control_layout.addWidget(QLabel("Setpoint K:"))
        control_layout.addWidget(self.setpoint_input)
        control_layout.addWidget(self.setpoint_btn)
        control_layout.addWidget(self.heater_range_combo)
        control_layout.addWidget(self.heater_range_btn)
        control_layout.addWidget(self.heater_off_btn)

        main_layout.addLayout(control_layout)

        # Logging area
        log_layout = QHBoxLayout()

        self.start_log_btn = QPushButton("Start Logging")
        self.stop_log_btn = QPushButton("Stop Logging")

        self.start_log_btn.clicked.connect(self.start_logging)
        self.stop_log_btn.clicked.connect(self.stop_logging)

        log_layout.addWidget(self.start_log_btn)
        log_layout.addWidget(self.stop_log_btn)

        main_layout.addLayout(log_layout)

        # Plot area
        self.plot = pg.PlotWidget()
        self.plot.setLabel("left", "Temperature", units="K")
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.addLegend()

        self.curve_a = self.plot.plot([], [], pen="r", name="Input A")
        self.curve_b = self.plot.plot([], [], pen="b", name="Input B")

        main_layout.addWidget(self.plot)

    def connect_device(self):
        port = self.port_input.text().strip()

        try:
            self.ls = LakeShore331(port)
            self.status_label.setText(f"Connected: {port}")
            self.timer.start()

        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            self.ls = None

    def disconnect_device(self):
        self.timer.stop()
        self.stop_logging()

        if self.ls is not None:
            self.ls.close()
            self.ls = None

        self.status_label.setText("Disconnected")

    def update_measurement(self):
        if self.ls is None:
            return

        try:
            temp_a = self.ls.read_temp("A")
            temp_b = self.ls.read_temp("B")
            setpoint = self.ls.get_setpoint(loop=1)
            heater_range = self.ls.get_heater_range()

            self.temp_a_label.setText(f"{temp_a:.3f} K")
            self.temp_b_label.setText(f"{temp_b:.3f} K")
            self.setpoint_label.setText(f"{setpoint:.3f} K")
            self.heater_label.setText(str(heater_range))

            t = time.time() - self.t0

            self.times.append(t)
            self.temp_a_data.append(temp_a)
            self.temp_b_data.append(temp_b)

            self.curve_a.setData(self.times, self.temp_a_data)
            self.curve_b.setData(self.times, self.temp_b_data)

            if self.is_logging and self.csv_writer is not None:
                self.csv_writer.writerow([
                    datetime.now().isoformat(),
                    t,
                    temp_a,
                    temp_b,
                    setpoint,
                    heater_range
                ])
                self.csv_file.flush()

        except Exception as e:
            self.status_label.setText(f"Error: {e}")

    def set_setpoint(self):
        if self.ls is None:
            return

        try:
            value = float(self.setpoint_input.text())
            self.ls.set_setpoint(value, loop=1)

        except Exception as e:
            QMessageBox.critical(self, "Setpoint Error", str(e))

    def set_heater_range(self):
        if self.ls is None:
            return

        try:
            range_value = self.heater_range_combo.currentIndex()
            self.ls.set_heater_range(range_value)

        except Exception as e:
            QMessageBox.critical(self, "Heater Range Error", str(e))

    def heater_off(self):
        if self.ls is None:
            return

        try:
            self.ls.heater_off()

        except Exception as e:
            QMessageBox.critical(self, "Heater Off Error", str(e))

    def start_logging(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save CSV",
            "temperature_log.csv",
            "CSV Files (*.csv)"
        )

        if not path:
            return

        self.csv_file = open(path, "w", newline="", encoding="utf-8")
        self.csv_writer = csv.writer(self.csv_file)

        self.csv_writer.writerow([
            "datetime",
            "elapsed_s",
            "temp_a_K",
            "temp_b_K",
            "setpoint_K",
            "heater_range"
        ])

        self.is_logging = True

    def stop_logging(self):
        self.is_logging = False

        if self.csv_file is not None:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None

    def closeEvent(self, event):
        self.disconnect_device()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())