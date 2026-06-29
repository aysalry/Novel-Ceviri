"""'Kütüphanem' tab: shows every file translated_library has recorded as
a grid of cover thumbnails (reopen in the built-in reader, reveal in
Explorer, drop from the registry, drag straight to the desktop), plus a
second grid of webnovels the user is tracking for new chapters.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidgetItem, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget)

from ..core import reading_progress, translated_library
from ..core.i18n import _
from ..webnovel import library
from .cover_grid import build_cover_icon, build_cover_list_widget
from .epub_reader import open_preview
from .webnovel_worker import LibraryUpdateWorker


class LibraryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Keeps non-modal EpubReaderWindow instances alive -- Qt garbage
        # collects a parentless top-level widget the moment nothing in
        # Python still references it.
        self._open_readers = []
        # path/url -> QIcon, so re-translating/finishing another book
        # doesn't re-open and re-decode every other book's EPUB just to
        # redraw the grid -- covers don't change once recorded. Reading
        # progress is looked up fresh at paint time instead, so it never
        # goes stale because of this cache.
        self._cover_cache = {}
        self._tracked_cover_cache = {}
        self.library_update_worker = None

        layout = QVBoxLayout(self)

        # A splitter (instead of two fixed-height blocks stacked in one
        # QVBoxLayout) so the two sections always split the available
        # height evenly and grow/shrink together as the window is
        # resized -- a plain stacked layout would let the top section
        # claim all the extra space and leave the bottom one pinned at
        # whatever fixed height it started with.
        splitter = QSplitter(Qt.Orientation.Vertical)

        books_widget = QWidget()
        books_layout = QVBoxLayout(books_widget)
        books_layout.setContentsMargins(0, 0, 0, 0)
        books_layout.addWidget(QLabel(_('Çevirdiğim Kitaplar:')))

        self.list_widget = build_cover_list_widget(
            draggable=True,
            progress_lookup=reading_progress.get_progress_fraction)
        self.list_widget.itemSelectionChanged.connect(self._update_buttons)
        self.list_widget.itemDoubleClicked.connect(self._read_selected)
        books_layout.addWidget(self.list_widget, stretch=1)

        button_row = QHBoxLayout()
        self.read_btn = QPushButton(_('Oku'))
        self.read_btn.setObjectName('primaryButton')
        self.read_btn.setEnabled(False)
        self.read_btn.clicked.connect(self._read_selected)
        button_row.addWidget(self.read_btn)

        self.show_btn = QPushButton(_('Klasörde Göster'))
        self.show_btn.setEnabled(False)
        self.show_btn.clicked.connect(self._show_in_folder)
        button_row.addWidget(self.show_btn)

        self.remove_btn = QPushButton(_('Kütüphaneden Kaldır'))
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self._remove_selected)
        button_row.addWidget(self.remove_btn)

        button_row.addStretch()
        refresh_btn = QPushButton(_('Yenile'))
        refresh_btn.clicked.connect(self.refresh)
        button_row.addWidget(refresh_btn)
        books_layout.addLayout(button_row)
        splitter.addWidget(books_widget)

        tracked_widget = QWidget()
        tracked_layout = QVBoxLayout(tracked_widget)
        tracked_layout.setContentsMargins(0, 0, 0, 0)

        tracked_header_row = QHBoxLayout()
        tracked_header_row.addWidget(QLabel(_('Takip Ettiğim Romanlar:')))
        tracked_header_row.addStretch()
        self.update_all_btn = QPushButton(_('Tümünü Güncelle'))
        self.update_all_btn.clicked.connect(self._update_all_tracked)
        tracked_header_row.addWidget(self.update_all_btn)
        tracked_layout.addLayout(tracked_header_row)

        self.tracked_list = build_cover_list_widget()
        self.tracked_list.itemSelectionChanged.connect(
            self._update_tracked_buttons)
        tracked_layout.addWidget(self.tracked_list, stretch=1)

        self.tracked_status_label = QLabel('')
        self.tracked_status_label.setObjectName('hintLabel')
        tracked_layout.addWidget(self.tracked_status_label)

        tracked_button_row = QHBoxLayout()
        self.update_selected_btn = QPushButton(_('Seçileni Güncelle'))
        self.update_selected_btn.setEnabled(False)
        self.update_selected_btn.clicked.connect(
            self._update_selected_tracked)
        tracked_button_row.addWidget(self.update_selected_btn)
        self.remove_tracked_btn = QPushButton(_('Listeden Kaldır'))
        self.remove_tracked_btn.setEnabled(False)
        self.remove_tracked_btn.clicked.connect(self._remove_tracked_novel)
        tracked_button_row.addWidget(self.remove_tracked_btn)
        tracked_button_row.addStretch()
        tracked_layout.addLayout(tracked_button_row)
        splitter.addWidget(tracked_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self.refresh()
        self._refresh_tracked_list()

    # -- translated-books grid ------------------------------------------

    def refresh(self):
        self.list_widget.clear()
        entries = translated_library.get_all()
        for path, info in sorted(
                entries.items(),
                key=lambda kv: kv[1].get('translated_at', ''), reverse=True):
            title = info.get('title') or os.path.basename(path)
            item = QListWidgetItem(title)
            item.setIcon(build_cover_icon(
                path, title, path, self._cover_cache, widget=self))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(self._tooltip_for(path))
            self.list_widget.addItem(item)
        self._update_buttons()

    def _tooltip_for(self, path):
        fraction = reading_progress.get_progress_fraction(path)
        if fraction is None:
            return path
        return '%s\n%s: %%%d' % (
            path, _('Okuma ilerlemesi'), round(fraction * 100))

    def _update_buttons(self):
        has_selection = self.list_widget.currentItem() is not None
        self.read_btn.setEnabled(has_selection)
        self.show_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _selected_path(self):
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _warn_missing(self, path):
        QMessageBox.warning(
            self, _('Dosya bulunamadı'),
            _('Bu dosya artık diskte yok, kütüphaneden kaldırılıyor:\n{}')
            .format(path))
        self._cover_cache.pop(path, None)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        # The reader is a separate, non-modal window -- reading progress
        # made there since this tab was last shown wouldn't otherwise be
        # reflected until something else happened to call refresh().
        self.refresh()
        # A webnovel just downloaded from Web'den Al gets recorded into
        # the tracking registry immediately, but without this the grid
        # only ever reflected __init__'s snapshot -- switching to this
        # tab right after a download showed an empty list until the user
        # ran a full update or restarted the app.
        self._refresh_tracked_list()

    def _read_selected(self):
        path = self._selected_path()
        if not path:
            return
        if not os.path.exists(path):
            self._warn_missing(path)
            return
        self._open_readers.append(open_preview(path, self))

    def _show_in_folder(self):
        path = self._selected_path()
        if not path:
            return
        if not os.path.exists(path):
            self._warn_missing(path)
            return
        os.startfile(os.path.dirname(path))

    def _remove_selected(self):
        path = self._selected_path()
        if not path:
            return
        answer = QMessageBox.question(
            self, _('Kütüphaneden Kaldır'),
            _('"{}" kütüphane listesinden kaldırılsın mı?\n'
              '(Dosyanın kendisi silinmeyecek.)')
            .format(os.path.basename(path)))
        if answer == QMessageBox.StandardButton.Yes:
            translated_library.remove(path)
            self._cover_cache.pop(path, None)
            self.refresh()

    # -- tracked-webnovels grid -------------------------------------------

    def _refresh_tracked_list(self):
        self.tracked_list.clear()
        for url, entry in library.get_all().items():
            title = entry.get('title', url)
            output_path = entry.get('output_path')
            item = QListWidgetItem(
                '%s (%s bölüm)' % (title, entry.get('chapter_count', 0)))
            item.setIcon(build_cover_icon(
                url, title, output_path, self._tracked_cover_cache,
                widget=self))
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.tracked_list.addItem(item)
        self._update_tracked_buttons()

    def _update_tracked_buttons(self):
        self.remove_tracked_btn.setEnabled(
            self.tracked_list.currentItem() is not None)

    def _remove_tracked_novel(self):
        item = self.tracked_list.currentItem()
        if item is None:
            return
        url = item.data(Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self, _('Listeden Kaldır'),
            _('"{}" takip listesinden kaldırılsın mı?\n'
              '(İndirilen EPUB silinmeyecek, sadece güncelleme takibi '
              'durur.)').format(item.text()))
        if answer == QMessageBox.StandardButton.Yes:
            library.remove(url)
            self._tracked_cover_cache.pop(url, None)
            self._refresh_tracked_list()

    def _update_all_tracked(self):
        if not library.get_all():
            return
        self._start_tracked_update(urls=None)

    def _update_selected_tracked(self):
        item = self.tracked_list.currentItem()
        if item is None:
            QMessageBox.information(
                self, _('Seçim Yok'), _('Önce listeden bir roman seç.'))
            return
        self._start_tracked_update(urls=[item.data(Qt.ItemDataRole.UserRole)])

    def _start_tracked_update(self, urls):
        if (self.library_update_worker is not None
                and self.library_update_worker.isRunning()):
            return
        self.update_all_btn.setEnabled(False)
        self.update_selected_btn.setEnabled(False)
        self.tracked_status_label.setText(_('Güncelleme kontrol ediliyor...'))

        self.library_update_worker = LibraryUpdateWorker(urls)
        self.library_update_worker.novel_started.connect(
            lambda url, title: self.tracked_status_label.setText(
                _('Kontrol ediliyor: {}').format(title)))
        self.library_update_worker.novel_progress.connect(
            lambda url, fraction, message: (
                self.tracked_status_label.setText(message)))
        self.library_update_worker.novel_finished.connect(
            self._on_tracked_novel_finished)
        self.library_update_worker.queue_finished.connect(
            self._on_tracked_update_finished)
        self.library_update_worker.start()

    def _on_tracked_novel_finished(self, url, status, message):
        if status == 'error':
            QMessageBox.warning(
                self, _('Güncelleme Hatası'), '%s: %s' % (url, message))

    def _on_tracked_update_finished(self):
        self.update_all_btn.setEnabled(True)
        self.update_selected_btn.setEnabled(True)
        if self.library_update_worker is not None:
            # run() may not have fully unwound yet when this slot fires
            # from queue_finished -- wait before dropping the reference.
            self.library_update_worker.wait()
        self.library_update_worker = None
        self._refresh_tracked_list()
        self.tracked_status_label.setText(_('Güncelleme tamamlandı.'))
