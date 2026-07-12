from PyQt6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget


class SettingsPanel(QWidget):
    def __init__(self, theme_manager, theme_changed=None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.theme_changed = theme_changed
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
        layout.addStretch()

    def change_theme(self, display_name):
        theme = self.theme_manager.THEMES[display_name]
        self.theme_manager.apply(theme)
        if self.theme_changed:
            self.theme_changed(theme)
