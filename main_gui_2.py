import sys
import csv
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QLabel, QPushButton, QLineEdit,
    QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QMessageBox
)
from PyQt6.QtCore import QTimer

import pyqtgraph as pg

from device_manager import DeviceManager
from lakeshore331 import LakeShore331
from keithley2400 import Keithley2400


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Experiment Device Monitor")
        self.resize(1000, 650)

        self.manager = DeviceManager()

        self.t0 = time.time()
        self.times = []
        self.temp_a_data = []
        self.current_data = []

        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_all_devices)

        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        # ---------- Connection panel ----------
        conn_layout = QHBoxLayout()

        self.ls_port_input = QLineEdit("COM3")
        self.ls_connect_btn = QPushButton("Connect LS331")
        self.ls_disconnect_btn = QPushButton("Disconnect LS331")

        self.k2400_addr_input = QLineEdit("GPIB0::24::INSTR")
        self.k2400_connect_btn = QPushButton("Connect K2400")
        self.k2400_disconnect_btn = QPushButton("Disconnect K2400")

        self.disconnect_all_btn = QPushButton("Disconnect All")

        self.ls_connect_btn.clicked.connect(self.connect_ls331)
        self.ls_disconnect_btn.clicked.connect(self.disconnect_ls331)
        self.k2400_connect_btn.clicked.connect(self.connect_k2400)
        self.k2400_disconnect_btn.clicked.connect(self.disconnect_k2400)
        self.disconnect_all_btn.clicked.connect(self.disconnect_devices)

        conn_layout.addWidget(QLabel("LS331 Port:"))
        conn_layout.addWidget(self.ls_port_input)
        conn_layout.addWidget(self.ls_connect_btn)
        conn_layout.addWidget(self.ls_disconnect_btn)

        conn_layout.addWidget(QLabel("K2400 GPIB:"))
        conn_layout.addWidget(self.k2400_addr_input)
        conn_layout.addWidget(self.k2400_connect_btn)
        conn_layout.addWidget(self.k2400_disconnect_btn)

        conn_layout.addWidget(self.disconnect_all_btn)

        layout.addLayout(conn_layout)

        # ---------- Status table ----------
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Device", "Parameter", "Value"])

        layout.addWidget(self.table)

        # ---------- Plot ----------
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.addLegend()

        self.temp_curve = self.plot.plot([], [], name="LS331 A Temp K")
        self.current_curve = self.plot.plot([], [], name="K2400 Current A")

        layout.addWidget(self.plot)

        # ---------- Control panel ----------
        control_layout = QHBoxLayout()

        self.setpoint_input = QLineEdit("300.00")
        self.setpoint_btn = QPushButton("Set LS331 Setpoint")
        self.heater_off_btn = QPushButton("LS331 Heater Off")

        self.k2400_voltage_input = QLineEdit("0.0")
        self.k2400_set_voltage_btn = QPushButton("Set K2400 Voltage")
        self.k2400_output_on_btn = QPushButton("K2400 Output ON")
        self.k2400_output_off_btn = QPushButton("K2400 Output OFF")

        self.setpoint_btn.clicked.connect(self.set_ls331_setpoint)
        self.heater_off_btn.clicked.connect(self.ls331_heater_off)

        self.k2400_set_voltage_btn.clicked.connect(self.set_k2400_voltage)
        self.k2400_output_on_btn.clicked.connect(self.k2400_output_on)
        self.k2400_output_off_btn.clicked.connect(self.k2400_output_off)

        control_layout.addWidget(QLabel("Setpoint K:"))
        control_layout.addWidget(self.setpoint_input)
        control_layout.addWidget(self.setpoint_btn)
        control_layout.addWidget(self.heater_off_btn)

        control_layout.addWidget(QLabel("K2400 V:"))
        control_layout.addWidget(self.k2400_voltage_input)
        control_layout.addWidget(self.k2400_set_voltage_btn)
        control_layout.addWidget(self.k2400_output_on_btn)
        control_layout.addWidget(self.k2400_output_off_btn)

        layout.addLayout(control_layout)

    def start_timer_if_needed(self):
        if not self.timer.isActive():
            self.timer.start()

    def stop_timer_if_no_devices(self):
        if len(self.manager.devices) == 0:
            self.timer.stop()

    def connect_ls331(self):
        try:
            if self.manager.get_device("LS331") is not None:
                QMessageBox.information(self, "Info", "LS331 is already connected.")
                return

            port = self.ls_port_input.text().strip()
            self.manager.add_device("LS331", LakeShore331(port))
            self.start_timer_if_needed()

        except Exception as e:
            QMessageBox.critical(self, "LS331 Connection Error", str(e))

    def disconnect_ls331(self):
        self.manager.remove_device("LS331")
        self.stop_timer_if_no_devices()

    def connect_k2400(self):
        try:
            if self.manager.get_device("K2400") is not None:
                QMessageBox.information(self, "Info", "K2400 is already connected.")
                return

            address = self.k2400_addr_input.text().strip()
            self.manager.add_device("K2400", Keithley2400(address))
            self.start_timer_if_needed()

        except Exception as e:
            QMessageBox.critical(self, "K2400 Connection Error", str(e))

    def disconnect_k2400(self):
        self.manager.remove_device("K2400")
        self.stop_timer_if_no_devices()

    def disconnect_devices(self):
        self.timer.stop()
        self.manager.close_all()
        self.table.setRowCount(0)

    def update_all_devices(self):
        data = self.manager.read_all()
        self.update_table(data)
        self.update_plot(data)

    def update_table(self, data: dict):
        rows = []

        for device_name, values in data.items():
            for key, value in values.items():
                rows.append((device_name, key, value))

        self.table.setRowCount(len(rows))

        for row, (device, param, value) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(str(device)))
            self.table.setItem(row, 1, QTableWidgetItem(str(param)))
            self.table.setItem(row, 2, QTableWidgetItem(str(value)))

    def update_plot(self, data: dict):
        t = time.time() - self.t0

        self.times.append(t)

        if "LS331" in data and "A_temp_K" in data["LS331"]:
            self.temp_a_data.append(data["LS331"]["A_temp_K"])
        else:
            self.temp_a_data.append(float("nan"))

        if "K2400" in data and "current_A" in data["K2400"]:
            self.current_data.append(data["K2400"]["current_A"])
        else:
            self.current_data.append(float("nan"))

        self.temp_curve.setData(self.times, self.temp_a_data)
        self.current_curve.setData(self.times, self.current_data)

    def set_ls331_setpoint(self):
        try:
            ls = self.manager.get_device("LS331")
            if ls is None:
                return

            value = float(self.setpoint_input.text())
            ls.set_setpoint(value, loop=1)

        except Exception as e:
            QMessageBox.critical(self, "Setpoint Error", str(e))

    def ls331_heater_off(self):
        try:
            ls = self.manager.get_device("LS331")
            if ls is not None:
                ls.heater_off()

        except Exception as e:
            QMessageBox.critical(self, "Heater Error", str(e))

    def set_k2400_voltage(self):
        try:
            smu = self.manager.get_device("K2400")
            if smu is None:
                return

            voltage = float(self.k2400_voltage_input.text())
            smu.set_voltage_source(voltage=voltage, current_limit=0.01)

        except Exception as e:
            QMessageBox.critical(self, "K2400 Error", str(e))

    def k2400_output_on(self):
        smu = self.manager.get_device("K2400")
        if smu is not None:
            smu.output_on()

    def k2400_output_off(self):
        smu = self.manager.get_device("K2400")
        if smu is not None:
            smu.output_off()

    def closeEvent(self, event):
        self.disconnect_devices()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())