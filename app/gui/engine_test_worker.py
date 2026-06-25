import re
from types import GeneratorType

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.i18n import _
from ..core.logging_setup import logger

TEST_TEXT = 'Hello, this is a connection test.'

# engines/base.py's Base.translate() wraps failures in an exception whose
# message is a full traceback dump glued to a raw response body (it's meant
# for the log file, see logger.exception() above) -- the line matching this
# pattern is the actual "module.ExceptionClass: reason" summary, which is
# what's worth showing in the one-line Settings dialog label. It always
# appears before any appended raw response body, so scanning from the end
# and taking the first match skips past JSON/HTML noise tacked on after it.
_EXC_LINE_RE = re.compile(r'^[\w.]+(?:Error|Exception)\b.*$')


def _short_error_summary(exc):
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    for line in reversed(lines):
        if _EXC_LINE_RE.match(line):
            return line
    return lines[0] if lines else str(exc)


class EngineTestWorker(QThread):
    """Sends one real translation request through the given engine class
    (already carrying the Settings dialog's current, possibly-unsaved
    field values via set_config) so a wrong API key or model name shows
    up immediately instead of at the start of a long queue run.
    """

    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def __init__(self, engine_class, parent=None):
        super().__init__(parent)
        self.engine_class = engine_class

    def run(self):
        try:
            translator = self.engine_class()
            translator.set_source_lang(_('Auto detect'))
            translator.set_target_lang('Turkish')
            result = translator.translate(TEST_TEXT)
            if isinstance(result, GeneratorType):
                result = ''.join(result)
            result = (result or '').strip()
        except Exception as e:
            logger.exception('Engine test failed for %s', self.engine_class.name)
            self.finished_error.emit(_short_error_summary(e))
        else:
            if result:
                self.finished_ok.emit(result)
            else:
                self.finished_error.emit(
                    _('Motor boş bir yanıt döndürdü.'))
