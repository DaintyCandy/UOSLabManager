import sys
import csv
import os
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QTextEdit, QDockWidget, QToolBar, QGroupBox, QDoubleSpinBox, QDial
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QImage, QPixmap, QFont

import pyqtgraph as pg

try:
    import cv2
except ImportError:
    cv2 = None

from device_manager import DeviceManager
from lakeshore331 import LakeShore331
from keithley2400 import Keithley2400

from gui_panels.panel_lakeshore import LakeshorePanel
from gui_panels.panel_keithley import KeithleyPanel

# ==========================================
# LabVIEW 스타일 CSS (QSS) - 교수님 취향 반영
# ==========================================
LABVIEW_STYLE = """
QWidget {
    background-color: #D4D0C8; /* LabVIEW 클래식 회색 배경 */
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
    color: #000000;
}
QGroupBox {
    border: 2px solid #808080;
    border-radius: 3px;
    margin-top: 2ex;
    font-weight: bold;
    background-color: #DFDBD3;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #003366;
}
QPushButton {
    background-color: #E0E0E0;
    border: 2px outset #FFFFFF;
    border-bottom-color: #808080;
    border-right-color: #808080;
    padding: 4px;
    font-weight: bold;
}
QPushButton:pressed {
    border: 2px inset #808080;
    background-color: #D0D0D0;
}
QComboBox, QDoubleSpinBox, QLineEdit {
    background-color: #FFFFFF;
    border: 1px inset #808080;
    padding: 2px;
}
QComboBox {
    min-width: 80px; /* 옵션창 작게 */
}
QDoubleSpinBox {
    min-width: 80px; /* 숫자창 작게 */
}
QTableWidget {
    background-color: #FFFFFF;
    gridline-color: #C0C0C0;
}
QHeaderView::section {
    background-color: #D4D0C8;
    border: 1px outset #FFFFFF;
    padding: 2px;
}
"""

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("UOSLabManager v1.0")
        self.resize(1300, 800)

        self.manager = DeviceManager()

        self.t0 = time.time()
        self.data_rows = []

        self.times = []
        self.temp_a_data = []
        self.current_data = []

        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_measurement)

        self.rheed_capture = None
        self.rheed_writer = None
        self.rheed_recording = False
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.rheed_output_dir = os.path.join(current_dir, "rheed_recordings")
        self.rheed_video_path = ""

        self.rheed_timer = QTimer()
        self.rheed_timer.setInterval(33)
        self.rheed_timer.timeout.connect(self.update_rheed_frame)

        self.init_ui()

    def init_ui(self):
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.AnimatedDocks
        )

        # 패널 먼저 생성 (에러 해결 핵심)
        self.device_panel = self.create_device_panel()
        self.plot_panel = self.create_plot_panel()
        self.table_panel = self.create_table_panel()
        self.sequence_panel = self.create_sequence_panel()
        self.rheed_panel = self.create_rheed_panel()

        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_label = QLabel("Use the toolbar to show, hide, and arrange panels.")
        center_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(center_label)
        self.setCentralWidget(center_panel)

        self.device_dock = self.create_dock("Instrument Communication", self.device_panel)
        self.plot_dock = self.create_dock("Real-time Plot", self.plot_panel)
        self.table_dock = self.create_dock("Measurement Table", self.table_panel)
        self.sequence_dock = self.create_dock("Sequence / Control", self.sequence_panel)
        self.rheed_dock = self.create_dock("RHEED Recording", self.rheed_panel)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.device_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.plot_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.table_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.sequence_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.rheed_dock)

        self.splitDockWidget(self.device_dock, self.plot_dock, Qt.Orientation.Horizontal)
        self.splitDockWidget(self.sequence_dock, self.rheed_dock, Qt.Orientation.Vertical)
        self.resizeDocks([self.device_dock], [360], Qt.Orientation.Horizontal)
        self.resizeDocks([self.table_dock], [260], Qt.Orientation.Vertical)
        
        # 패널들이 모두 만들어진 후 툴바 생성
        self.create_toolbar()
        self.add_panel_toolbar_actions()

    def create_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.port_action = QAction("PORT", self)
        self.setup_action = QAction("SETUP", self)
        self.save_action = QAction("SAVE", self)
        self.seq_action = QAction("SEQ", self)
        self.stop_action = QAction("STOP", self)
        self.exit_action = QAction("EXIT", self)

        self.port_action.triggered.connect(lambda: self.device_dock.raise_())
        self.setup_action.triggered.connect(lambda: self.sequence_dock.raise_())
        self.save_action.triggered.connect(self.save_table_csv)
        self.seq_action.triggered.connect(self.start_timer)
        self.stop_action.triggered.connect(self.disconnect_all)
        self.exit_action.triggered.connect(self.close)

        for action in [self.port_action, self.setup_action, self.save_action, 
                       self.seq_action, self.stop_action, self.exit_action]:
            self.toolbar.addAction(action)

    def add_panel_toolbar_actions(self):
        self.toolbar.addSeparator()

        panel_actions = [
            ("COMM", self.device_dock),
            ("PLOT", self.plot_dock),
            ("TABLE", self.table_dock),
            ("CTRL", self.sequence_dock),
            ("RHEED", self.rheed_dock),
        ]

        for text, dock in panel_actions:
            action = dock.toggleViewAction()
            action.setText(text)
            self.toolbar.addAction(action)

    def create_dock(self, title, widget):
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        return dock

    def create_device_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        group = QGroupBox("Device Manager")
        glayout = QGridLayout(group)

        self.ls_port_input = QLineEdit("/dev/cu.usbserial-A9EQ7W68")
        self.k2400_addr_input = QLineEdit("GPIB0::24::INSTR")

        self.ls_connect_btn = QPushButton("Connect LS331")
        self.ls_disconnect_btn = QPushButton("Disconnect LS331")
        self.k_connect_btn = QPushButton("Connect K2400")
        self.k_disconnect_btn = QPushButton("Disconnect K2400")
        self.disconnect_all_btn = QPushButton("Disconnect All")
        self.disconnect_all_btn.setStyleSheet("background-color: #FF6666;") # 비상 정지는 붉은색

        self.ls_connect_btn.clicked.connect(self.connect_ls331)
        self.ls_disconnect_btn.clicked.connect(self.disconnect_ls331)
        self.k_connect_btn.clicked.connect(self.connect_k2400)
        self.k_disconnect_btn.clicked.connect(self.disconnect_k2400)
        self.disconnect_all_btn.clicked.connect(self.disconnect_all)

        glayout.addWidget(QLabel("LS331 Port:"), 0, 0)
        glayout.addWidget(self.ls_port_input, 0, 1)
        glayout.addWidget(self.ls_connect_btn, 0, 2)
        glayout.addWidget(self.ls_disconnect_btn, 0, 3)

        glayout.addWidget(QLabel("K2400 Addr:"), 1, 0)
        glayout.addWidget(self.k2400_addr_input, 1, 1)
        glayout.addWidget(self.k_connect_btn, 1, 2)
        glayout.addWidget(self.k_disconnect_btn, 1, 3)
        glayout.addWidget(self.disconnect_all_btn, 2, 0, 1, 4)
        
        layout.addWidget(group)

        self.device_status_table = QTableWidget()
        self.device_status_table.setColumnCount(2)
        self.device_status_table.setHorizontalHeaderLabels(["Device", "Status"])
        layout.addWidget(self.device_status_table)

        return panel

    def create_plot_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        group = QGroupBox("Real-time Plot")
        glayout = QVBoxLayout(group)

        # LabVIEW 스타일의 흰 배경 그래프
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.addLegend()

        self.temp_curve = self.plot.plot([], [], name="LS331 A Temp [K]", pen=pg.mkPen(color='r', width=2))
        self.current_curve = self.plot.plot([], [], name="K2400 Current [A]", pen=pg.mkPen(color='b', width=2))

        glayout.addWidget(self.plot)
        layout.addWidget(group)
        return panel

    def create_table_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)

        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Data Table"))

        self.save_table_btn = QPushButton("Save Table CSV")
        self.clear_table_btn = QPushButton("Clear Table")
        self.save_table_btn.clicked.connect(self.save_table_csv)
        self.clear_table_btn.clicked.connect(self.clear_table)

        header_layout.addWidget(self.save_table_btn)
        header_layout.addWidget(self.clear_table_btn)
        layout.addLayout(header_layout)

        self.data_table = QTableWidget()
        self.data_table.setColumnCount(7)
        self.data_table.setHorizontalHeaderLabels([
            "datetime", "elapsed_s", "LS331_A_K", "LS331_B_K",
            "LS331_setpoint_K", "K2400_voltage_V", "K2400_current_A",
        ])
        layout.addWidget(self.data_table)
        return panel

    def create_sequence_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # --- LS331 컨트롤 파트 (교체됨) ---
        self.lakeshore_panel = LakeshorePanel(self.manager, self.log)
        layout.addWidget(self.lakeshore_panel)

        # --- K2400 컨트롤 파트 (교체됨) ---
        self.keithley_panel = KeithleyPanel(self.manager, self.log)
        layout.addWidget(self.keithley_panel)

        # --- 로그 박스 파트 (다시 추가) ---
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150) # 로그박스 크기 조절
        layout.addWidget(QLabel("Log"))
        layout.addWidget(self.log_box)

        return panel  # <--- 이 리턴 문이 없으면 화면에 아무것도 안 나옵니다!

    def create_rheed_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        group = QGroupBox("RHEED Camera / Recording")
        glayout = QVBoxLayout(group)

        self.rheed_source_input = QLineEdit("0")
        self.rheed_fps_spin = QDoubleSpinBox()
        self.rheed_fps_spin.setValue(30.0)
        self.rheed_dir_label = QLabel(self.rheed_output_dir)

        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Source:"))
        source_layout.addWidget(self.rheed_source_input)
        source_layout.addWidget(QLabel("FPS:"))
        source_layout.addWidget(self.rheed_fps_spin)
        glayout.addLayout(source_layout)

        self.rheed_preview_label = QLabel("No RHEED preview")
        self.rheed_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rheed_preview_label.setMinimumHeight(180)
        self.rheed_preview_label.setStyleSheet("background: #111; color: #ddd; border: 2px inset #555;")
        glayout.addWidget(self.rheed_preview_label)

        btn_layout = QGridLayout()
        self.rheed_choose_dir_btn = QPushButton("Choose Save Folder")
        self.rheed_start_preview_btn = QPushButton("Start Preview")
        self.rheed_stop_preview_btn = QPushButton("Stop Preview")
        self.rheed_record_btn = QPushButton("Start Recording")
        self.rheed_record_btn.setStyleSheet("background-color: #FF9999;") # 녹화버튼 약간 붉게

        self.rheed_choose_dir_btn.clicked.connect(self.choose_rheed_output_dir)
        self.rheed_start_preview_btn.clicked.connect(self.start_rheed_preview)
        self.rheed_stop_preview_btn.clicked.connect(self.stop_rheed_preview)
        self.rheed_record_btn.clicked.connect(self.toggle_rheed_recording)

        btn_layout.addWidget(QLabel("Save Folder:"), 0, 0)
        btn_layout.addWidget(self.rheed_dir_label, 0, 1, 1, 3)
        btn_layout.addWidget(self.rheed_choose_dir_btn, 1, 0, 1, 4)
        btn_layout.addWidget(self.rheed_start_preview_btn, 2, 0, 1, 2)
        btn_layout.addWidget(self.rheed_stop_preview_btn, 2, 2, 1, 2)
        btn_layout.addWidget(self.rheed_record_btn, 3, 0, 1, 4)
        
        glayout.addLayout(btn_layout)
        layout.addWidget(group)

        return panel

    # --- 통신 및 원래 백엔드 로직 (수정 안 함, 그대로 유지) ---
    def connect_ls331(self):
        try:
            if self.manager.get_device("LS331") is not None:
                return
            port = self.ls_port_input.text().strip()
            self.manager.add_device("LS331", LakeShore331(port))
            self.log(f"LS331 connected: {port}")
            self.start_timer()
            self.update_device_status()
        except Exception as e:
            QMessageBox.critical(self, "LS331 Error", str(e))

    def disconnect_ls331(self):
        self.manager.remove_device("LS331")
        self.log("LS331 disconnected")
        self.update_device_status()
        self.stop_timer_if_empty()

    def connect_k2400(self):
        try:
            if self.manager.get_device("K2400") is not None:
                return
            address = self.k2400_addr_input.text().strip()
            self.manager.add_device("K2400", Keithley2400(address))
            self.log(f"K2400 connected: {address}")
            self.start_timer()
            self.update_device_status()
        except Exception as e:
            QMessageBox.critical(self, "K2400 Error", str(e))

    def disconnect_k2400(self):
        self.manager.remove_device("K2400")
        self.log("K2400 disconnected")
        self.update_device_status()
        self.stop_timer_if_empty()

    def disconnect_all(self):
        self.timer.stop()
        self.manager.close_all()
        self.update_device_status()
        self.log("All devices disconnected")

    def start_timer(self):
        if not self.timer.isActive():
            self.timer.start()

    def stop_timer_if_empty(self):
        if len(self.manager.devices) == 0:
            self.timer.stop()

    def update_device_status(self):
        rows = []
        for name in ["LS331", "K2400"]:
            status = "Connected" if self.manager.get_device(name) else "Disconnected"
            rows.append((name, status))
        self.device_status_table.setRowCount(len(rows))
        for i, (name, status) in enumerate(rows):
            self.device_status_table.setItem(i, 0, QTableWidgetItem(name))
            self.device_status_table.setItem(i, 1, QTableWidgetItem(status))

    def update_measurement(self):
        data = self.manager.read_all()
        now = datetime.now().isoformat(timespec="seconds")
        elapsed = time.time() - self.t0
        ls = data.get("LS331", {})
        k = data.get("K2400", {})
        row = {
            "datetime": now,
            "elapsed_s": elapsed,
            "LS331_A_K": ls.get("A_temp_K", ""),
            "LS331_B_K": ls.get("B_temp_K", ""),
            "LS331_setpoint_K": ls.get("setpoint_K", ""),
            "K2400_voltage_V": k.get("voltage_V", ""),
            "K2400_current_A": k.get("current_A", ""),
        }
        self.data_rows.append(row)
        self.append_table_row(row)
        self.update_plot(row)

    def append_table_row(self, row):
        r = self.data_table.rowCount()
        self.data_table.insertRow(r)
        columns = [
            "datetime", "elapsed_s", "LS331_A_K", "LS331_B_K",
            "LS331_setpoint_K", "K2400_voltage_V", "K2400_current_A",
        ]
        for c, key in enumerate(columns):
            value = row[key]
            if isinstance(value, float):
                text = f"{value:.6g}"
            else:
                text = str(value)
            self.data_table.setItem(r, c, QTableWidgetItem(text))

    def update_plot(self, row):
        self.times.append(row["elapsed_s"])
        temp = row["LS331_A_K"]
        current = row["K2400_current_A"]
        self.temp_a_data.append(float(temp) if temp != "" else float("nan"))
        self.current_data.append(float(current) if current != "" else float("nan"))
        self.temp_curve.setData(self.times, self.temp_a_data)
        self.current_curve.setData(self.times, self.current_data)

    def save_table_csv(self):
        if not self.data_rows:
            QMessageBox.information(self, "Save CSV", "No data to save.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Data Table", "experiment_data.csv", "CSV Files (*.csv)")
        if not path:
            return
        columns = list(self.data_rows[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(self.data_rows)
        self.log(f"Saved table: {path}")

    def clear_table(self):
        self.data_rows.clear()
        self.data_table.setRowCount(0)
        self.times.clear()
        self.temp_a_data.clear()
        self.current_data.clear()
        self.temp_curve.setData([], [])
        self.current_curve.setData([], [])
        self.t0 = time.time()
        self.log("Table cleared")

    # --- 카메라 연동 파트 (그대로 유지) ---
    def choose_rheed_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose RHEED Save Folder", self.rheed_output_dir)
        if path:
            self.rheed_output_dir = path
            self.rheed_dir_label.setText(path)
            self.log(f"RHEED save folder: {path}")

    def parse_rheed_source(self):
        source = self.rheed_source_input.text().strip()
        if source.isdigit():
            return int(source)
        return source

    def get_rheed_fps(self):
        return self.rheed_fps_spin.value() # QDoubleSpinBox에서 직접 값 가져옴

    def start_rheed_preview(self):
        if cv2 is None:
            QMessageBox.critical(self, "RHEED Error", "OpenCV is not installed.")
            return False
        if self.rheed_capture is not None:
            return True
        source = self.parse_rheed_source()
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            capture.release()
            QMessageBox.critical(self, "RHEED Error", f"Cannot open RHEED source: {source}")
            return False
        self.rheed_capture = capture
        self.rheed_timer.start()
        self.log(f"RHEED preview started: {source}")
        return True

    def stop_rheed_preview(self):
        self.stop_rheed_recording()
        self.rheed_timer.stop()
        if self.rheed_capture is not None:
            self.rheed_capture.release()
            self.rheed_capture = None
        self.rheed_preview_label.setText("No RHEED preview")
        self.log("RHEED preview stopped")

    def toggle_rheed_recording(self):
        if self.rheed_recording:
            self.stop_rheed_recording()
            return
        fps = self.get_rheed_fps()
        if fps is None:
            return
        if not self.start_rheed_preview():
            return
        os.makedirs(self.rheed_output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.rheed_video_path = os.path.join(self.rheed_output_dir, f"rheed_{timestamp}.mp4")
        self.rheed_recording = True
        self.rheed_record_btn.setText("Stop Recording")
        self.log(f"RHEED recording armed: {self.rheed_video_path}")

    def stop_rheed_recording(self):
        if self.rheed_writer is not None:
            self.rheed_writer.release()
            self.rheed_writer = None
        if self.rheed_recording:
            self.rheed_recording = False
            self.rheed_record_btn.setText("Start Recording")
            self.log(f"RHEED recording saved: {self.rheed_video_path}")

    def update_rheed_frame(self):
        if self.rheed_capture is None:
            return
        ok, frame = self.rheed_capture.read()
        if not ok:
            self.log("RHEED frame read failed")
            self.stop_rheed_preview()
            return
        if self.rheed_recording:
            self.write_rheed_frame(frame)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        bytes_per_line = channels * width
        image = QImage(rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        scaled = pixmap.scaled(
            self.rheed_preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.rheed_preview_label.setPixmap(scaled)

    def write_rheed_frame(self, frame):
        if self.rheed_writer is None:
            fps = self.get_rheed_fps()
            if fps is None:
                self.stop_rheed_recording()
                return
            height, width = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            self.rheed_writer = cv2.VideoWriter(self.rheed_video_path, fourcc, int(fps), (width, height))
            if not self.rheed_writer.isOpened():
                QMessageBox.critical(self, "RHEED Error", "Cannot create RHEED video file.")
                self.stop_rheed_recording()
                return
        self.rheed_writer.write(frame)

    def log(self, message):
        self.log_box.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def closeEvent(self, event):
        self.stop_rheed_preview()
        self.disconnect_all()
        event.accept()

if __name__ == "__main__":
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    app.setStyleSheet(LABVIEW_STYLE) # LabVIEW 스타일 적용
    win = MainWindow()
    win.show()
    sys.exit(app.exec())