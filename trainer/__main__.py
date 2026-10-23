"""Start the trainer with:  python -m trainer"""

import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow
from .progress import Progress
from .settings import Settings


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Chess Opening Trainer")
    window = MainWindow(Settings.load(), Progress.load())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
