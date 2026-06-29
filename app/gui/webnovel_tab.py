import os
import sys

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
    QProgressDialog, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout,
    QWidget)

from ..core.config import get_config
from ..core.i18n import _
from ..webnovel import library
from .cover_grid import (
    ResponsiveCoverLabel, build_cover_list_widget, build_placeholder_icon,
    icon_from_cover_bytes)
from .epub_reader import open_preview
from .notifications import notify
from .webnovel_worker import (
    NovelDownloadWorker, NovelInfoWorker, NovelSearchWorker,
    SearchCoverFetchWorker)


def _desktop_path():
    """The real Desktop path, which os.path.expanduser('~/Desktop') gets
    wrong whenever it's OneDrive-redirected or the OS isn't English (e.g.
    Turkish Windows calls it "Masaüstü"). Ask Windows directly; fall back
    to the home directory everywhere else / if the lookup fails.
    """
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes

            FOLDERID_Desktop = ctypes.create_unicode_buffer(
                '{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}')
            guid = ctypes.create_string_buffer(16)
            ctypes.windll.ole32.CLSIDFromString(FOLDERID_Desktop, guid)
            path_ptr = ctypes.c_wchar_p()
            result = ctypes.windll.shell32.SHGetKnownFolderPath(
                guid, 0, None, ctypes.byref(path_ptr))
            if result == 0 and path_ptr.value:
                return path_ptr.value
        except Exception:
            pass
    return os.path.expanduser('~')


class WebNovelTab(QWidget):
    """Paste a novel's URL, fetch its chapter list, pick a range, and
    download it straight into a fresh EPUB -- optionally queued for
    translation right after. Tracking/updating already-downloaded
    novels for new chapters lives in the Kütüphanem tab instead, so this
    one stays focused on "get a new novel".
    """

    epub_ready = pyqtSignal(str)  # emits the output path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = None
        self.novel_info = None
        self.info_worker = None
        self.download_worker = None
        self.search_worker = None
        self.search_cover_worker = None
        self._search_results = []
        self._library_old_count = 0
        self._info_progress_dialog = None
        self._last_output_path = None
        # True until the user types or browses to a path themselves --
        # lets _on_info_loaded() keep the save path in sync with whichever
        # novel is currently loaded instead of silently reusing the first
        # novel's filename (and output_path) for every later download.
        self._output_path_is_auto = True
        # Keeps non-modal EpubReaderWindow instances alive (see
        # epub_reader.open_preview) -- Qt garbage collects a parentless
        # top-level widget the moment nothing in Python still references it.
        self._open_readers = []

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # URL and name-search used to each get their own full-width row,
        # which made the URL field look like it owned the whole tab --
        # side by side with an equal 1:1 stretch instead, so neither
        # input method visually dominates the other.
        finder_row = QHBoxLayout()

        url_col = QHBoxLayout()
        url_col.addWidget(QLabel(_('Roman adresi (URL):')))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText('https://novelfire.net/book/...')
        self.url_edit.returnPressed.connect(self.fetch_info)
        url_col.addWidget(self.url_edit, stretch=1)
        self.fetch_btn = QPushButton(_('Bilgileri Getir'))
        self.fetch_btn.setObjectName('primaryButton')
        self.fetch_btn.clicked.connect(self.fetch_info)
        url_col.addWidget(self.fetch_btn)
        finder_row.addLayout(url_col, stretch=1)

        finder_row.addSpacing(20)

        search_col = QHBoxLayout()
        search_col.addWidget(QLabel(_('Veya isimle ara:')))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_('Roman adı...'))
        self.search_edit.returnPressed.connect(self.search_novels)
        search_col.addWidget(self.search_edit, stretch=1)
        self.search_btn = QPushButton(_('Ara'))
        self.search_btn.clicked.connect(self.search_novels)
        search_col.addWidget(self.search_btn)
        finder_row.addLayout(search_col, stretch=1)

        layout.addLayout(finder_row)

        hint = QLabel(_(
            'Desteklenen siteler: novelfire.net, novelight.net, '
            'novelbuddy.com ve "Madara" temalı birçok roman sitesi. Diğer '
            'siteler için destek eklenebilir.'))
        hint.setObjectName('hintLabel')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # "Searching...", "no results", and error text live in this
        # label instead of as fake entries inside the grid -- a text-only
        # row with no cover would otherwise paint as an odd, mostly-empty
        # thumbnail next to the real results.
        self.search_status_label = QLabel('')
        self.search_status_label.setObjectName('hintLabel')
        self.search_status_label.setVisible(False)
        layout.addWidget(self.search_status_label)

        # The search-results grid and the single-novel preview used to
        # be two separate, sequential blocks -- whichever one was
        # hidden still left the *other* sitting wherever it was in the
        # stack, so there was always an empty gap somewhere. A
        # QStackedWidget instead: one shared, generously-sized area that
        # shows whichever is relevant right now (search results until
        # you pick one, then the picked novel's preview takes over the
        # exact same spot), with stretch=1 so it actually uses the
        # leftover space instead of staying pinned small.
        self.results_stack = QStackedWidget()

        # A cover-thumbnail grid, same look as Kütüphanem -- results show
        # immediately with a generated placeholder, then get their real
        # cover filled in as SearchCoverFetchWorker downloads each one.
        self.search_results_list = build_cover_list_widget()
        self.search_results_list.itemDoubleClicked.connect(
            self._use_search_result)
        self.results_stack.addWidget(self.search_results_list)

        self.info_container = QWidget()
        info_row = QHBoxLayout(self.info_container)
        info_row.setContentsMargins(0, 0, 0, 0)
        self.cover_label = ResponsiveCoverLabel(max_size=QSize(320, 460))
        self.cover_label.setObjectName('coverPlaceholder')
        # stretch=1 (same as the text column) so the cover's box can
        # actually claim extra horizontal room as the window grows --
        # with stretch=0 it stayed pinned to its sizeHint width while
        # all the growth went to the text beside it, so the cover image
        # itself never got any bigger no matter how wide the window was.
        info_row.addWidget(self.cover_label, stretch=1)

        info_col = QVBoxLayout()
        self.title_label = QLabel('')
        self.title_label.setObjectName('aboutTitle')
        self.author_label = QLabel('')
        self.author_label.setObjectName('hintLabel')
        self.genres_label = QLabel('')
        self.genres_label.setObjectName('hintLabel')
        self.genres_label.setWordWrap(True)
        self.status_label = QLabel('')
        info_col.addWidget(self.title_label)
        info_col.addWidget(self.author_label)
        info_col.addWidget(self.genres_label)
        info_col.addWidget(self.status_label)
        info_col.addStretch()
        info_row.addLayout(info_col, stretch=1)
        info_row.setAlignment(info_col, Qt.AlignmentFlag.AlignTop)
        self.results_stack.addWidget(self.info_container)

        layout.addWidget(self.results_stack, stretch=1)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel(_('Bölüm aralığı:')))
        self.start_spin = QSpinBox()
        self.start_spin.setMinimum(1)
        range_row.addWidget(self.start_spin)
        range_row.addWidget(QLabel('-'))
        self.end_spin = QSpinBox()
        self.end_spin.setMinimum(1)
        range_row.addWidget(self.end_spin)
        select_all_btn = QPushButton(_('Tümünü Seç'))
        select_all_btn.clicked.connect(self._select_all_range)
        range_row.addWidget(select_all_btn)
        self.new_chapters_btn = QPushButton('')
        self.new_chapters_btn.setObjectName('primaryButton')
        self.new_chapters_btn.setVisible(False)
        self.new_chapters_btn.clicked.connect(self._select_new_chapters_range)
        range_row.addWidget(self.new_chapters_btn)
        range_row.addStretch()
        layout.addLayout(range_row)

        # No max-height cap, and equal stretch with results_stack -- this
        # used to be pinned to a tiny 140px box while a large empty gap
        # sat above it under the cover/info preview; now both areas
        # share whatever vertical room the window actually has.
        self.chapter_list = QListWidget()
        layout.addWidget(self.chapter_list, stretch=1)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(_('Kaydedilecek EPUB:')))
        self.output_path_edit = QLineEdit()
        # textEdited (not textChanged) only fires for the user's own
        # keystrokes, never our own setText() calls below -- exactly the
        # signal needed to tell "user typed a custom path" apart from
        # "this is still our auto-generated guess."
        self.output_path_edit.textEdited.connect(self._on_output_path_edited)
        out_row.addWidget(self.output_path_edit, stretch=1)
        browse_btn = QPushButton(_('Seç...'))
        browse_btn.clicked.connect(self._choose_output)
        out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        action_row = QHBoxLayout()
        self.download_btn = QPushButton(_('EPUB Oluştur'))
        self.download_btn.setObjectName('primaryButton')
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self.start_download)
        action_row.addWidget(self.download_btn)
        self.cancel_btn = QPushButton(_('İptal Et'))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_active_operation)
        action_row.addWidget(self.cancel_btn)
        self.preview_btn = QPushButton(_('Önizle'))
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self._preview_output)
        action_row.addWidget(self.preview_btn)
        self.add_to_queue_check = QCheckBox(_('Oluşunca çeviri kuyruğuna ekle'))
        self.add_to_queue_check.setChecked(True)
        action_row.addWidget(self.add_to_queue_check)
        action_row.addStretch()
        layout.addLayout(action_row)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        self.log_view.setPlaceholderText(_('İndirme kayıtları burada görünecek...'))
        layout.addWidget(self.log_view)

    # -- search -------------------------------------------------------------

    def search_novels(self):
        query = self.search_edit.text().strip()
        if not query:
            return
        if self.search_worker is not None:
            if self.search_worker.isRunning():
                return
            self.search_worker.wait()
        if (self.search_cover_worker is not None
                and self.search_cover_worker.isRunning()):
            # A previous search's cover fetches are keyed by index into
            # that search's results -- let them finish quietly rather
            # than racing to update whatever the grid now shows.
            self.search_cover_worker.cancel()
            self.search_cover_worker.wait()

        self.search_btn.setEnabled(False)
        self.search_results_list.clear()
        self.results_stack.setCurrentWidget(self.search_results_list)
        self.search_status_label.setText(_('Aranıyor...'))
        self.search_status_label.setVisible(True)

        self.search_worker = NovelSearchWorker(query)
        self.search_worker.finished_ok.connect(self._on_search_results)
        self.search_worker.start()

    def _on_search_results(self, results, errors):
        self.search_btn.setEnabled(True)
        self._search_results = results
        self.search_results_list.clear()

        for result in results:
            item = QListWidgetItem(
                '[%s] %s' % (result.source_name, result.title))
            item.setIcon(build_placeholder_icon(result.title, widget=self))
            self.search_results_list.addItem(item)

        status_parts = []
        if not results:
            status_parts.append(_('Sonuç bulunamadı.'))
        status_parts.extend(_('Hata: {}').format(e) for e in errors)
        self.search_status_label.setText('   '.join(status_parts))
        self.search_status_label.setVisible(bool(status_parts))

        if results:
            self.search_cover_worker = SearchCoverFetchWorker(results)
            self.search_cover_worker.cover_ready.connect(
                self._on_search_cover_ready)
            self.search_cover_worker.start()

    def _on_search_cover_ready(self, index, cover_bytes):
        if 0 <= index < self.search_results_list.count():
            item = self.search_results_list.item(index)
            item.setIcon(icon_from_cover_bytes(cover_bytes, widget=self))

    def _use_search_result(self, item):
        row = self.search_results_list.row(item)
        if row < 0 or row >= len(self._search_results):
            return
        result = self._search_results[row]
        self.url_edit.setText(result.url)
        self.fetch_info()

    # -- fetch info -------------------------------------------------------

    def fetch_info(self):
        url = self.url_edit.text().strip()
        if not url:
            return
        if self.info_worker is not None:
            if self.info_worker.isRunning():
                # Reassigning self.info_worker while it's still running
                # would drop the only reference to a live QThread.
                return
            self.info_worker.wait()
        self.fetch_btn.setEnabled(False)
        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.status_label.setText(_('Bilgiler alınıyor...'))
        self.chapter_list.clear()
        self.genres_label.setText('')

        # Selecting a search result (or pasting a URL) used to give zero
        # visible feedback until fetch_info() finished -- the screen just
        # sat there looking unchanged for however long the fetch took
        # (several seconds for sources with a slow, paginated chapter-list
        # walk), which reads as "this app is frozen/broken," not "this is
        # working." A modal, unmissable popup that closes itself the
        # moment the result arrives fixes that without needing the user
        # to notice the small status_label text below the chapter list.
        self._info_progress_dialog = QProgressDialog(
            _('Roman bilgileri alınıyor...'), _('İptal Et'), 0, 0, self)
        self._info_progress_dialog.setWindowTitle(_('Yükleniyor'))
        self._info_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._info_progress_dialog.setMinimumDuration(0)
        self._info_progress_dialog.canceled.connect(self.cancel_active_operation)
        self._info_progress_dialog.show()

        self.info_worker = NovelInfoWorker(url)
        self.info_worker.finished_ok.connect(self._on_info_loaded)
        self.info_worker.finished_error.connect(self._on_info_error)
        self.info_worker.list_progress.connect(self._on_info_list_progress)
        self.info_worker.start()

    def _close_info_progress_dialog(self):
        if self._info_progress_dialog is not None:
            self._info_progress_dialog.close()
            self._info_progress_dialog = None

    def _on_info_list_progress(self, current, total):
        message = _('Tam bölüm listesi alınıyor: {}/{}...').format(current, total)
        self.status_label.setText(message)
        if self._info_progress_dialog is not None:
            self._info_progress_dialog.setLabelText(message)

    def _on_info_loaded(self, source, novel_info):
        self._close_info_progress_dialog()
        self.results_stack.setCurrentWidget(self.info_container)
        self.source = source
        self.novel_info = novel_info
        self.fetch_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        self.title_label.setText(novel_info.title)
        self.author_label.setText(novel_info.author or '')
        self.genres_label.setText(
            _('Türler: {}').format(', '.join(novel_info.genres))
            if novel_info.genres else '')

        total = len(novel_info.chapters)
        locked_count = sum(1 for c in novel_info.chapters if c.locked)
        status = _('{} bölüm bulundu.').format(total)
        if locked_count:
            status += ' ' + _('({} bölüm kilitli/ücretli, atlanacak.)').format(
                locked_count)
        self.status_label.setText(status)

        self.chapter_list.clear()
        for chapter in novel_info.chapters:
            label = chapter.title
            if chapter.locked:
                label += '  ' + _('[KİLİTLİ]')
            self.chapter_list.addItem(label)

        self.start_spin.setRange(1, max(total, 1))
        self.end_spin.setRange(1, max(total, 1))
        self.start_spin.setValue(1)
        self.end_spin.setValue(total or 1)

        library_entry = library.get(novel_info.source_url)
        self._library_old_count = (
            library_entry['chapter_count'] if library_entry else 0)
        new_count = total - self._library_old_count
        if library_entry and new_count > 0:
            self.new_chapters_btn.setText(
                _('{} Yeni Bölümü Seç').format(new_count))
            self.new_chapters_btn.setVisible(True)
            self.status_label.setText(
                status + ' ' + _('({} yeni bölüm bulundu!)').format(new_count))
            # The common case after the first download is "catch up on
            # what's new", not "redo the whole novel" -- default to that.
            self.start_spin.setValue(self._library_old_count + 1)
        else:
            self.new_chapters_btn.setVisible(False)
        self.download_btn.setEnabled(total > 0)

        if self._output_path_is_auto or not self.output_path_edit.text().strip():
            safe_title = ''.join(
                c for c in novel_info.title if c.isalnum() or c in ' _-'
            ).strip() or 'novel'
            # Guessing a "Desktop" path via string substitution breaks on
            # OneDrive-redirected or localized (non-English) Windows
            # folders -- reuse the user's configured output folder if set,
            # otherwise ask Windows for the real (possibly redirected)
            # Desktop path instead of assuming one.
            config = get_config()
            output_dir = (
                config.get('output_path') if not config.get(
                    'to_source_folder', True) else None) or _desktop_path()
            filename = '%s.epub' % safe_title
            self.output_path_edit.setText(
                os.path.join(output_dir, filename) if output_dir else filename)

        if novel_info.cover_url:
            self._load_cover(novel_info.cover_url)
        else:
            self.cover_label.clear()

    def _on_info_error(self, message):
        self._close_info_progress_dialog()
        self.fetch_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_label.setText('')
        QMessageBox.warning(self, _('Hata'), message)

    def _load_cover(self, cover_url):
        try:
            cover_bytes = self.source.fetch_cover_bytes(cover_url)
            if cover_bytes:
                pixmap = QPixmap()
                pixmap.loadFromData(cover_bytes)
                self.cover_label.setCoverPixmap(pixmap)
        except Exception:
            self.cover_label.clear()

    def _select_all_range(self):
        self.start_spin.setValue(self.start_spin.minimum())
        self.end_spin.setValue(self.end_spin.maximum())

    def _select_new_chapters_range(self):
        if not self.novel_info:
            return
        total = len(self.novel_info.chapters)
        self.start_spin.setValue(min(self._library_old_count + 1, total))
        self.end_spin.setValue(total)

    def _choose_output(self):
        path, _filter = QFileDialog.getSaveFileName(
            self, _('EPUB Kaydet'), self.output_path_edit.text(),
            'EPUB (*.epub)')
        if path:
            self.output_path_edit.setText(path)
            self._output_path_is_auto = False

    def _on_output_path_edited(self, _text):
        self._output_path_is_auto = False

    def _preview_output(self):
        if self._last_output_path:
            self._open_readers.append(
                open_preview(self._last_output_path, self))

    # -- download -----------------------------------------------------------

    def start_download(self):
        if not self.novel_info or not self.source:
            return
        if self.download_worker is not None:
            if self.download_worker.isRunning():
                return
            self.download_worker.wait()
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, _('Uyarı'), _('Önce bir kayıt yolu seç.'))
            return

        start, end = self.start_spin.value(), self.end_spin.value()
        if start > end:
            start, end = end, start
        selected = [
            c for c in self.novel_info.chapters[start - 1:end] if not c.locked
        ]
        skipped_locked = (end - start + 1) - len(selected)
        if not selected:
            QMessageBox.warning(
                self, _('Uyarı'),
                _('Seçili aralıkta indirilebilir (kilitsiz) bölüm yok.'))
            return

        self.log_view.clear()
        if skipped_locked:
            self.log_view.appendPlainText(
                _('{} kilitli bölüm atlanacak.').format(skipped_locked))

        self.download_worker = NovelDownloadWorker(
            self.source, self.novel_info, selected, output_path,
            # If output_path already has a file from an earlier run, only
            # whatever sits before this run's chosen start chapter still
            # belongs in the result -- starting from 1 means "rebuild this
            # file fresh," not "tack today's chapters onto the old ones."
            keep_existing_count=start - 1)
        self.download_worker.progress.connect(self._on_progress)
        self.download_worker.log.connect(self.log_view.appendPlainText)
        self.download_worker.finished_ok.connect(self._on_download_done)
        self.download_worker.finished_error.connect(self._on_download_error)
        self.download_worker.start()

        self.download_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

    def cancel_active_operation(self):
        if self.download_worker is not None and self.download_worker.isRunning():
            self.download_worker.cancel()
        if self.info_worker is not None and self.info_worker.isRunning():
            self.info_worker.cancel()
        self.cancel_btn.setEnabled(False)

    def _on_progress(self, fraction, message):
        self.progress.setValue(int(fraction * 100))
        self.status_label.setText(message)

    def _on_download_done(self, output_path, failed_count=0):
        self._reset_download_controls()
        self.log_view.appendPlainText(_('--- Tamamlandı: {} ---').format(output_path))
        self._last_output_path = output_path
        self.preview_btn.setEnabled(True)
        title = self.novel_info.title if self.novel_info else ''
        if self.novel_info:
            # Recorded regardless of what happens below -- this is what
            # lets Kütüphanem's "Tümünü Güncelle" find this novel again
            # later, independent of whether the user adds it to their
            # reading library right now.
            library.record(
                self.novel_info.source_url, self.novel_info.title,
                len(self.novel_info.chapters), output_path)
            self.new_chapters_btn.setVisible(False)
        notify(_('EPUB hazır'), title or output_path)
        if self.add_to_queue_check.isChecked():
            # The worker already logged a "UYARI: N bölüm indirilemedi"
            # line for this same failed_count -- no extra popup needed
            # here, the file is about to go straight into the queue.
            self.epub_ready.emit(output_path)
        elif failed_count:
            QMessageBox.warning(
                self, _('Eksik Tamamlandı'),
                _('EPUB oluşturuldu, ama {} bölüm indirilemedi (ayrıntılar '
                  'kayıtlarda):\n{}').format(failed_count, output_path))
        else:
            QMessageBox.information(
                self, _('Tamamlandı'),
                _('EPUB oluşturuldu:\n{}').format(output_path))

    def _on_download_error(self, message):
        self._reset_download_controls()
        self.progress.setValue(0)
        self.log_view.appendPlainText(_('HATA: {}').format(message))
        QMessageBox.warning(self, _('Hata'), message)

    def _reset_download_controls(self):
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if self.download_worker is not None:
            # This runs from a slot connected to the worker's own
            # finished_ok/finished_error signal -- run() is about to
            # return but may not have fully unwound yet. Dropping the
            # last reference here without waiting first destroys the
            # QThread while it's still technically running.
            self.download_worker.wait()
        self.download_worker = None
