import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from core.app_paths import resource_path, storage_dir
from core.theme_manager import ThemeManager
from gui.main_window import MainWindow


def main() -> int:
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    storage_dir("data")
    storage_dir("camera_recordings")
    app = QApplication(sys.argv)
    icon = QIcon(str(resource_path("assets/uoslabmanager_icon.png")))
    if not icon.isNull():
        app.setWindowIcon(icon)
    theme_manager = ThemeManager(app)
    theme_manager.apply()
    window = MainWindow(theme_manager)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
