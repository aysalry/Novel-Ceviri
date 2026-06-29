import os

from PyQt6.QtCore import QThread, pyqtSignal

from ..conversion import translate_file
from ..core.exception import TranslationCanceled
from ..core.logging_setup import logger
from .queue_item import STATUS_CANCELED, STATUS_DONE, STATUS_ERROR


class QueueWorker(QThread):
    """Runs the whole queue, one file at a time, in a background thread.

    Pausing takes effect mid-file: core.translation.Translation polls
    pause_request at the top of every paragraph (see translate_paragraph),
    so each of the engine's concurrency_limit workers stops before picking
    up its next paragraph instead of waiting for the whole file to finish.
    Canceling is instant and safe the same way, via cancel_request.
    """

    item_started = pyqtSignal(int)
    item_progress = pyqtSignal(int, float, str)
    item_log = pyqtSignal(int, str, bool)
    item_finished = pyqtSignal(int, str, str)  # row, status, message
    queue_finished = pyqtSignal()

    def __init__(self, items, output_dir_resolver, parent=None):
        super().__init__(parent)
        self.items = items
        self.output_dir_resolver = output_dir_resolver
        self._cancelled = False
        self._paused = False

    def cancel(self):
        self._cancelled = True

    @property
    def was_cancelled(self):
        return self._cancelled

    def set_paused(self, paused):
        self._paused = paused

    def run(self):
        for row, item in enumerate(self.items):
            if self._cancelled:
                break
            while self._paused and not self._cancelled:
                self.msleep(200)
            if self._cancelled:
                break

            self.item_started.emit(row)
            output_dir = self.output_dir_resolver(item)
            os.makedirs(output_dir, exist_ok=True)
            filename = '%s [%s].%s' % (
                item.title, item.target_lang, item.input_format)
            output_path = os.path.join(output_dir, filename)

            try:
                translate_file(
                    item.input_format, item.path, output_path,
                    source_lang=item.source_lang,
                    target_lang=item.target_lang,
                    title=item.title,
                    progress=lambda frac, msg, r=row: (
                        self.item_progress.emit(r, frac, msg)),
                    log=lambda msg, is_error=False, r=row: (
                        self.item_log.emit(r, msg, is_error)),
                    cancel_request=lambda: self._cancelled,
                    pause_request=lambda: self._paused)
            except TranslationCanceled:
                self.item_finished.emit(row, STATUS_CANCELED, '')
                break
            except Exception as e:
                logger.exception('Translation failed for %s', item.path)
                self.item_finished.emit(row, STATUS_ERROR, str(e))
                continue
            else:
                # Whether this goes into Kütüphanem is the GUI's call, not
                # the worker's -- _on_item_finished prompts for it, mirroring
                # the same "kütüphaneye eklensin mi?" question Web'den Al
                # asks after a download, instead of silently adding every
                # translation (a one-off test run included) to the library.
                self.item_finished.emit(row, STATUS_DONE, output_path)

        self.queue_finished.emit()
