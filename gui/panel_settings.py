from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)


class SettingsPanel(QWidget):
    def __init__(self, theme_manager, theme_changed=None, parent=None, camera_workspace=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.theme_changed = theme_changed
        self.camera_workspace = camera_workspace
        self.settings = QSettings("UOSLabManager", "UOSLabManager")
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
        layout.addStretch()

    def change_theme(self, display_name):
        theme = self.theme_manager.THEMES[display_name]
        self.theme_manager.apply(theme)
        if self.theme_changed:
            self.theme_changed(theme)

    def choose_camera_path(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Camera Save Folder", self.camera_path.text())
        if not path:
            return
        self.camera_path.setText(path)
        self.settings.setValue("camera/output_dir", path)
        if self.camera_workspace is not None:
            self.camera_workspace.set_output_dir(path)
