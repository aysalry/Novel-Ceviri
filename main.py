import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from app.core.config import get_config
from app.core.logging_setup import setup_logging
from app.gui.main_window import MainWindow
from app.gui.theme import apply_theme
from app.gui.welcome_dialog import WelcomeDialog

RESOURCES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'app', 'gui', 'resources')
ICON_PATH = os.path.join(RESOURCES_DIR, 'icon.ico')


def main():
    setup_logging()
    # Must be set before QApplication is constructed -- the built-in EPUB
    # reader uses QWebEngineView, which shares a GL context with the rest
    # of the app for hardware-accelerated rendering; Qt can only apply this
    # attribute pre-construction, and it's a no-op if the reader is never
    # opened, so it's set unconditionally here rather than deferred.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName('Novel Çeviri')
    # When background new-chapter checking is on, closing the window hides
    # it to the tray instead of quitting -- don't let Qt's default "quit
    # when the last window closes" race against that.
    app.setQuitOnLastWindowClosed(False)
    # The native Windows style only partially honors QSS (borders/radius on
    # QComboBox, QPushButton, etc. get silently ignored) -- Fusion is a
    # purely Qt-drawn style that respects the stylesheet fully.
    app.setStyle('Fusion')
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))
    apply_theme(app, get_config().get('ui_theme', 'light'))

    if not get_config().get('first_run_completed'):
        WelcomeDialog().exec()

    window = MainWindow()
    window.resize(1080, 720)
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
