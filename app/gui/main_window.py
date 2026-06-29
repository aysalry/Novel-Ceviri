import os
import time
import webbrowser

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter,
    QSystemTrayIcon, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget)

from ..core import translated_library
from ..core.config import get_config
from ..core.glossary_extract import (
    count_characters, extract_terms, merge_extracted_terms)
from ..core.i18n import _
from ..core.update_check import is_update_available
from ..core.version import APP_VERSION
from ..engines import get_all_engines
from ..webnovel import library
from .about_dialog import AboutDialog
from .epub_reader import open_preview
from .glossary_dialog import GlossaryDialog
from .library_tab import LibraryTab
from .notifications import get_tray_icon, notify
from .queue_item import QueueItem, SUPPORTED_EXTENSIONS, STATUS_DONE
from .settings_dialog import SettingsDialog
from .splitter_dialog import SplitterDialog
from .update_check_worker import UpdateCheckWorker
from .webnovel_tab import WebNovelTab
from .webnovel_worker import LibraryCheckWorker
from .worker import QueueWorker

STATUS_LABELS = {
    'waiting': 'Bekliyor',
    'running': 'Çevriliyor...',
    'done': 'Tamamlandı',
    'error': 'Hata',
    'canceled': 'İptal edildi',
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_('Novel Çeviri'))
        self.setAcceptDrops(True)
        self.setMinimumSize(880, 640)

        self.queue_items: list[QueueItem] = []
        self.worker: QueueWorker | None = None
        self.library_check_worker: LibraryCheckWorker | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self._intentional_quit = False
        # Keeps non-modal EpubReaderWindow instances alive (see
        # epub_reader.open_preview) -- Qt garbage collects a parentless
        # top-level widget the moment nothing in Python still references it.
        self._open_readers = []

        self.library_check_timer = QTimer(self)
        self.library_check_timer.timeout.connect(self.run_library_check)

        self._build_menu_bar()
        self._build_ui()
        self._refresh_lang_combos()
        self._setup_tray_icon()
        self.apply_webnovel_check_settings()
        QTimer.singleShot(30_000, self.check_for_updates)

    def _active_background_threads(self):
        webnovel_workers = (
            self.webnovel_tab.info_worker, self.webnovel_tab.download_worker,
            self.webnovel_tab.search_worker,
            self.library_tab.library_update_worker)
        return [
            thread for thread in (self.worker, *webnovel_workers)
            if thread is not None and thread.isRunning()]

    def closeEvent(self, event):
        active = self._active_background_threads()
        if active:
            answer = QMessageBox.question(
                self, _('Çıkış'),
                _('Devam eden bir işlem var (çeviri/indirme/arama). '
                  'Şimdi çıkmak istediğine emin misin?'))
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for thread in active:
                if hasattr(thread, 'cancel'):
                    thread.cancel()
            for thread in active:
                if not thread.wait(5000):
                    thread.terminate()
                    thread.wait()

        # The titlebar X should minimize to tray when the user has chosen
        # that close behavior in Settings -- but File > Çıkış / the tray
        # menu's own Çıkış must always really quit, hence the flag.
        close_to_tray = get_config().get(
            'close_button_behavior', 'exit') == 'tray'
        if not self._intentional_quit and close_to_tray and (
                QSystemTrayIcon.isSystemTrayAvailable()):
            event.ignore()
            self.hide()
            return
        # setQuitOnLastWindowClosed(False) (needed so the tray-minimize
        # branch above can keep the app alive with no window open) means
        # Qt won't quit on its own here -- without this, closing via the
        # titlebar X leaves a windowless process running forever.
        event.accept()
        QApplication.instance().quit()

    # -- system tray / background checking -------------------------------

    def _setup_tray_icon(self):
        self._tray_icon = get_tray_icon()
        menu = QMenu()
        show_action = QAction(_('Göster'), self)
        show_action.triggered.connect(self._restore_from_tray)
        quit_action = QAction(_('Çıkış'), self)
        quit_action.triggered.connect(self.quit_application)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_application(self):
        self._intentional_quit = True
        self.close()
        QApplication.instance().quit()

    def _update_tray_visibility(self):
        """The tray icon should be visible whenever it's actually useful --
        either as the "minimized to" destination for the close button, or
        so background-check notifications have somewhere to pop up from --
        and hidden otherwise. Without this, the icon would only ever
        appear by accident, the first time notify() happens to fire.
        """
        config = get_config()
        should_show = (
            config.get('close_button_behavior', 'exit') == 'tray'
            or config.get('webnovel_check_enabled', False))
        if should_show and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.show()
        else:
            self._tray_icon.hide()

    def apply_webnovel_check_settings(self):
        """Re-reads the background-check settings and (re)starts or stops
        the timer accordingly -- called at startup and again whenever the
        Settings dialog closes, so a change takes effect immediately.
        """
        self._update_tray_visibility()
        config = get_config()
        enabled = config.get('webnovel_check_enabled', False)
        self.library_check_timer.stop()
        if not enabled:
            return
        interval_hours = config.get('webnovel_check_interval_hours', 6)
        self.library_check_timer.start(int(interval_hours * 3600 * 1000))
        # Also check shortly after startup instead of waiting a full
        # interval, so reopening the app after a while surfaces backlog
        # right away.
        QTimer.singleShot(30_000, self.run_library_check)

    def run_library_check(self):
        if self.library_check_worker is not None and (
                self.library_check_worker.isRunning()):
            return
        if not library.get_all():
            return
        self.library_check_worker = LibraryCheckWorker(self)
        self.library_check_worker.finished_ok.connect(
            self._on_library_check_done)
        self.library_check_worker.start()

    def _on_library_check_done(self, updates):
        for url, _title, _old, new_count in updates:
            library.update_chapter_count(url, new_count)
        if not updates:
            return
        lines = [
            '{}: +{}'.format(title, new_count - old_count)
            for _url, title, old_count, new_count in updates[:5]]
        if len(updates) > 5:
            lines.append(_('...ve {} roman daha').format(len(updates) - 5))
        notify(_('Yeni bölümler var!'), '\n'.join(lines))

    def check_for_updates(self):
        # At most once a day -- GitHub's API rate limit is generous, but
        # there is no reason to ask every single launch.
        last_at = get_config().get('update_check_last_at', 0) or 0
        if time.time() - last_at < 86400:
            return
        if (self.update_check_worker is not None
                and self.update_check_worker.isRunning()):
            return
        self.update_check_worker = UpdateCheckWorker(self)
        self.update_check_worker.release_found.connect(
            self._on_update_check_result)
        self.update_check_worker.start()

    def _on_update_check_result(self, release):
        get_config().save(update_check_last_at=time.time())
        latest_version = release['version']
        if not is_update_available(APP_VERSION, latest_version):
            return
        if get_config().get('update_check_skip_version') == latest_version:
            return

        box = QMessageBox(self)
        box.setWindowTitle(_('Yeni Sürüm Var'))
        box.setText(
            _('Yeni bir sürüm yayınlandı: {}\nŞu an kullanılan sürüm: {}')
            .format(latest_version, APP_VERSION))
        download_btn = box.addButton(
            _('İndir'), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_('Daha Sonra'), QMessageBox.ButtonRole.RejectRole)
        skip_btn = box.addButton(
            _('Bu Sürümü Atla'), QMessageBox.ButtonRole.DestructiveRole)
        box.exec()

        if box.clickedButton() == download_btn:
            webbrowser.open(release['url'])
        elif box.clickedButton() == skip_btn:
            get_config().save(update_check_skip_version=latest_version)

    # -- menu bar -------------------------------------------------------

    def _build_menu_bar(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu(_('Dosya'))
        add_action = file_menu.addAction(_('Dosya Ekle...'))
        add_action.triggered.connect(self.add_files)
        split_action = file_menu.addAction(_('Ham Metni Bölümlere Ayır...'))
        split_action.triggered.connect(self.open_splitter)
        file_menu.addSeparator()
        exit_action = file_menu.addAction(_('Çıkış'))
        exit_action.triggered.connect(self.quit_application)

        tools_menu = menu_bar.addMenu(_('Araçlar'))
        settings_action = tools_menu.addAction(_('Ayarlar...'))
        settings_action.triggered.connect(self.open_settings)

        help_menu = menu_bar.addMenu(_('Yardım'))
        about_action = help_menu.addAction(_('Hakkında...'))
        about_action.triggered.connect(self.open_about)

    def open_settings(self):
        if self.worker is not None:
            QMessageBox.warning(
                self, _('Uyarı'),
                _('Çeviri sürerken ayarlar değiştirilemez.'))
            return
        SettingsDialog(self).exec()
        self._refresh_engine_combo()
        self.apply_webnovel_check_settings()

    def open_splitter(self):
        dialog = SplitterDialog(self)
        if dialog.exec() and dialog.written_files:
            answer = QMessageBox.question(
                self, _('Sıraya Ekle'),
                _('Oluşturulan {} bölüm dosyası çeviri kuyruğuna '
                  'eklensin mi?').format(len(dialog.written_files)))
            if answer == QMessageBox.StandardButton.Yes:
                self._add_paths(dialog.written_files)

    def open_about(self):
        AboutDialog(self).exec()

    # -- UI construction -------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName('centralArea')
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(16, 16, 16, 16)
        outer_layout.setSpacing(10)

        tabs = QTabWidget()
        tabs.addTab(self._build_translate_tab(), _('Çeviri Kuyruğu'))
        tabs.addTab(self._build_webnovel_tab(), _('Web\'den Al'))
        tabs.addTab(self._build_library_tab(), _('Kütüphanem'))
        outer_layout.addWidget(tabs)

    def _build_library_tab(self):
        self.library_tab = LibraryTab()
        return self.library_tab

    def _build_translate_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_engine_bar())
        layout.addWidget(self._build_glossary_bar())
        layout.addWidget(self._build_file_bar())
        layout.addWidget(self._build_output_bar())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_table())
        splitter.addWidget(self._build_log_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        layout.addWidget(self._build_progress_row())
        layout.addWidget(self._build_controls_row())
        return widget

    def _build_webnovel_tab(self):
        self.webnovel_tab = WebNovelTab()
        self.webnovel_tab.epub_ready.connect(self._on_webnovel_epub_ready)
        return self.webnovel_tab

    def _on_webnovel_epub_ready(self, output_path):
        self._add_paths([output_path])
        QMessageBox.information(
            self, _('Eklendi'),
            _('İndirilen EPUB çeviri kuyruğuna eklendi:\n{}').format(output_path))

    def _build_engine_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel(_('Çeviri motoru:')))
        self.engine_combo = QComboBox()
        for engine in get_all_engines():
            self.engine_combo.addItem(engine.alias, engine.name)
        self.engine_combo.currentIndexChanged.connect(self._refresh_lang_combos)
        row.addWidget(self.engine_combo)

        row.addSpacing(16)
        row.addWidget(QLabel(_('Kaynak dil:')))
        self.source_lang_combo = QComboBox()
        row.addWidget(self.source_lang_combo)

        row.addSpacing(16)
        row.addWidget(QLabel(_('Hedef dil:')))
        self.target_lang_combo = QComboBox()
        row.addWidget(self.target_lang_combo)

        self.apply_btn = QPushButton(_('Seçili dosyalara uygula'))
        self.apply_btn.setToolTip(
            _('Yukarıdaki dil seçimini, listede seçili olan dosyalara uygular.'))
        self.apply_btn.clicked.connect(self._apply_langs_to_selected)
        row.addWidget(self.apply_btn)

        row.addStretch()
        return bar

    def _build_glossary_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        # "Düzenle" and "Terim Çıkar" used to be two separate buttons --
        # folded into one menu so this row doesn't keep growing every
        # time a glossary-related action gets added. A plain QPushButton
        # popping its own QMenu (rather than QToolButton) so it keeps
        # the app's regular button styling instead of the OS's bare
        # native look.
        self.glossary_btn = QPushButton(_('Sözlük ▾'))
        self.glossary_menu = QMenu(self.glossary_btn)
        self.glossary_menu.addAction(_('Düzenle...')).triggered.connect(
            self._open_glossary_dialog)
        extract_action = self.glossary_menu.addAction(
            _('Seçili Dosyadan Terim Çıkar...'))
        extract_action.setToolTip(_(
            'Seçili dosyadaki sık geçen özel isim/terimleri analiz edip '
            'sözlüğe ekler -- çevirilerini doldurman için.'))
        extract_action.triggered.connect(self._extract_glossary_terms)
        self.glossary_btn.clicked.connect(self._show_glossary_menu)
        row.addWidget(self.glossary_btn)

        self.glossary_enabled_check = QCheckBox(_('Sözlüğü Kullan'))
        self.glossary_enabled_check.setChecked(
            get_config().get('glossary_enabled', False))
        self.glossary_enabled_check.toggled.connect(
            lambda checked: get_config().save(glossary_enabled=checked))
        row.addWidget(self.glossary_enabled_check)

        row.addStretch()
        return bar

    def _show_glossary_menu(self):
        self.glossary_menu.exec(
            self.glossary_btn.mapToGlobal(self.glossary_btn.rect().bottomLeft()))

    def _resolve_glossary_path(self):
        path = get_config().get('glossary_path')
        if path:
            return path
        path, _filter = QFileDialog.getSaveFileName(
            self, _('Sözlük Dosyası Oluştur'), 'sozluk.txt',
            'Metin Dosyası (*.txt)')
        if not path:
            return None
        get_config().save(glossary_path=path)
        return path

    def _open_glossary_dialog(self):
        path = self._resolve_glossary_path()
        if not path:
            return
        GlossaryDialog(path, self).exec()

    def _extract_glossary_terms(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        if len(rows) != 1:
            QMessageBox.information(
                self, _('Dosya Seç'),
                _('Önce listeden kelime çıkarılacak tek bir dosya seç.'))
            return
        path = self._resolve_glossary_path()
        if not path:
            return
        item = self.queue_items[next(iter(rows))]
        terms = extract_terms(item.path, item.input_format)
        added = merge_extracted_terms(path, terms)
        if added:
            QMessageBox.information(
                self, _('Sözlük Güncellendi'),
                _('{} yeni terim bulundu ve sözlüğe eklendi. Çevirilerini '
                  'doldurmak için düzenleyici açılıyor.').format(added))
        else:
            QMessageBox.information(
                self, _('Yeni Terim Bulunamadı'),
                _('Bu dosyada sözlükte henüz olmayan, sık geçen bir terim '
                  'bulunamadı.'))
        GlossaryDialog(path, self, highlight_last_n=added).exec()

    def _build_file_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        self.add_btn = QPushButton(_('+ Dosya Ekle'))
        self.add_btn.setObjectName('primaryButton')
        self.add_btn.clicked.connect(self.add_files)
        row.addWidget(self.add_btn)

        self.remove_btn = QPushButton(_('Seçileni Kaldır'))
        self.remove_btn.clicked.connect(self.remove_selected)
        row.addWidget(self.remove_btn)

        self.clear_btn = QPushButton(_('Listeyi Temizle'))
        self.clear_btn.clicked.connect(self.clear_queue)
        row.addWidget(self.clear_btn)

        row.addStretch()
        hint = QLabel(_('İpucu: dosyaları doğrudan pencereye sürükleyip bırakabilirsin.'))
        hint.setObjectName('hintLabel')
        row.addWidget(hint)
        return bar

    def _build_output_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        row.addWidget(QLabel(_('Çıktı klasörü:')))
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setReadOnly(True)
        self.output_dir_edit.setPlaceholderText(
            _('(varsayılan) Kaynak dosyayla aynı klasör'))
        row.addWidget(self.output_dir_edit, stretch=1)

        choose_btn = QPushButton(_('Klasör Seç...'))
        choose_btn.clicked.connect(self._choose_output_dir)
        row.addWidget(choose_btn)

        reset_btn = QPushButton(_('Sıfırla'))
        reset_btn.setToolTip(_('Kaynak dosyayla aynı klasöre geri dön.'))
        reset_btn.clicked.connect(self._reset_output_dir)
        row.addWidget(reset_btn)

        self._load_output_dir_display()
        return bar

    def _load_output_dir_display(self):
        config = get_config()
        if not config.get('to_source_folder', True) and config.get('output_path'):
            self.output_dir_edit.setText(config.get('output_path'))
        else:
            self.output_dir_edit.clear()

    def _choose_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, _('Çıktı Klasörü Seç'))
        if path:
            get_config().save(to_source_folder=False, output_path=path)
            self.output_dir_edit.setText(path)

    def _reset_output_dir(self):
        get_config().save(to_source_folder=True, output_path=None)
        self.output_dir_edit.clear()

    def _build_table(self):
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [_('Dosya'), _('Biçim'), _('Kaynak'), _('Hedef'), _('Durum')])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_preview_button)
        return self.table

    def _update_preview_button(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        self.preview_btn.setEnabled(
            len(rows) == 1
            and self.queue_items[next(iter(rows))].status == STATUS_DONE)

    def preview_selected(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        if len(rows) != 1:
            return
        item = self.queue_items[next(iter(rows))]
        if item.status != STATUS_DONE or not item.output_path:
            return
        self._open_readers.append(open_preview(item.output_path, self))

    def _build_log_panel(self):
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setPlaceholderText(
            _('Çeviri kayıtları burada görünecek...'))
        return self.log_view

    def _build_progress_row(self):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        self.current_file_label = QLabel('')
        self.current_file_label.setObjectName('hintLabel')
        row.addWidget(self.current_file_label, stretch=1)
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        row.addWidget(self.overall_progress, stretch=2)
        return widget

    def _build_controls_row(self):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)

        self.start_btn = QPushButton(_('Çeviriyi Başlat'))
        self.start_btn.setObjectName('primaryButton')
        self.start_btn.clicked.connect(self.start_translation)
        row.addWidget(self.start_btn)

        self.pause_btn = QPushButton(_('Duraklat'))
        self.pause_btn.setCheckable(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setToolTip(
            _('Devam eden dosyayı da içinde bulunduğu noktada duraklatır.'))
        self.pause_btn.toggled.connect(self.toggle_pause)
        row.addWidget(self.pause_btn)

        self.cancel_btn = QPushButton(_('İptal Et'))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_translation)
        row.addWidget(self.cancel_btn)

        self.preview_btn = QPushButton(_('Önizle'))
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self.preview_selected)
        row.addWidget(self.preview_btn)

        row.addStretch()
        return widget

    # -- language combos ---------------------------------------------------

    def _current_engine_class(self):
        engine_name = self.engine_combo.currentData()
        engines = get_all_engines()
        return next(
            (e for e in engines if e.name == engine_name), engines[0])

    def _refresh_engine_combo(self):
        """Re-reads get_all_engines() so a custom engine added/edited in
        Settings shows up immediately, instead of only after a restart --
        called after the Settings dialog closes, like
        apply_webnovel_check_settings().
        """
        current_name = self.engine_combo.currentData()
        self.engine_combo.blockSignals(True)
        self.engine_combo.clear()
        for engine in get_all_engines():
            self.engine_combo.addItem(engine.alias, engine.name)
        index = self.engine_combo.findData(current_name)
        self.engine_combo.setCurrentIndex(max(index, 0))
        self.engine_combo.blockSignals(False)
        self._refresh_lang_combos()

    def _refresh_lang_combos(self):
        engine_class = self._current_engine_class()
        source_codes = engine_class.lang_codes.get('source') or {}
        target_codes = engine_class.lang_codes.get('target') or {}

        self.source_lang_combo.clear()
        self.source_lang_combo.addItem(_('Auto detect'))
        self.source_lang_combo.addItems(sorted(source_codes.keys()))

        self.target_lang_combo.clear()
        self.target_lang_combo.addItems(sorted(target_codes.keys()))
        turkish_index = self.target_lang_combo.findText('Turkish')
        if turkish_index >= 0:
            self.target_lang_combo.setCurrentIndex(turkish_index)

    def _apply_langs_to_selected(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            rows = range(len(self.queue_items))
        source_lang = self.source_lang_combo.currentText()
        target_lang = self.target_lang_combo.currentText()
        for row in rows:
            item = self.queue_items[row]
            item.source_lang = source_lang
            item.target_lang = target_lang
            self.table.item(row, 2).setText(source_lang)
            self.table.item(row, 3).setText(target_lang)

    # -- drag & drop ---------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self._add_paths(paths)

    # -- queue management -------------------------------------------------

    def add_files(self):
        patterns = ' '.join('*.%s' % ext for ext in SUPPORTED_EXTENSIONS)
        paths, _filter = QFileDialog.getOpenFileNames(
            self, _('Çevrilecek Dosyaları Seç'), '',
            '%s (%s)' % (_('Desteklenen Dosyalar'), patterns))
        self._add_paths(paths)

    def _add_paths(self, paths):
        if self.worker is not None and self.worker.isRunning():
            # Drag-and-drop reaches this directly, bypassing add_btn's
            # disabled state -- appending while QueueWorker is mid-run
            # wouldn't crash it the way removing does, but the new file
            # would silently start translating under whatever engine was
            # selected when the run started, with no "Çeviriyi Başlat"
            # ever clicked for it. Simpler to just disallow it here too.
            QMessageBox.information(
                self, _('Çeviri Sürüyor'),
                _('Çeviri çalışırken kuyruğa dosya eklenemez. Önce '
                  'çeviriyi durdur ya da tamamlanmasını bekle.'))
            return
        for path in paths:
            extension = os.path.splitext(path)[1].lstrip('.').lower()
            if extension not in SUPPORTED_EXTENSIONS:
                continue
            item = QueueItem(path)
            item.source_lang = self.source_lang_combo.currentText() or 'Auto detect'
            item.target_lang = self.target_lang_combo.currentText() or 'Turkish'
            self.queue_items.append(item)
            self._add_row(item)

    def _add_row(self, item: QueueItem):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(item.title))
        self.table.setItem(row, 1, QTableWidgetItem(item.input_format.upper()))
        self.table.setItem(row, 2, QTableWidgetItem(item.source_lang))
        self.table.setItem(row, 3, QTableWidgetItem(item.target_lang))
        self.table.setItem(row, 4, QTableWidgetItem(STATUS_LABELS['waiting']))

    def remove_selected(self):
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()},
            reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.queue_items[row]

    def clear_queue(self):
        self.table.setRowCount(0)
        self.queue_items.clear()

    # -- translation control -------------------------------------------------

    def start_translation(self):
        if not self.queue_items:
            QMessageBox.warning(
                self, _('Uyarı'), _('Önce çevrilecek dosya ekle.'))
            return

        engine_class = self._current_engine_class()
        if engine_class.need_api_key:
            prefs = get_config().get('engine_preferences', {}).get(
                engine_class.name, {})
            api_keys = prefs.get('api_keys') or []
            if not api_keys or not (api_keys[0] or '').strip():
                QMessageBox.warning(
                    self, _('API Anahtarı Eksik'),
                    _('"{}" motoru bir API anahtarı gerektiriyor. Lütfen '
                      'Araçlar > Ayarlar > Motor ve Hız\'tan anahtarını '
                      'gir.').format(engine_class.alias))
                return

        if not engine_class.free:
            total_chars = 0
            for item in self.queue_items:
                try:
                    total_chars += count_characters(
                        item.path, item.input_format)
                except Exception:
                    pass
            answer = QMessageBox.question(
                self, _('Ücretli Motor'),
                _('Seçili motor ("{}") ücretli. Kuyruktaki dosyaların '
                  'toplam karakter sayısı: ~{}.\n\n'
                  'Tam fiyatlandırma sağlayıcıya göre değişir ve sık '
                  'güncellenir, burada sabit bir tutar gösterilmiyor -- '
                  'güncel fiyatı motor sağlayıcısının kendi sitesinden '
                  'kontrol et.\n\nÇeviriye devam edilsin mi?')
                .format(engine_class.alias, total_chars))
            if answer != QMessageBox.StandardButton.Yes:
                return

        if self.worker is not None:
            self.worker.wait()

        config = get_config()
        config.save(translate_engine=self.engine_combo.currentData())

        self.worker = QueueWorker(self.queue_items, self._resolve_output_dir)
        self.worker.item_started.connect(self._on_item_started)
        self.worker.item_progress.connect(self._on_item_progress)
        self.worker.item_log.connect(self._on_item_log)
        self.worker.item_finished.connect(self._on_item_finished)
        self.worker.queue_finished.connect(self._on_queue_finished)
        self.worker.start()

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.engine_combo.setEnabled(False)
        self.source_lang_combo.setEnabled(False)
        self.target_lang_combo.setEnabled(False)
        # QueueWorker iterates self.queue_items by row index in its own
        # thread -- removing/clearing/adding rows here while it's running
        # desyncs those indices out from under it (the GUI list shrinks,
        # the worker keeps reporting progress for rows that no longer
        # exist) and crashes _on_item_progress/_on_item_started with an
        # IndexError, repeatedly, for every signal the worker still emits.
        self.add_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        # Same hazard as the list mutations above, just on item attributes
        # instead of list length: QueueWorker reads item.source_lang/
        # target_lang off these exact QueueItem objects when it gets to
        # them (worker.py), so rewriting a not-yet-started item's
        # language mid-run would silently translate it into the wrong
        # target language with no error at all.
        self.apply_btn.setEnabled(False)
        self.log_view.appendPlainText(_('--- Çeviri başlatıldı ---'))

    def _resolve_output_dir(self, item: QueueItem):
        config = get_config()
        if not config.get('to_source_folder', True):
            custom_path = config.get('output_path')
            if custom_path:
                return custom_path
        return os.path.dirname(item.path) or '.'

    def cancel_translation(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def toggle_pause(self, checked):
        if self.worker:
            self.worker.set_paused(checked)
        self.pause_btn.setText(_('Devam Et') if checked else _('Duraklat'))

    # -- worker signal handlers -------------------------------------------------

    def _on_item_started(self, row):
        if row >= len(self.queue_items):
            return
        self.table.item(row, 4).setText(STATUS_LABELS['running'])
        self.table.scrollToItem(self.table.item(row, 0))
        self.current_file_label.setText(self.queue_items[row].title)

    def _on_item_progress(self, row, fraction, message):
        if row >= len(self.queue_items):
            return
        self.overall_progress.setValue(int(fraction * 100))
        self.current_file_label.setText(
            '%s — %s' % (self.queue_items[row].title, message))

    def _on_item_log(self, row, message, is_error):
        self.log_view.appendPlainText(message)

    def _on_item_finished(self, row, status, message):
        if row >= len(self.queue_items):
            return
        self.table.item(row, 4).setText(
            STATUS_LABELS.get(status, status))
        self.queue_items[row].status = status
        self.queue_items[row].output_path = (
            message if status == STATUS_DONE else None)
        if status == STATUS_DONE:
            item = self.queue_items[row]
            answer = QMessageBox.question(
                self, _('Kütüphaneye Ekle'),
                _('"{}" Kütüphanem sekmesine eklensin mi? (Kapak resmiyle '
                  'görünür, içinde okuyabilirsin.)').format(item.title))
            if answer == QMessageBox.StandardButton.Yes:
                translated_library.record(
                    item.output_path, item.title, item.input_format)
            self.library_tab.refresh()
        else:
            self.log_view.appendPlainText(
                '[%s] %s' % (self.queue_items[row].title, message))

    def _on_queue_finished(self):
        was_cancelled = self.worker is not None and self.worker.was_cancelled
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setChecked(False)
        self.pause_btn.setText(_('Duraklat'))
        self.cancel_btn.setEnabled(False)
        self.engine_combo.setEnabled(True)
        self.source_lang_combo.setEnabled(True)
        self.target_lang_combo.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.remove_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.apply_btn.setEnabled(True)
        if was_cancelled:
            self.overall_progress.setValue(0)
            self.current_file_label.setText(_('İptal edildi.'))
            self.log_view.appendPlainText(_('--- Kuyruk iptal edildi ---'))
        else:
            self.current_file_label.setText(_('Tamamlandı.'))
            self.log_view.appendPlainText(_('--- Kuyruk tamamlandı ---'))
            notify(_('Novel Çeviri'), _('Çeviri kuyruğu tamamlandı.'))
        if self.worker is not None:
            # Same reasoning as webnovel_tab._reset_download_controls():
            # this slot runs off the worker's own queue_finished signal, so
            # wait for run() to fully unwind before dropping the reference.
            self.worker.wait()
        self.worker = None
