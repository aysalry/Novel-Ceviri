import os
import sys

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QVBoxLayout, QWidget)

from ..core.config import get_config
from ..core.i18n import _
from ..webnovel import library
from .notifications import notify
from .preview_dialog import PreviewDialog
from .webnovel_worker import NovelDownloadWorker, NovelInfoWorker, NovelSearchWorker


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
    translation right after.
    """

    epub_ready = pyqtSignal(str)  # emits the output path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = None
        self.novel_info = None
        self.info_worker = None
        self.download_worker = None
        self.search_worker = None
        self._search_results = []
        self._library_old_count = 0
        self._last_output_path = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel(_('Roman adresi (URL):')))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText('https://novelfire.net/book/...')
        self.url_edit.returnPressed.connect(self.fetch_info)
        url_row.addWidget(self.url_edit, stretch=1)
        self.fetch_btn = QPushButton(_('Bilgileri Getir'))
        self.fetch_btn.setObjectName('primaryButton')
        self.fetch_btn.clicked.connect(self.fetch_info)
        url_row.addWidget(self.fetch_btn)
        layout.addLayout(url_row)

        hint = QLabel(_(
            'Desteklenen siteler: novelfire.net, novelight.net, '
            'novelbuddy.com ve "Madara" temalı birçok roman sitesi. Diğer '
            'siteler için destek eklenebilir.'))
        hint.setObjectName('hintLabel')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(_('Veya isimle ara:')))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_('Roman adı...'))
        self.search_edit.returnPressed.connect(self.search_novels)
        search_row.addWidget(self.search_edit, stretch=1)
        self.search_btn = QPushButton(_('Ara'))
        self.search_btn.clicked.connect(self.search_novels)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        self.search_results_list = QListWidget()
        self.search_results_list.setMaximumHeight(140)
        self.search_results_list.setVisible(False)
        self.search_results_list.itemDoubleClicked.connect(
            self._use_search_result)
        layout.addWidget(self.search_results_list)

        info_row = QHBoxLayout()
        self.cover_label = QLabel()
        self.cover_label.setObjectName('coverPlaceholder')
        self.cover_label.setFixedSize(86, 124)
        self.cover_label.setScaledContents(True)
        info_row.addWidget(self.cover_label)

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
        layout.addLayout(info_row)

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

        self.chapter_list = QListWidget()
        self.chapter_list.setMaximumHeight(140)
        layout.addWidget(self.chapter_list)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(_('Kaydedilecek EPUB:')))
        self.output_path_edit = QLineEdit()
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
        self.search_btn.setEnabled(False)
        self.search_results_list.clear()
        self.search_results_list.setVisible(True)
        self.search_results_list.addItem(_('Aranıyor...'))

        self.search_worker = NovelSearchWorker(query)
        self.search_worker.finished_ok.connect(self._on_search_results)
        self.search_worker.start()

    def _on_search_results(self, results, errors):
        self.search_btn.setEnabled(True)
        self._search_results = results
        self.search_results_list.clear()

        if not results:
            self.search_results_list.addItem(_('Sonuç bulunamadı.'))
        for result in results:
            self.search_results_list.addItem(
                '[%s] %s' % (result.source_name, result.title))
        for error in errors:
            self.search_results_list.addItem(_('Hata: {}').format(error))

        if results:
            self.search_results_list.addItem(
                _('(seçmek için çift tıkla)'))

    def _use_search_result(self, item):
        row = self.search_results_list.row(item)
        if row < 0 or row >= len(self._search_results):
            return
        result = self._search_results[row]
        self.url_edit.setText(result.url)
        self.search_results_list.setVisible(False)
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

        self.info_worker = NovelInfoWorker(url)
        self.info_worker.finished_ok.connect(self._on_info_loaded)
        self.info_worker.finished_error.connect(self._on_info_error)
        self.info_worker.list_progress.connect(self._on_info_list_progress)
        self.info_worker.start()

    def _on_info_list_progress(self, current, total):
        self.status_label.setText(
            _('Tam bölüm listesi alınıyor: {}/{}...').format(current, total))

    def _on_info_loaded(self, source, novel_info):
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

        if not self.output_path_edit.text().strip():
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
                self.cover_label.setPixmap(pixmap)
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

    def _preview_output(self):
        if self._last_output_path:
            PreviewDialog(self._last_output_path, self).exec()

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
            self.source, self.novel_info, selected, output_path)
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

    def _on_download_done(self, output_path):
        self._reset_download_controls()
        self.log_view.appendPlainText(_('--- Tamamlandı: {} ---').format(output_path))
        self._last_output_path = output_path
        self.preview_btn.setEnabled(True)
        if self.novel_info:
            library.record(
                self.novel_info.source_url, self.novel_info.title,
                len(self.novel_info.chapters), output_path)
            self.new_chapters_btn.setVisible(False)
        title = self.novel_info.title if self.novel_info else ''
        notify(_('EPUB hazır'), title or output_path)
        if self.add_to_queue_check.isChecked():
            self.epub_ready.emit(output_path)
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
