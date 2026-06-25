import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QSystemTrayIcon,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..core.config import get_config
from ..core.i18n import _
from ..engines import builtin_engines
from ..webnovel import library
from .about_dialog import AboutDialog
from .notifications import get_tray_icon, notify
from .preview_dialog import PreviewDialog
from .queue_item import QueueItem, SUPPORTED_EXTENSIONS, STATUS_DONE
from .settings_dialog import SettingsDialog
from .splitter_dialog import SplitterDialog
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
        self._intentional_quit = False

        self.library_check_timer = QTimer(self)
        self.library_check_timer.timeout.connect(self.run_library_check)

        self._build_menu_bar()
        self._build_ui()
        self._refresh_lang_combos()
        self._setup_tray_icon()
        self.apply_webnovel_check_settings()

    def _active_background_threads(self):
        webnovel_workers = (
            self.webnovel_tab.info_worker, self.webnovel_tab.download_worker,
            self.webnovel_tab.search_worker)
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
        outer_layout.addWidget(tabs)

    def _build_translate_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_engine_bar())
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
        for engine in builtin_engines:
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

        apply_btn = QPushButton(_('Seçili dosyalara uygula'))
        apply_btn.setToolTip(
            _('Yukarıdaki dil seçimini, listede seçili olan dosyalara uygular.'))
        apply_btn.clicked.connect(self._apply_langs_to_selected)
        row.addWidget(apply_btn)

        row.addStretch()
        return bar

    def _build_file_bar(self):
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        add_btn = QPushButton(_('+ Dosya Ekle'))
        add_btn.setObjectName('primaryButton')
        add_btn.clicked.connect(self.add_files)
        row.addWidget(add_btn)

        remove_btn = QPushButton(_('Seçileni Kaldır'))
        remove_btn.clicked.connect(self.remove_selected)
        row.addWidget(remove_btn)

        clear_btn = QPushButton(_('Listeyi Temizle'))
        clear_btn.clicked.connect(self.clear_queue)
        row.addWidget(clear_btn)

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
        PreviewDialog(item.output_path, self).exec()

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
        return next(e for e in builtin_engines if e.name == engine_name)

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
        self.table.item(row, 4).setText(STATUS_LABELS['running'])
        self.table.scrollToItem(self.table.item(row, 0))
        self.current_file_label.setText(self.queue_items[row].title)

    def _on_item_progress(self, row, fraction, message):
        self.overall_progress.setValue(int(fraction * 100))
        self.current_file_label.setText(
            '%s — %s' % (self.queue_items[row].title, message))

    def _on_item_log(self, row, message, is_error):
        self.log_view.appendPlainText(message)

    def _on_item_finished(self, row, status, message):
        self.table.item(row, 4).setText(
            STATUS_LABELS.get(status, status))
        self.queue_items[row].status = status
        self.queue_items[row].output_path = (
            message if status == STATUS_DONE else None)
        if status != STATUS_DONE:
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
