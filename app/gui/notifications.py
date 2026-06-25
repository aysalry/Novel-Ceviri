import os

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

_tray_icon: QSystemTrayIcon | None = None


def get_tray_icon() -> QSystemTrayIcon:
    """The one shared tray icon -- used both for transient notify()
    popups and, by MainWindow, as the persistent "minimized to tray"
    presence with its own context menu. One shared icon avoids showing
    two unrelated tray icons for what is, to the user, a single app.
    """
    return _get_tray_icon()


def _get_tray_icon() -> QSystemTrayIcon:
    global _tray_icon
    if _tray_icon is None:
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'resources', 'icon.ico')
        app = QApplication.instance()
        icon = QIcon(icon_path) if os.path.exists(icon_path) else (
            app.windowIcon() if isinstance(app, QApplication) else QIcon())
        # Parented to the QApplication so it survives as long as the app
        # does, rather than getting garbage-collected after this call.
        _tray_icon = QSystemTrayIcon(icon, app if isinstance(app, QObject) else None)
    return _tray_icon


def notify(title: str, message: str) -> None:
    """Best-effort desktop notification -- silently does nothing on
    systems without a tray (some Linux setups), since this is a
    convenience, not something correctness depends on.
    """
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return
    tray = _get_tray_icon()
    tray.show()
    tray.showMessage(
        title, message, QSystemTrayIcon.MessageIcon.Information, 6000)
