import qdarktheme
from PyQt6.QtCore import QSettings


ADDITIONAL_QSS = """
QToolBar { spacing: 6px; padding: 6px; }
QTabBar::tab { min-width: 110px; padding: 8px 14px; }
QGroupBox { font-weight: 600; }
"""


class ThemeManager:
    THEMES = {"Dark": "dark", "Light": "light"}

    def __init__(self, app):
        self.app = app
        self.settings = QSettings("UOSLab", "UOSLabManager")
        self.current_theme = self.settings.value("appearance/theme", "dark")

    def apply(self, theme=None):
        theme = theme or self.current_theme
        if theme not in self.THEMES.values():
            theme = "dark"
        self.current_theme = theme
        if hasattr(qdarktheme, "setup_theme"):
            options = {"theme": theme, "corner_shape": "rounded", "additional_qss": ADDITIONAL_QSS}
            if theme == "dark":
                options["custom_colors"] = {"primary": "#4da3ff"}
            qdarktheme.setup_theme(**options)
        else:
            self.app.setPalette(qdarktheme.load_palette(theme))
            self.app.setStyleSheet(qdarktheme.load_stylesheet(theme) + ADDITIONAL_QSS)
        self.settings.setValue("appearance/theme", theme)

    def display_name(self):
        return next((name for name, value in self.THEMES.items() if value == self.current_theme), "Dark")
