"""Background, non-blocking wrapper around core.update_check -- network
calls must never run on the UI thread, mirroring every other network
operation in this app (translation, novel search/download all use a
QThread the same way).
"""
from PyQt6.QtCore import QThread, pyqtSignal

from ..core.update_check import get_latest_release


class UpdateCheckWorker(QThread):
    release_found = pyqtSignal(dict)  # {'version', 'url'}

    def run(self):
        try:
            release = get_latest_release()
        except Exception:
            # A failed check (no internet, GitHub rate limit, repo
            # renamed...) should be invisible to the user -- there is
            # nothing actionable for them to do about it, so this stays
            # silent instead of emitting anything.
            return
        self.release_found.emit(release)
