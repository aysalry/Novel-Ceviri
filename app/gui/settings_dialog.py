from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QColorDialog, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..core.cache import TranslationCache
from ..core.config import get_config
from ..core.i18n import _
from ..engines import builtin_engines
from .engine_test_worker import EngineTestWorker
from .glossary_dialog import GlossaryDialog
from .theme import apply_theme


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Ayarlar'))
        self.setMinimumSize(600, 560)
        self.resize(620, 640)
        self.config = get_config()
        self._original_theme = self.config.get('ui_theme', 'light')
        self._test_worker = None
        self._test_engine_class = None
        self._test_original_config = None

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._scrollable(self._build_general_tab()), _('Genel'))
        self.tabs.addTab(
            self._scrollable(self._build_engine_tab()), _('Motor ve Hız'))
        self.tabs.addTab(
            self._scrollable(self._build_output_tab()), _('Çıktı Görünümü'))
        self.tabs.addTab(self._scrollable(self._build_cache_tab()), _('Önbellek'))

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_btn = QPushButton(_('Kapat'))
        close_btn.clicked.connect(self.reject)
        save_btn = QPushButton(_('Kaydet'))
        save_btn.setObjectName('primaryButton')
        save_btn.clicked.connect(self._save_and_close)
        buttons.addWidget(close_btn)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons)

        self._load_values()

    @staticmethod
    def _scrollable(widget):
        scroll = QScrollArea()
        scroll.setWidget(widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    # -- tabs -------------------------------------------------------------

    def _build_general_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        folder_group = QGroupBox(_('Çıktı Klasörü'))
        folder_layout = QVBoxLayout(folder_group)
        self.same_folder_radio = QRadioButton(
            _('Kaynak dosyayla aynı klasöre kaydet (önerilir)'))
        self.custom_folder_radio = QRadioButton(_('Şu klasöre kaydet:'))
        folder_layout.addWidget(self.same_folder_radio)
        folder_layout.addWidget(self.custom_folder_radio)

        folder_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setEnabled(False)
        browse_btn = QPushButton(_('Seç...'))
        browse_btn.setEnabled(False)
        browse_btn.clicked.connect(self._browse_output_folder)
        self.custom_folder_radio.toggled.connect(
            self.output_path_edit.setEnabled)
        self.custom_folder_radio.toggled.connect(browse_btn.setEnabled)
        folder_row.addWidget(self.output_path_edit)
        folder_row.addWidget(browse_btn)
        folder_layout.addLayout(folder_row)
        layout.addWidget(folder_group)

        glossary_group = QGroupBox(_('Çeviri Sözlüğü'))
        glossary_layout = QVBoxLayout(glossary_group)
        self.glossary_enabled_check = QCheckBox(_('Sözlük kullan'))
        glossary_layout.addWidget(self.glossary_enabled_check)
        glossary_row = QHBoxLayout()
        self.glossary_path_edit = QLineEdit()
        self.glossary_path_edit.setReadOnly(True)
        glossary_browse_btn = QPushButton(_('Dosya Seç...'))
        glossary_browse_btn.clicked.connect(self._browse_glossary)
        glossary_edit_btn = QPushButton(_('Düzenle...'))
        glossary_edit_btn.clicked.connect(self._open_glossary_editor)
        glossary_row.addWidget(self.glossary_path_edit)
        glossary_row.addWidget(glossary_browse_btn)
        glossary_row.addWidget(glossary_edit_btn)
        glossary_layout.addLayout(glossary_row)
        glossary_hint = QLabel(_(
            'Karakter/yer adlarının her bölümde aynı şekilde çevrilmesini, '
            'ya da hiç çevrilmemesini sağlar.'))
        glossary_hint.setObjectName('hintLabel')
        glossary_hint.setWordWrap(True)
        glossary_layout.addWidget(glossary_hint)
        layout.addWidget(glossary_group)

        theme_group = QGroupBox(_('Görünüm'))
        theme_layout = QHBoxLayout(theme_group)
        theme_layout.addWidget(QLabel(_('Tema:')))
        self._theme_button_group = QButtonGroup(self)
        self.light_theme_radio = QRadioButton(_('Açık (pastel)'))
        self.dark_theme_radio = QRadioButton(_('Karanlık'))
        self._theme_button_group.addButton(self.light_theme_radio)
        self._theme_button_group.addButton(self.dark_theme_radio)
        self.light_theme_radio.toggled.connect(self._preview_theme)
        self.dark_theme_radio.toggled.connect(self._preview_theme)
        theme_layout.addWidget(self.light_theme_radio)
        theme_layout.addWidget(self.dark_theme_radio)
        theme_layout.addStretch()
        layout.addWidget(theme_group)

        close_behavior_group = QGroupBox(_('Kapatma Düğmesi'))
        close_behavior_layout = QVBoxLayout(close_behavior_group)
        self._close_behavior_button_group = QButtonGroup(self)
        self.close_exit_radio = QRadioButton(_('Programdan çık'))
        self.close_tray_radio = QRadioButton(_('Sistem tepsisine küçült'))
        self._close_behavior_button_group.addButton(self.close_exit_radio)
        self._close_behavior_button_group.addButton(self.close_tray_radio)
        close_behavior_layout.addWidget(self.close_exit_radio)
        close_behavior_layout.addWidget(self.close_tray_radio)
        close_behavior_hint = QLabel(_(
            '"Sistem tepsisine küçült" seçiliyse pencereyi kapatma (X) '
            'düğmesi programı kapatmaz, tepside arka planda çalışmaya '
            'devam eder; tamamen çıkmak için tepsi simgesine sağ tıklayıp '
            '"Çıkış"ı kullan.'))
        close_behavior_hint.setObjectName('hintLabel')
        close_behavior_hint.setWordWrap(True)
        close_behavior_layout.addWidget(close_behavior_hint)
        layout.addWidget(close_behavior_group)

        webnovel_check_group = QGroupBox(_('Yeni Bölüm Bildirimleri'))
        webnovel_check_layout = QVBoxLayout(webnovel_check_group)
        self.webnovel_check_enabled_check = QCheckBox(
            _('"Web\'den Al" ile indirdiğim romanları arka planda otomatik '
              'kontrol et'))
        webnovel_check_layout.addWidget(self.webnovel_check_enabled_check)
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel(_('Kontrol sıklığı:')))
        self.webnovel_check_interval_combo = QComboBox()
        for hours, label in (
                (1, _('Her saat')), (3, _('Her 3 saatte')),
                (6, _('Her 6 saatte')), (12, _('Her 12 saatte')),
                (24, _('Her 24 saatte'))):
            self.webnovel_check_interval_combo.addItem(label, hours)
        interval_row.addWidget(self.webnovel_check_interval_combo)
        interval_row.addStretch()
        webnovel_check_layout.addLayout(interval_row)
        webnovel_check_hint = QLabel(_(
            'Bu kontrol program açıkken çalışır. Pencereyi kapatınca da '
            'arka planda sürmesini istiyorsan yukarıdaki "Kapatma '
            'Düğmesi" ayarını "Sistem tepsisine küçült" yap.'))
        webnovel_check_hint.setObjectName('hintLabel')
        webnovel_check_hint.setWordWrap(True)
        webnovel_check_layout.addWidget(webnovel_check_hint)
        layout.addWidget(webnovel_check_group)

        layout.addStretch()
        return widget

    def _preview_theme(self):
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, 'dark' if self.dark_theme_radio.isChecked() else 'light')

    def _build_engine_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        select_row = QFormLayout()
        self.engine_select = QComboBox()
        for engine in builtin_engines:
            self.engine_select.addItem(engine.alias, engine.name)
        self.engine_select.currentIndexChanged.connect(
            self._load_engine_preferences)
        select_row.addRow(_('Ayarlanacak motor:'), self.engine_select)
        layout.addLayout(select_row)

        self.api_key_group = QGroupBox(_('API Anahtarı'))
        api_key_layout = QVBoxLayout(self.api_key_group)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_layout.addWidget(self.api_key_edit)
        api_key_hint = QLabel(_(
            'Gemini için ücretsiz bir anahtar alabileceğin adres: '
            'aistudio.google.com/apikey'))
        api_key_hint.setObjectName('hintLabel')
        api_key_hint.setWordWrap(True)
        api_key_layout.addWidget(api_key_hint)
        layout.addWidget(self.api_key_group)

        self.model_group = QGroupBox(_('Model'))
        model_layout = QFormLayout(self.model_group)
        self.model_edit = QLineEdit()
        model_layout.addRow(_('Model adı:'), self.model_edit)
        layout.addWidget(self.model_group)

        test_row = QHBoxLayout()
        self.test_engine_btn = QPushButton(_('Test Et'))
        self.test_engine_btn.clicked.connect(self._test_engine)
        test_row.addWidget(self.test_engine_btn)
        reset_engine_btn = QPushButton(_('Varsayılana Sıfırla'))
        reset_engine_btn.clicked.connect(self._reset_engine_to_default)
        test_row.addWidget(reset_engine_btn)
        test_row.addStretch()
        layout.addLayout(test_row)
        self.test_result_label = QLabel('')
        self.test_result_label.setObjectName('hintLabel')
        self.test_result_label.setWordWrap(True)
        layout.addWidget(self.test_result_label)

        self.temperature_group = QGroupBox(_('Yaratıcılık (Temperature)'))
        temperature_layout = QVBoxLayout(self.temperature_group)
        self.temperature_enabled_check = QCheckBox(
            _('Özel bir sıcaklık değeri kullan'))
        temperature_layout.addWidget(self.temperature_enabled_check)

        temperature_row = QHBoxLayout()
        plain_label = QLabel(_('Düz çeviri'))
        plain_label.setObjectName('hintLabel')
        self.temperature_slider = QSlider(Qt.Orientation.Horizontal)
        self.temperature_slider.setRange(0, 100)
        self.temperature_value_label = QLabel('0.50')
        self.temperature_value_label.setFixedWidth(36)
        poetic_label = QLabel(_('Daha "samimi" / şiirsel'))
        poetic_label.setObjectName('hintLabel')
        self.temperature_slider.valueChanged.connect(
            lambda value: self.temperature_value_label.setText(
                '%.2f' % (value / 100)))
        temperature_row.addWidget(plain_label)
        temperature_row.addWidget(self.temperature_slider)
        temperature_row.addWidget(poetic_label)
        temperature_row.addWidget(self.temperature_value_label)
        temperature_layout.addLayout(temperature_row)
        self.temperature_enabled_check.toggled.connect(
            self.temperature_slider.setEnabled)

        temperature_hint = QLabel(_(
            '0 = motorun varsayılan, dümdüz/tutarlı çevirisi. 1\'e '
            'yaklaştıkça çeviri daha özgür ve "şiirsel" bir üsluba kayar. '
            'Kapalıyken motorun kendi varsayılanı kullanılır.'))
        temperature_hint.setWordWrap(True)
        temperature_hint.setObjectName('hintLabel')
        temperature_layout.addWidget(temperature_hint)
        layout.addWidget(self.temperature_group)

        speed_group = QGroupBox(_('Hız Ayarları'))
        speed_form = QFormLayout(speed_group)

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 64)
        speed_form.addRow(_('Eşzamanlı istek sayısı:'), self.concurrency_spin)
        concurrency_hint = QLabel(_(
            'Aynı anda kaç çeviri isteği gönderilecek. Yüksek değer hızlıdır, '
            'ama çok yüksek değerler geçici olarak engellenmene neden olabilir.'))
        concurrency_hint.setWordWrap(True)
        concurrency_hint.setObjectName('hintLabel')
        speed_form.addRow(concurrency_hint)

        self.merge_enabled_check = QCheckBox(
            _('Kısa paragrafları birleştirerek istek sayısını azalt (önerilir)'))
        speed_form.addRow(self.merge_enabled_check)
        self.merge_length_spin = QSpinBox()
        self.merge_length_spin.setRange(200, 5000)
        self.merge_length_spin.setSingleStep(100)
        speed_form.addRow(
            _('Birleştirme uzunluğu (karakter):'), self.merge_length_spin)
        merge_hint = QLabel(_(
            'Birleştirme, çok sayıda kısa paragrafı tek istekte göndererek '
            'toplam istek sayısını (ve süreyi) büyük ölçüde azaltır.'))
        merge_hint.setWordWrap(True)
        merge_hint.setObjectName('hintLabel')
        speed_form.addRow(merge_hint)

        self.request_interval_spin = QDoubleSpinBox()
        self.request_interval_spin.setRange(0.0, 30.0)
        self.request_interval_spin.setSingleStep(0.1)
        speed_form.addRow(
            _('İstekler arası bekleme (saniye):'), self.request_interval_spin)

        self.request_attempt_spin = QSpinBox()
        self.request_attempt_spin.setRange(1, 20)
        speed_form.addRow(
            _('Hatada tekrar deneme sayısı:'), self.request_attempt_spin)

        self.request_timeout_spin = QDoubleSpinBox()
        self.request_timeout_spin.setRange(5.0, 120.0)
        speed_form.addRow(
            _('İstek zaman aşımı (saniye):'), self.request_timeout_spin)

        layout.addWidget(speed_group)
        layout.addStretch()
        return widget

    def _build_output_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        position_group = QGroupBox(_('Çeviri Yerleşimi (EPUB)'))
        position_layout = QVBoxLayout(position_group)
        self._position_button_group = QButtonGroup(self)
        self.position_radios = {}
        choices = [
            ('below', _('Orijinal metnin altında (iki dilli)')),
            ('above', _('Orijinal metnin üstünde (iki dilli)')),
            ('only', _('Sadece çeviri (orijinal silinir)')),
        ]
        for key, label in choices:
            radio = QRadioButton(label)
            self._position_button_group.addButton(radio)
            self.position_radios[key] = radio
            position_layout.addWidget(radio)
        layout.addWidget(position_group)

        color_group = QGroupBox(_('Renkler (isteğe bağlı)'))
        color_form = QFormLayout(color_group)

        self.original_color_edit = QLineEdit()
        self.original_color_edit.setPlaceholderText(_('(değiştirilmez)'))
        original_color_btn = QPushButton(_('Seç...'))
        original_color_btn.clicked.connect(
            lambda: self._pick_color(self.original_color_edit))
        original_row = QHBoxLayout()
        original_row.addWidget(self.original_color_edit)
        original_row.addWidget(original_color_btn)
        color_form.addRow(_('Orijinal metin rengi:'), original_row)

        self.translation_color_edit = QLineEdit()
        self.translation_color_edit.setPlaceholderText(_('(değiştirilmez)'))
        translation_color_btn = QPushButton(_('Seç...'))
        translation_color_btn.clicked.connect(
            lambda: self._pick_color(self.translation_color_edit))
        translation_row = QHBoxLayout()
        translation_row.addWidget(self.translation_color_edit)
        translation_row.addWidget(translation_color_btn)
        color_form.addRow(_('Çeviri metni rengi:'), translation_row)

        layout.addWidget(color_group)
        layout.addStretch()
        return widget

    def _build_cache_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.cache_enabled_check = QCheckBox(
            _('Çevirileri önbelleğe al (yeniden çalıştırınca tekrar çevirme)'))
        layout.addWidget(self.cache_enabled_check)

        hint = QLabel(_(
            'Önbellek, daha önce çevrilmiş paragrafları hatırlar ve tekrar '
            'API\'ye göndermez; kesinti sonrası devam etmeyi de hızlandırır.'))
        hint.setWordWrap(True)
        hint.setObjectName('hintLabel')
        layout.addWidget(hint)

        self.cache_size_label = QLabel()
        layout.addWidget(self.cache_size_label)

        clear_btn = QPushButton(_('Önbelleği Temizle'))
        clear_btn.clicked.connect(self._clear_cache)
        layout.addWidget(clear_btn)

        layout.addStretch()
        self._refresh_cache_size()
        return widget

    # -- color picker -------------------------------------------------------

    def _pick_color(self, line_edit):
        initial = QColor(line_edit.text()) if line_edit.text() else QColor(
            '#000000')
        color = QColorDialog.getColor(initial, self)
        if color.isValid():
            line_edit.setText(color.name())

    # -- cache --------------------------------------------------------------

    def _refresh_cache_size(self):
        size_mb = TranslationCache.count()
        self.cache_size_label.setText(
            _('Önbellek boyutu: {} MB').format(size_mb))

    def _clear_cache(self):
        answer = QMessageBox.question(
            self, _('Onay'),
            _('Tüm önbellek silinsin mi? Bu işlem geri alınamaz.'))
        if answer == QMessageBox.StandardButton.Yes:
            TranslationCache.clean()
            self._refresh_cache_size()

    # -- browse handlers ------------------------------------------------------

    def _browse_output_folder(self):
        path = QFileDialog.getExistingDirectory(self, _('Klasör Seç'))
        if path:
            self.output_path_edit.setText(path)
            self.custom_folder_radio.setChecked(True)

    def _browse_glossary(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, _('Sözlük Dosyası Seç'), '', 'Metin Dosyası (*.txt)')
        if path:
            self.glossary_path_edit.setText(path)

    def _open_glossary_editor(self):
        path = self.glossary_path_edit.text().strip()
        if not path:
            path, _filter = QFileDialog.getSaveFileName(
                self, _('Sözlük Dosyası Oluştur'), 'sozluk.txt',
                'Metin Dosyası (*.txt)')
            if not path:
                return
            self.glossary_path_edit.setText(path)
        if GlossaryDialog(path, self).exec():
            self.glossary_enabled_check.setChecked(True)

    # -- load / save ----------------------------------------------------------

    def _load_values(self):
        c = self.config
        same_folder = c.get('to_source_folder', True)
        self.same_folder_radio.setChecked(same_folder)
        self.custom_folder_radio.setChecked(not same_folder)
        self.output_path_edit.setText(c.get('output_path') or '')

        self.glossary_enabled_check.setChecked(c.get('glossary_enabled', False))
        self.glossary_path_edit.setText(c.get('glossary_path') or '')

        if self._original_theme == 'dark':
            self.dark_theme_radio.setChecked(True)
        else:
            self.light_theme_radio.setChecked(True)

        close_behavior = c.get('close_button_behavior', 'exit')
        self.close_tray_radio.setChecked(close_behavior == 'tray')
        self.close_exit_radio.setChecked(close_behavior != 'tray')

        self.webnovel_check_enabled_check.setChecked(
            c.get('webnovel_check_enabled', False))
        interval_index = self.webnovel_check_interval_combo.findData(
            c.get('webnovel_check_interval_hours', 6))
        self.webnovel_check_interval_combo.setCurrentIndex(max(interval_index, 0))

        position = c.get('translation_position', 'below')
        self.position_radios.get(
            position, self.position_radios['below']).setChecked(True)
        self.original_color_edit.setText(c.get('original_color') or '')
        self.translation_color_edit.setText(c.get('translation_color') or '')

        self.cache_enabled_check.setChecked(c.get('cache_enabled', True))

        current_engine = c.get('translate_engine') or 'Google(Free)New'
        index = self.engine_select.findData(current_engine)
        self.engine_select.setCurrentIndex(max(index, 0))
        self._load_engine_preferences()

    def _load_engine_preferences(self):
        engine_class = self._current_engine_class()
        prefs = self.config.get('engine_preferences', {}).get(
            engine_class.name, {})

        self.test_result_label.setText('')

        self.api_key_group.setVisible(engine_class.need_api_key)
        api_keys = prefs.get('api_keys', [])
        self.api_key_edit.setText(api_keys[0] if api_keys else '')

        self.model_group.setVisible(hasattr(engine_class, 'model'))
        self.model_edit.setText(
            prefs.get('model') or getattr(engine_class, 'model', '') or '')

        has_temperature = hasattr(engine_class, 'temperature')
        self.temperature_group.setVisible(has_temperature)
        default_temperature = getattr(engine_class, 'temperature', 0.9)
        custom_temperature = prefs.get('temperature')
        self.temperature_enabled_check.setChecked(custom_temperature is not None)
        self.temperature_slider.setEnabled(custom_temperature is not None)
        shown_temperature = (
            custom_temperature if custom_temperature is not None
            else default_temperature)
        self.temperature_slider.setValue(
            max(0, min(100, round(shown_temperature * 100))))
        self.temperature_value_label.setText('%.2f' % shown_temperature)

        default_concurrency = engine_class.concurrency_limit or 8
        self.concurrency_spin.setValue(
            int(prefs.get('concurrency_limit') or default_concurrency))
        self.merge_enabled_check.setChecked(self.config.get('merge_enabled', True))
        self.merge_length_spin.setValue(self.config.get('merge_length', 1800))
        self.request_interval_spin.setValue(
            float(prefs.get(
                'request_interval', engine_class.request_interval)))
        self.request_attempt_spin.setValue(
            int(prefs.get('request_attempt', engine_class.request_attempt)))
        self.request_timeout_spin.setValue(
            float(prefs.get('request_timeout', engine_class.request_timeout)))

    def _reset_engine_to_default(self):
        """Reloads the form for the selected engine as if it had no saved
        overrides at all -- mirrors _load_engine_preferences() but always
        takes the engine class's built-in defaults instead of anything
        from engine_preferences. Like every other field here, this only
        changes the form; Kaydet still has to be clicked to persist it.
        """
        engine_class = self._current_engine_class()
        self.test_result_label.setText('')

        self.api_key_edit.setText('')
        self.model_edit.setText(getattr(engine_class, 'model', '') or '')

        default_temperature = getattr(engine_class, 'temperature', 0.9)
        self.temperature_enabled_check.setChecked(False)
        self.temperature_slider.setValue(
            max(0, min(100, round(default_temperature * 100))))
        self.temperature_value_label.setText('%.2f' % default_temperature)

        default_concurrency = engine_class.concurrency_limit or 8
        self.concurrency_spin.setValue(default_concurrency)
        self.request_interval_spin.setValue(float(engine_class.request_interval))
        self.request_attempt_spin.setValue(int(engine_class.request_attempt))
        self.request_timeout_spin.setValue(float(engine_class.request_timeout))

    def _current_engine_class(self):
        engine_name = self.engine_select.currentData()
        return next(e for e in builtin_engines if e.name == engine_name)

    # -- engine test ----------------------------------------------------------

    def _build_current_engine_prefs(self, engine_class):
        prefs = {}
        api_key_text = self.api_key_edit.text().strip()
        prefs['api_keys'] = [api_key_text] if api_key_text else []
        if hasattr(engine_class, 'model'):
            prefs['model'] = self.model_edit.text().strip()
        if hasattr(engine_class, 'temperature') \
                and self.temperature_enabled_check.isChecked():
            prefs['temperature'] = self.temperature_slider.value() / 100
        prefs['concurrency_limit'] = self.concurrency_spin.value()
        prefs['request_interval'] = self.request_interval_spin.value()
        prefs['request_attempt'] = self.request_attempt_spin.value()
        prefs['request_timeout'] = self.request_timeout_spin.value()
        return prefs

    def _test_engine(self):
        engine_class = self._current_engine_class()
        if engine_class.need_api_key and not self.api_key_edit.text().strip():
            QMessageBox.warning(
                self, _('Test Et'), _('Önce bir API anahtarı girmelisin.'))
            return

        self._test_engine_class = engine_class
        self._test_original_config = engine_class.config
        engine_class.set_config(self._build_current_engine_prefs(engine_class))

        self.test_engine_btn.setEnabled(False)
        self.test_engine_btn.setText(_('Test ediliyor...'))
        self.engine_select.setEnabled(False)
        self.test_result_label.setText('')

        self._test_worker = EngineTestWorker(engine_class)
        self._test_worker.finished_ok.connect(self._on_test_ok)
        self._test_worker.finished_error.connect(self._on_test_error)
        self._test_worker.finished.connect(self._on_test_thread_finished)
        self._test_worker.start()

    def _restore_test_config(self):
        if self._test_engine_class is not None:
            self._test_engine_class.set_config(self._test_original_config)

    def _on_test_ok(self, sample):
        self._restore_test_config()
        self.test_result_label.setText(
            _('Başarılı! Örnek çeviri: "{}"').format(sample))

    def _on_test_error(self, message):
        self._restore_test_config()
        self.test_result_label.setText(_('Başarısız: {}').format(message))

    def _on_test_thread_finished(self):
        self.test_engine_btn.setEnabled(True)
        self.test_engine_btn.setText(_('Test Et'))
        self.engine_select.setEnabled(True)

    def _test_in_progress(self):
        return self._test_worker is not None and self._test_worker.isRunning()

    def closeEvent(self, event):
        if self._test_in_progress():
            event.ignore()
            return
        super().closeEvent(event)

    def _selected_position(self):
        for key, radio in self.position_radios.items():
            if radio.isChecked():
                return key
        return 'below'

    def _save_and_close(self):
        if self._test_in_progress():
            return
        c = self.config
        c.update(
            to_source_folder=self.same_folder_radio.isChecked(),
            output_path=self.output_path_edit.text().strip() or None,
            glossary_enabled=self.glossary_enabled_check.isChecked(),
            glossary_path=self.glossary_path_edit.text().strip() or None,
            translation_position=self._selected_position(),
            original_color=self.original_color_edit.text().strip() or None,
            translation_color=self.translation_color_edit.text().strip() or None,
            cache_enabled=self.cache_enabled_check.isChecked(),
            merge_enabled=self.merge_enabled_check.isChecked(),
            merge_length=self.merge_length_spin.value(),
            ui_theme='dark' if self.dark_theme_radio.isChecked() else 'light',
            close_button_behavior=(
                'tray' if self.close_tray_radio.isChecked() else 'exit'),
            webnovel_check_enabled=self.webnovel_check_enabled_check.isChecked(),
            webnovel_check_interval_hours=(
                self.webnovel_check_interval_combo.currentData()),
        )

        engine_class = self._current_engine_class()
        engine_preferences = c.get('engine_preferences', {})
        prefs = engine_preferences.setdefault(engine_class.name, {})
        api_key_text = self.api_key_edit.text().strip()
        prefs['api_keys'] = [api_key_text] if api_key_text else []
        if hasattr(engine_class, 'model'):
            prefs['model'] = self.model_edit.text().strip()
        if hasattr(engine_class, 'temperature'):
            if self.temperature_enabled_check.isChecked():
                prefs['temperature'] = self.temperature_slider.value() / 100
            else:
                prefs.pop('temperature', None)
        prefs['concurrency_limit'] = self.concurrency_spin.value()
        prefs['request_interval'] = self.request_interval_spin.value()
        prefs['request_attempt'] = self.request_attempt_spin.value()
        prefs['request_timeout'] = self.request_timeout_spin.value()
        c.update(engine_preferences=engine_preferences)
        c.commit()

        self.accept()

    def reject(self):
        if self._test_in_progress():
            return
        # Undo the live theme preview if the user backs out without saving.
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self._original_theme)
        super().reject()
