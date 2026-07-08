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
from zup36_12 import ZUP36_12

from gui_panels.panel_sequence import SequencePanel

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

# --- 아이폰 스타일의 On/Off 스위치 클래스 ---
class ToggleSwitch(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(60, 28)
        self.update_style()
        self.toggled.connect(self.update_style)

    def update_style(self):
        if self.isChecked():
            # ON 상태: 초록색 배경
            self.setText("ON")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #4CD964; 
                    color: white; 
                    border-radius: 14px; 
                    font-weight: bold; 
                    border: 1px solid #3eb452;
                }
            """)
        else:
            # OFF 상태: 빨간색 배경
            self.setText("OFF")
            self.setStyleSheet("""
                QPushButton {
                    background-color: #FF3B30; 
                    color: white; 
                    border-radius: 14px; 
                    font-weight: bold; 
                    border: 1px solid #d32f2f;
                }
            """)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Experiment Interface (LabVIEW Style)")
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

        # 패널 생성
        self.device_panel = self.create_device_panel()
        self.plot_panel = self.create_plot_panel()
        self.table_panel = self.create_table_panel() # 테이블 패널
        self.sequence_panel = self.create_sequence_panel()
        self.rheed_panel = self.create_rheed_panel()

        # --- [수정] 테이블 패널을 도크가 아닌 메인 화면 중앙에 배치 ---
        self.setCentralWidget(self.table_panel)

        # 도크 생성 (테이블 도크는 제외)
        self.device_dock = self.create_dock("Instrument Communication", self.device_panel)
        self.plot_dock = self.create_dock("Real-time Plot", self.plot_panel)
        self.sequence_dock = self.create_dock("Sequence / Control", self.sequence_panel)
        self.rheed_dock = self.create_dock("RHEED Recording", self.rheed_panel)

        # 도크 배치
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.device_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.sequence_dock)
        
        # Plot을 Communication 아래에 배치
        self.splitDockWidget(self.device_dock, self.plot_dock, Qt.Orientation.Vertical)
        # Rheed를 Sequence 아래에 배치
        self.splitDockWidget(self.sequence_dock, self.rheed_dock, Qt.Orientation.Vertical)

        # 초기 너비 조정
        self.resizeDocks([self.device_dock], [380], Qt.Orientation.Horizontal)
        
        self.create_toolbar()
        self.add_panel_toolbar_actions()
        
        # 시작할 때 테이블 열 숨기기 초기화
        self.update_device_status()

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
        glayout.setColumnStretch(1, 1)

        # 1. LS331 Port
        self.ls_port_input = QLineEdit("/dev/cu.usbserial-A9EQ7W68") # 윈도우/맥 환경에 맞게 기본값 수정 필요
        self.ls_port_input.setMinimumWidth(220)
        self.ls_switch = ToggleSwitch()
        
        glayout.addWidget(QLabel("LS331 Port:"), 0, 0)
        glayout.addWidget(self.ls_port_input, 0, 1)
        glayout.addWidget(self.ls_switch, 0, 2)

        # 2. K2400 Port (Addr에서 Port로 명칭 변경)
        self.k2400_addr_input = QLineEdit("GPIB0::24::INSTR") # 윈도우/맥 환경에 맞게 기본값 수정 필요
        self.k_switch = ToggleSwitch()

        glayout.addWidget(QLabel("K2400 Port:"), 1, 0) # 이 부분 수정됨
        glayout.addWidget(self.k2400_addr_input, 1, 1)
        glayout.addWidget(self.k_switch, 1, 2)

        # --- [추가] 3. ZUP36-12 Port ---
        self.zup_port_input = QLineEdit("/dev/cu.usbserial-A9EQ7W68") # 윈도우/맥 환경에 맞게 기본값 수정 필요
        self.zup_switch = ToggleSwitch()

        glayout.addWidget(QLabel("ZUP Port:"), 2, 0)
        glayout.addWidget(self.zup_port_input, 2, 1)
        glayout.addWidget(self.zup_switch, 2, 2)

        layout.addWidget(group)

        self.ls_switch.clicked.connect(self.handle_ls_toggle)
        self.k_switch.clicked.connect(self.handle_k_toggle)
        self.zup_switch.clicked.connect(self.handle_zup_toggle) # [추가]

        # 3. System Log
        layout.addWidget(QLabel("<b>System Log</b>"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet("background-color: #000000; color: #00FF00; font-family: monospace; font-size: 9pt;")
        self.log_box.setFixedHeight(180) # 세로 크기 축소
        layout.addWidget(self.log_box)

        layout.addStretch(1) # 로그박스 아래 공백을 채워 위로 밀착시킴
        return panel

    # --- 스위치 전용 핸들러 함수 추가 ---
    def handle_ls_toggle(self, checked):
        if checked: self.connect_ls331()
        else: self.disconnect_ls331()

    def handle_k_toggle(self, checked):
        if checked: self.connect_k2400()
        else: self.disconnect_k2400()

    def handle_zup_toggle(self, checked):
        if checked: self.connect_zup()
        else: self.disconnect_zup()

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
        self.data_table.setColumnCount(9)
        self.data_table.setHorizontalHeaderLabels([
            "datetime", "elapsed_s",
            "LS331_A_K", "LS331_B_K", "LS331_setpoint_K",
            "K2400_voltage_V", "K2400_current_A",
            "ZUP_voltage_V", "ZUP_current_A"
        ])
        layout.addWidget(self.data_table)
        return panel

    def create_sequence_panel(self):
        # 복잡한 버튼들을 다 지우고, panel_sequence.py에서 만든 
        # SequencePanel 객체 하나만 딱 넣습니다.
        self.sequence_builder = SequencePanel(self.manager, self.log)
        return self.sequence_builder

    def create_rheed_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5) # 패널 테두리 여백 최소화

        group = QGroupBox("RHEED Camera / Recording")
        glayout = QVBoxLayout(group)
        glayout.setSpacing(8) # 위젯 간 간격 좁게

        # 1. 상단 설정 라인 (Source & FPS 한 줄 배치)
        top_layout = QHBoxLayout()
        
        top_layout.addWidget(QLabel("Source:"))
        self.rheed_source_input = QLineEdit("0")
        self.rheed_source_input.setFixedWidth(40) # 입력창 크기 고정
        top_layout.addWidget(self.rheed_source_input)

        top_layout.addSpacing(15) # 간격 벌리기

        top_layout.addWidget(QLabel("FPS:"))
        self.rheed_fps_spin = QDoubleSpinBox()
        self.rheed_fps_spin.setValue(30.0)
        self.rheed_fps_spin.setFixedWidth(60)
        top_layout.addWidget(self.rheed_fps_spin)
        
        top_layout.addStretch(1) # 오른쪽 빈 공간 채우기
        glayout.addLayout(top_layout)

        # 2. 카메라 프리뷰 영역 (크기 약간 축소)
        self.rheed_preview_label = QLabel("No RHEED preview")
        self.rheed_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rheed_preview_label.setMinimumHeight(160) # 높이 최적화
        self.rheed_preview_label.setStyleSheet("""
            background: #000; 
            color: #777; 
            border: 2px inset #555; 
            font-weight: bold;
        """)
        glayout.addWidget(self.rheed_preview_label)

        # 3. 저장 폴더 라인 (경로창 + 버튼 한 줄 배치)
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Path:"))
        
        # 라벨 대신 읽기 전용 QLineEdit 사용 (더 깔끔함)
        self.rheed_dir_display = QLineEdit(self.rheed_output_dir)
        self.rheed_dir_display.setReadOnly(True)
        self.rheed_dir_display.setStyleSheet("background-color: #EEE; color: #555; font-size: 9pt;")
        folder_layout.addWidget(self.rheed_dir_display)

        self.rheed_choose_dir_btn = QPushButton("Choose")
        self.rheed_choose_dir_btn.setFixedWidth(65)
        self.rheed_choose_dir_btn.clicked.connect(self.choose_rheed_output_dir)
        folder_layout.addWidget(self.rheed_choose_dir_btn)
        
        glayout.addLayout(folder_layout)

        # 4. 제어 버튼 라인 (Start / Stop Preview 한 줄 배치)
        btn_ctrl_layout = QHBoxLayout()
        self.rheed_start_preview_btn = QPushButton("Start Preview")
        self.rheed_stop_preview_btn = QPushButton("Stop Preview")
        
        # 버튼 높이 조절
        self.rheed_start_preview_btn.setFixedHeight(30)
        self.rheed_stop_preview_btn.setFixedHeight(30)
        
        self.rheed_start_preview_btn.clicked.connect(self.start_rheed_preview)
        self.rheed_stop_preview_btn.clicked.connect(self.stop_rheed_preview)
        
        btn_ctrl_layout.addWidget(self.rheed_start_preview_btn)
        btn_ctrl_layout.addWidget(self.rheed_stop_preview_btn)
        glayout.addLayout(btn_ctrl_layout)

        # 5. 녹화 버튼 (하단에 강조)
        self.rheed_record_btn = QPushButton("Start Recording")
        self.rheed_record_btn.setFixedHeight(35)
        self.rheed_record_btn.setStyleSheet("background-color: #FF9999; font-weight: bold; border: 2px outset #FFFFFF;")
        self.rheed_record_btn.clicked.connect(self.toggle_rheed_recording)
        glayout.addWidget(self.rheed_record_btn)

        layout.addWidget(group)
        return panel

    # --- 추가 수정: 폴더 선택 시 화면 업데이트 함수 ---
    def choose_rheed_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Choose RHEED Save Folder", self.rheed_output_dir)
        if path:
            self.rheed_output_dir = path
            self.rheed_dir_display.setText(path) # display 위젯 업데이트
            self.log(f"RHEED save folder changed: {path}")

    def connect_ls331(self):
        try:
            if self.manager.get_device("LS331") is not None:
                return
            port = self.ls_port_input.text().strip()
            
            # 1. 객체 생성
            ls = LakeShore331(port)
            
            # --- [안전 기능 추가] 장비 연결 즉시 램프 강제 종료 ---
            time.sleep(0.2) # 통신 안정화를 위한 미세 대기
            ls.write("MODE 1")      # Remote 모드 활성화
            time.sleep(0.2)
            ls.write("RAMP 1,0,1.0") # Loop 1의 램프를 Off(0)로 설정
            self.log(">>> LS331 Safety Init: Ramp Forced OFF.")
            # ------------------------------------------------
            
            self.manager.add_device("LS331", ls)
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

    def connect_zup(self):
        try:
            if self.manager.get_device("ZUP") is not None: return
            port = self.zup_port_input.text().strip()
            
            zup = ZUP36_12(port) # 우리가 만든 클래스로 연결
            self.manager.add_device("ZUP", zup)
            
            self.log(f"ZUP36-12 connected: {port}")
            self.start_timer()
            self.update_device_status()
        except Exception as e:
            QMessageBox.critical(self, "ZUP Error", str(e))
            self.update_device_status() # 에러 시 스위치 되돌리기

    def disconnect_zup(self):
        self.manager.remove_device("ZUP")
        self.log("ZUP36-12 disconnected")
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
        # 1. LS331 연결 상태 확인 및 스위치 동기화
        is_ls_connected = self.manager.get_device("LS331") is not None
        self.ls_switch.blockSignals(True)
        self.ls_switch.setChecked(is_ls_connected)
        self.ls_switch.update_style()
        self.ls_switch.blockSignals(False)

        # 2. K2400 연결 상태 확인 및 스위치 동기화
        is_k_connected = self.manager.get_device("K2400") is not None
        self.k_switch.blockSignals(True)
        self.k_switch.setChecked(is_k_connected)
        self.k_switch.update_style()
        self.k_switch.blockSignals(False)

        # 3. ZUP 연결 상태 확인 및 스위치 동기화
        is_zup_connected = self.manager.get_device("ZUP") is not None
        self.zup_switch.blockSignals(True)
        self.zup_switch.setChecked(is_zup_connected)
        self.zup_switch.update_style()
        self.zup_switch.blockSignals(False)

        # --- [핵심 추가] 연결된 장비의 데이터 열만 표시하기 ---
        # 열 인덱스: 0:datetime, 1:elapsed, 2:LS_A, 3:LS_B, 4:LS_Set, 5:K_Volt, 6:K_Curr
        
        # LS331 열 (2, 3, 4번 열) 제어
        for i in [2, 3, 4]:
            self.data_table.setColumnHidden(i, not is_ls_connected)
            
        # K2400 열 (5, 6번 열) 제어
        for i in [5, 6]:
            self.data_table.setColumnHidden(i, not is_k_connected)

        # ZUP 열 (7, 8 번 열) 제어
        for i in [7, 8]:
            self.data_table.setColumnHidden(i, not is_zup_connected)

    def update_measurement(self):
        data = self.manager.read_all()
        now = datetime.now().isoformat(timespec="seconds")
        elapsed = time.time() - self.t0

        ls = data.get("LS331", {})
        k = data.get("K2400", {})
        zup = data.get("ZUP", {})

        # ZUP 알람 체크 및 로그 출력 (AL00000이 정상이므로, 그 외엔 에러 로그)
        alm = zup.get("alarm", "AL00000")
        if alm and alm != "AL00000":
            # 빨간색 폰트로 로그 출력 (에러 발생 시)
            self.log_box.append(f"<span style='color:#FF3B30;'>[{datetime.now().strftime('%H:%M:%S')}] ZUP ALARM DETECTED: {alm}</span>")

        row = {
            "datetime": now,
            "elapsed_s": elapsed,
            "LS331_A_K": ls.get("A_temp_K", ""),
            "LS331_B_K": ls.get("B_temp_K", ""),
            "LS331_setpoint_K": ls.get("setpoint_K", ""),
            "K2400_voltage_V": k.get("voltage_V", ""),
            "K2400_current_A": k.get("current_A", ""),
            "ZUP_voltage_V": zup.get("voltage_V", ""),
            "ZUP_current_A": zup.get("current_A", "")
        }
        self.data_rows.append(row)
        self.append_table_row(row)
        self.update_plot(row)

    def append_table_row(self, row):
        r = self.data_table.rowCount()
        self.data_table.insertRow(r)
        columns = [
            "datetime", "elapsed_s",
            "LS331_A_K", "LS331_B_K","LS331_setpoint_K",
            "K2400_voltage_V", "K2400_current_A",
            "ZUP_voltage_V", "ZUP_current_A"
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
