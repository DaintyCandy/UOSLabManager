from PyQt6.QtCore import QSettings, QTimer
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .widget_busy_spinner import BusySpinnerDialog
from core import storage_dir
from core.app_paths import resource_path


class SettingsPanel(QWidget):
    def __init__(self, theme_manager, theme_changed=None, parent=None, camera_workspace=None,
                 *, layout_preference="landscape", layout_changed=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.theme_changed = theme_changed
        self.layout_changed = layout_changed
        self.camera_workspace = camera_workspace
        self.settings = QSettings("UOSLabManager", "UOSLabManager")
        self.theme_spinner = None
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        general = QWidget()
        layout = QVBoxLayout(general)
        appearance = QGroupBox("Appearance")
        form = QFormLayout(appearance)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(theme_manager.THEMES.keys())
        self.theme_combo.setCurrentText(theme_manager.display_name())
        self.theme_combo.currentTextChanged.connect(self.change_theme)
        form.addRow("Theme", self.theme_combo)
        self.layout_mode_combo = QComboBox()
        for label, value in (("가로", "landscape"), ("세로", "portrait")):
            self.layout_mode_combo.addItem(label, value)
        self.sync_layout_preference(layout_preference)
        self.layout_mode_combo.currentIndexChanged.connect(self.change_layout)
        form.addRow("화면 배치", self.layout_mode_combo)
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
        default_data_path = str(storage_dir("data"))
        self.data_path = QLineEdit(self.settings.value("data/output_dir", default_data_path))
        self.data_path.setReadOnly(True)
        data_path_row.addWidget(self.data_path)
        choose_data_path = QPushButton("Choose")
        choose_data_path.clicked.connect(self.choose_data_path)
        data_path_row.addWidget(choose_data_path)
        data_form.addRow("CSV Save Path", data_path_row)
        layout.addWidget(data)
        layout.addStretch()
        general_scroll = QScrollArea()
        general_scroll.setWidgetResizable(True)
        general_scroll.setWidget(general)
        self.tabs.addTab(general_scroll, "일반")
        self.tabs.addTab(self._build_information(), "정보 및 라이선스")

    def sync_layout_preference(self, preference):
        blocked = self.layout_mode_combo.blockSignals(True)
        index = self.layout_mode_combo.findData(preference)
        self.layout_mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.layout_mode_combo.blockSignals(blocked)

    def change_layout(self, _index):
        preference = self.layout_mode_combo.currentData()
        if self.layout_changed is not None:
            self.layout_changed(preference)
        else:
            self.settings.setValue("appearance/layout_mode", preference)

    def _build_information(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.about_view = QTextBrowser()
        self.about_view.setOpenExternalLinks(True)
        self.about_view.setHtml(
            "<h3>UOSLabManager</h3>"
            "<p>Copyright &copy; 2026 UOSLabManager contributors.</p>"
            "<p>Free software licensed under <b>GNU GPL version 3 or later</b>.</p>"
            "<p>This program comes with absolutely no warranty. "
            "See the license and third-party notices below for details.</p>"
            "<p>Independent interoperability project; not affiliated with "
            "or endorsed by equipment manufacturers.</p>"
            '<p>Source: <a href="https://github.com/DaintyCandy/UOSLabManager">'
            "github.com/DaintyCandy/UOSLabManager</a></p>"
        )
        layout.addWidget(self.about_view, 1)
        self.license_tabs = QTabWidget()
        for name, title in (("LICENSE", "License"),
                            ("THIRD_PARTY_NOTICES.md", "Third-party notices")):
            viewer = QTextBrowser()
            try:
                contents = resource_path(name).read_text(encoding="utf-8")
            except OSError as error:
                contents = f"Could not load {name}: {error}"
            viewer.setPlainText(contents)
            self.license_tabs.addTab(viewer, title)
        layout.addWidget(self.license_tabs, 2)
        return panel

    def change_theme(self, display_name):
        if self.theme_spinner is not None:
            return
        self.pending_theme_name = display_name
        self.theme_combo.setEnabled(False)
        self.theme_spinner = BusySpinnerDialog(self)
        self.theme_spinner.show_after()
        QTimer.singleShot(0, self.apply_pending_theme)

    def apply_pending_theme(self):
        try:
            theme = self.theme_manager.THEMES[self.pending_theme_name]
            self.theme_manager.apply(theme)
            if self.theme_changed:
                self.theme_changed(theme)
        finally:
            if self.theme_spinner is not None:
                dialog = self.theme_spinner

                def loading_finished():
                    if self.theme_spinner is dialog:
                        self.theme_spinner = None
                    self.theme_combo.setEnabled(True)

                dialog.finish(loading_finished)
            else:
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
