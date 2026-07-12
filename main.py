import os
import sys

from PyQt6.QtWidgets import QApplication

from core.theme_manager import ThemeManager
from gui.main_window import MainWindow


def main() -> int:
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    theme_manager = ThemeManager(app)
    theme_manager.apply()
    window = MainWindow(theme_manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
