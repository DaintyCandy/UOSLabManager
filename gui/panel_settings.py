import os

from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from .widget_busy_spinner import BusySpinnerDialog


class SettingsPanel(QWidget):
    def __init__(self, theme_manager, theme_changed=None, parent=None, camera_workspace=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.theme_changed = theme_changed
        self.camera_workspace = camera_workspace
        self.settings = QSettings("UOSLabManager", "UOSLabManager")
        self.theme_spinner = None
        layout = QVBoxLayout(self)
        appearance = QGroupBox("Appearance")
        form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(theme_manager.THEMES.keys())
        self.theme_combo.setCurrentText(theme_manager.display_name())
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        form.addRow("Theme", self.theme_combo)
        form.addRow("", QLabel("Theme changes are applied immediately and saved automatically."))
        layout.addWidget(appearance)
        camera = QGroupBox("Camera Storage")
        camera_form = QFormLayout(camera)
        path_row = QHBoxLayout()
        self.camera_path = QLineEdit(
            camera_workspace.output_dir if camera_workspace is not None else ""
        )
        self.camera_path.setReadOnly(True)
        path_row.addWidget(self.camera_path)
        choose_path = QPushButton("Choose")
        choose_path.clicked.connect(self.choose_camera_path)
        path_row.addWidget(choose_path)
        camera_form.addRow("Recording Path", path_row)
        layout.addWidget(camera)
        data = QGroupBox("Data Table Storage")
        data_form = QFormLayout(data)
        data_path_row = QHBoxLayout()
        default_data_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        self.data_path = QLineEdit(self.settings.value("data/output_dir", default_data_path))
        self.data_path.setReadOnly(True)
        data_path_row.addWidget(self.data_path)
        choose_data_path = QPushButton("Choose")
        choose_data_path.clicked.connect(self.choose_data_path)
        data_path_row.addWidget(choose_data_path)
        data_form.addRow("CSV Save Path", data_path_row)
        layout.addWidget(data)
        layout.addStretch()

    def change_theme(self, display_name):
        if self.theme_spinner is not None:
            return
        self.pending_theme_name = display_name
        self.theme_combo.setEnabled(False)
        self.theme_spinner = BusySpinnerDialog(self)
        self.theme_spinner.show()
        QTimer.singleShot(80, self.apply_pending_theme)

    def apply_pending_theme(self):
        try:
            theme = self.theme_manager.THEMES[self.pending_theme_name]
            self.theme_manager.apply(theme)
            if self.theme_changed:
                self.theme_changed(theme)
        finally:
            if self.theme_spinner is not None:
                self.theme_spinner.close()
                self.theme_spinner.deleteLater()
                self.theme_spinner = None
            self.theme_combo.setEnabled(True)

    def choose_camera_path(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Camera Save Folder", self.camera_path.text())
        if not path:
            return
        self.camera_path.setText(path)
        self.settings.setValue("camera/output_dir", path)
        if self.camera_workspace is not None:
            self.camera_workspace.set_output_dir(path)

    def choose_data_path(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Data Table Save Folder", self.data_path.text())
        if not path:
            return
        self.data_path.setText(path)
        self.settings.setValue("data/output_dir", path)
