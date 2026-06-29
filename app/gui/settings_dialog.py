import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QColorDialog, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QRadioButton, QScrollArea, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget)

from ..core.cache import TranslationCache
from ..core.config import get_config
from ..core.i18n import _
from ..engines import builtin_engines, get_all_engines
from ..engines.custom import build_custom_engine_class
from .custom_engine_dialog import CustomEngineDialog
from .engine_test_worker import EngineTestWorker
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
        self._custom_engines_draft = {}

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._scrollable(self._build_general_tab()), _('Genel'))
        self.tabs.addTab(
            self._scrollable(self._build_engine_tab()), _('Motor ve Hız'))
        self.tabs.addTab(
            self._scrollable(self._build_output_tab()), _('Çıktı Görünümü'))
        self.tabs.addTab(
            self._scrollable(self._build_filter_tab()), _('Filtreleme'))
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

        notification_group = QGroupBox(_('Bildirimler'))
        notification_layout = QVBoxLayout(notification_group)
        self.show_notification_check = QCheckBox(
            _('Masaüstü bildirimleri göster'))
        notification_layout.addWidget(self.show_notification_check)
        layout.addWidget(notification_group)

        proxy_group = QGroupBox(_('HTTP Proxy'))
        proxy_layout = QVBoxLayout(proxy_group)
        self.proxy_enabled_check = QCheckBox(_('Proxy kullan'))
        proxy_layout.addWidget(self.proxy_enabled_check)
        proxy_row = QHBoxLayout()
        proxy_row.addWidget(QLabel(_('Sunucu:')))
        self.proxy_host_edit = QLineEdit()
        self.proxy_host_edit.setPlaceholderText('127.0.0.1')
        self.proxy_host_edit.setEnabled(False)
        proxy_row.addWidget(self.proxy_host_edit, 3)
        proxy_row.addWidget(QLabel(_('Port:')))
        self.proxy_port_spin = QSpinBox()
        self.proxy_port_spin.setRange(1, 65535)
        self.proxy_port_spin.setValue(8080)
        self.proxy_port_spin.setEnabled(False)
        proxy_row.addWidget(self.proxy_port_spin, 1)
        proxy_layout.addLayout(proxy_row)
        self.proxy_enabled_check.toggled.connect(self.proxy_host_edit.setEnabled)
        self.proxy_enabled_check.toggled.connect(self.proxy_port_spin.setEnabled)
        proxy_hint = QLabel(_(
            'Google/DeepL gibi servislerin engellendiği bölgelerde, '
            'çeviri isteklerini bir HTTP proxy üzerinden göndermek için '
            'kullan.'))
        proxy_hint.setObjectName('hintLabel')
        proxy_hint.setWordWrap(True)
        proxy_layout.addWidget(proxy_hint)
        layout.addWidget(proxy_group)

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

        custom_group = QGroupBox(_('Özel Motorlar'))
        custom_layout = QVBoxLayout(custom_group)
        self.custom_engine_list = QListWidget()
        self.custom_engine_list.setMaximumHeight(90)
        custom_layout.addWidget(self.custom_engine_list)
        custom_buttons = QHBoxLayout()
        add_custom_btn = QPushButton(_('+ Ekle'))
        add_custom_btn.clicked.connect(self._add_custom_engine)
        edit_custom_btn = QPushButton(_('Düzenle'))
        edit_custom_btn.clicked.connect(self._edit_custom_engine)
        remove_custom_btn = QPushButton(_('Sil'))
        remove_custom_btn.clicked.connect(self._remove_custom_engine)
        custom_buttons.addWidget(add_custom_btn)
        custom_buttons.addWidget(edit_custom_btn)
        custom_buttons.addWidget(remove_custom_btn)
        custom_buttons.addStretch()
        custom_layout.addLayout(custom_buttons)
        custom_hint = QLabel(_(
            'Listede olmayan bir çeviri API\'sini JSON ile tanımlamak için '
            'kullan -- eklenince aşağıdaki motor listesinde de görünür.'))
        custom_hint.setObjectName('hintLabel')
        custom_hint.setWordWrap(True)
        custom_layout.addWidget(custom_hint)
        layout.addWidget(custom_group)

        select_row = QFormLayout()
        self.engine_select = QComboBox()
        for engine in get_all_engines():
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
        self.api_key_hint_label = QLabel('')
        self.api_key_hint_label.setObjectName('hintLabel')
        self.api_key_hint_label.setWordWrap(True)
        api_key_layout.addWidget(self.api_key_hint_label)
        layout.addWidget(self.api_key_group)

        self.model_group = QGroupBox(_('Model'))
        model_layout = QFormLayout(self.model_group)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        model_layout.addRow(_('Model adı:'), self.model_combo)
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

    def _build_filter_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        ignore_group = QGroupBox(_('Yoksay Kuralları (CSS seçici)'))
        ignore_layout = QVBoxLayout(ignore_group)
        self.ignore_rules_edit = QPlainTextEdit()
        self.ignore_rules_edit.setPlaceholderText(
            'pre\n.no-translate')
        self.ignore_rules_edit.setMinimumHeight(70)
        ignore_layout.addWidget(self.ignore_rules_edit)
        ignore_hint = QLabel(_(
            'Her satıra bir CSS seçici. Eşleşen elemanlar hiç çeviriye '
            'gönderilmez, olduğu gibi kalır (kod bloğu, dipnot vb. için).'))
        ignore_hint.setObjectName('hintLabel')
        ignore_hint.setWordWrap(True)
        ignore_layout.addWidget(ignore_hint)
        layout.addWidget(ignore_group)

        reserve_group = QGroupBox(_('Koru Kuralları (CSS seçici)'))
        reserve_layout = QVBoxLayout(reserve_group)
        self.reserve_rules_edit = QPlainTextEdit()
        self.reserve_rules_edit.setPlaceholderText('ruby\n.keep-original')
        self.reserve_rules_edit.setMinimumHeight(70)
        reserve_layout.addWidget(self.reserve_rules_edit)
        reserve_hint = QLabel(_(
            'Her satıra bir CSS seçici. Eşleşen elemanların biçimi '
            '(linkler, ruby vb. varsayılan korumaya ek olarak) çeviri '
            'sırasında olduğu gibi korunur.'))
        reserve_hint.setObjectName('hintLabel')
        reserve_hint.setWordWrap(True)
        reserve_layout.addWidget(reserve_hint)
        layout.addWidget(reserve_group)

        filter_group = QGroupBox(_('Filtre Kuralları (metin)'))
        filter_layout = QVBoxLayout(filter_group)
        self.filter_rules_edit = QPlainTextEdit()
        self.filter_rules_edit.setPlaceholderText(
            'Reklam\n^Bölüm \\d+$')
        self.filter_rules_edit.setMinimumHeight(70)
        filter_layout.addWidget(self.filter_rules_edit)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(_('Eşleştirme modu:')))
        self._filter_mode_button_group = QButtonGroup(self)
        self.filter_mode_normal_radio = QRadioButton(_('Normal'))
        self.filter_mode_case_radio = QRadioButton(_('Büyük/küçük harf duyarlı'))
        self.filter_mode_regex_radio = QRadioButton(_('Regex'))
        for radio in (
                self.filter_mode_normal_radio, self.filter_mode_case_radio,
                self.filter_mode_regex_radio):
            self._filter_mode_button_group.addButton(radio)
            mode_row.addWidget(radio)
        mode_row.addStretch()
        filter_layout.addLayout(mode_row)
        filter_hint = QLabel(_(
            'Her satıra bir kural. Eşleşen paragraflar çeviriye '
            'gönderilmez, olduğu gibi kalır. "Normal" satırı düz metin '
            'olarak arar, "Regex" düzenli ifade olarak yorumlar.'))
        filter_hint.setObjectName('hintLabel')
        filter_hint.setWordWrap(True)
        filter_layout.addWidget(filter_hint)
        layout.addWidget(filter_group)

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

    # -- load / save ----------------------------------------------------------

    def _load_values(self):
        c = self.config
        same_folder = c.get('to_source_folder', True)
        self.same_folder_radio.setChecked(same_folder)
        self.custom_folder_radio.setChecked(not same_folder)
        self.output_path_edit.setText(c.get('output_path') or '')

        if self._original_theme == 'dark':
            self.dark_theme_radio.setChecked(True)
        else:
            self.light_theme_radio.setChecked(True)

        self.show_notification_check.setChecked(
            c.get('show_notification', True))

        proxy_enabled = c.get('proxy_enabled', False)
        self.proxy_enabled_check.setChecked(proxy_enabled)
        self.proxy_host_edit.setEnabled(proxy_enabled)
        self.proxy_port_spin.setEnabled(proxy_enabled)
        proxy_setting = c.get('proxy_setting') or []
        if len(proxy_setting) == 2:
            self.proxy_host_edit.setText(proxy_setting[0])
            try:
                self.proxy_port_spin.setValue(int(proxy_setting[1]))
            except (TypeError, ValueError):
                pass

        close_behavior = c.get('close_button_behavior', 'exit')
        self.close_tray_radio.setChecked(close_behavior == 'tray')
        self.close_exit_radio.setChecked(close_behavior != 'tray')

        self.webnovel_check_enabled_check.setChecked(
            c.get('webnovel_check_enabled', False))
        interval_index = self.webnovel_check_interval_combo.findData(
            c.get('webnovel_check_interval_hours', 6))
        self.webnovel_check_interval_combo.setCurrentIndex(max(interval_index, 0))

        position = c.get('translation_position', 'only')
        self.position_radios.get(
            position, self.position_radios['only']).setChecked(True)
        self.original_color_edit.setText(c.get('original_color') or '')
        self.translation_color_edit.setText(c.get('translation_color') or '')

        self.ignore_rules_edit.setPlainText(
            self._rules_to_lines(c.get('ignore_rules')))
        self.reserve_rules_edit.setPlainText(
            self._rules_to_lines(c.get('reserve_rules')))
        self.filter_rules_edit.setPlainText(
            self._rules_to_lines(c.get('filter_rules')))
        filter_mode = c.get('rule_mode', 'normal')
        self.filter_mode_case_radio.setChecked(filter_mode == 'case')
        self.filter_mode_regex_radio.setChecked(filter_mode == 'regex')
        self.filter_mode_normal_radio.setChecked(
            filter_mode not in ('case', 'regex'))

        self.cache_enabled_check.setChecked(c.get('cache_enabled', True))

        self._custom_engines_draft = dict(c.get('custom_engines', {}))
        self._refresh_custom_engine_list()

        current_engine = c.get('translate_engine') or 'Google(Free)New'
        index = self.engine_select.findData(current_engine)
        self.engine_select.setCurrentIndex(max(index, 0))
        # merge_enabled/merge_length are global, not per-engine -- loaded
        # once here, not inside _load_engine_preferences() (which also
        # runs every time the "Ayarlanacak motor" dropdown changes, and
        # used to re-read these two from disk on every switch, silently
        # discarding whatever the user had just typed into them).
        self.merge_enabled_check.setChecked(c.get('merge_enabled', True))
        self.merge_length_spin.setValue(c.get('merge_length', 1800))
        self._load_engine_preferences()

    def _load_engine_preferences(self):
        engine_class = self._current_engine_class()
        prefs = self.config.get('engine_preferences', {}).get(
            engine_class.name, {})

        self.test_result_label.setText('')

        self.api_key_group.setVisible(engine_class.need_api_key)
        api_keys = prefs.get('api_keys', [])
        self.api_key_edit.setText(api_keys[0] if api_keys else '')
        key_hint = getattr(engine_class, 'key_hint', '') or ''
        self.api_key_hint_label.setText(key_hint)
        self.api_key_hint_label.setVisible(bool(key_hint))

        self.model_group.setVisible(hasattr(engine_class, 'model'))
        self.model_combo.clear()
        self.model_combo.addItems(getattr(engine_class, 'models', []) or [])
        self.model_combo.setCurrentText(
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
        self.model_combo.setCurrentText(getattr(engine_class, 'model', '') or '')

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
        for engine in get_all_engines():
            if engine.name == engine_name:
                return engine
        # Not saved yet -- a custom engine added/edited in this dialog
        # session but not yet persisted by Kaydet.
        custom_data = self._custom_engines_draft.get(engine_name)
        if custom_data is not None:
            return build_custom_engine_class(custom_data)
        raise ValueError('Unknown engine: %s' % engine_name)

    # -- custom engines ---------------------------------------------------

    def _refresh_custom_engine_list(self):
        self.custom_engine_list.clear()
        self.custom_engine_list.addItems(sorted(self._custom_engines_draft))

    def _sync_engine_select_with_draft(self, old_name, new_data):
        """Keeps the engine dropdown in step with add/edit/remove on the
        custom-engines draft, without waiting for Kaydet -- so a newly
        added/renamed custom engine is selectable immediately.
        """
        if old_name is not None:
            index = self.engine_select.findData(old_name)
            if index >= 0:
                self.engine_select.removeItem(index)
        if new_data is not None:
            self.engine_select.addItem(new_data['name'], new_data['name'])

    def _add_custom_engine(self):
        existing_names = (
            [e.name for e in builtin_engines]
            + list(self._custom_engines_draft))
        dialog = CustomEngineDialog(
            existing_names=existing_names, parent=self)
        if dialog.exec() and dialog.result_data:
            data = dialog.result_data
            self._custom_engines_draft[data['name']] = data
            self._refresh_custom_engine_list()
            self._sync_engine_select_with_draft(None, data)

    def _edit_custom_engine(self):
        item = self.custom_engine_list.currentItem()
        if item is None:
            return
        old_name = item.text()
        existing_names = (
            [e.name for e in builtin_engines]
            + [n for n in self._custom_engines_draft if n != old_name])
        dialog = CustomEngineDialog(
            existing_data=self._custom_engines_draft[old_name],
            existing_names=existing_names, parent=self)
        if dialog.exec() and dialog.result_data:
            data = dialog.result_data
            del self._custom_engines_draft[old_name]
            self._custom_engines_draft[data['name']] = data
            self._refresh_custom_engine_list()
            self._sync_engine_select_with_draft(old_name, data)

    def _remove_custom_engine(self):
        item = self.custom_engine_list.currentItem()
        if item is None:
            return
        name = item.text()
        # Distinct from "is this engine selected in the dropdown right
        # here in Settings" (was_selected below) -- this is whether it's
        # the *actual* translate engine the main window/queue would use
        # right now. Deleting it out from under that used to silently
        # fall back to Google(Free) with zero indication anything had
        # changed (only discovered once a translation came out in the
        # wrong place/language). The actual fallback is applied in
        # _save_and_close(), since this deletion is only a draft until
        # Kaydet is clicked.
        message = _('"{}" özel motorunu silmek istediğine emin misin?').format(name)
        if self.config.get('translate_engine') == name:
            message += '\n\n' + _(
                'Bu motor şu anda çeviri için seçili -- "Kaydet"e basınca '
                '"Google (Free)" motoruna geri dönülecek.')
        answer = QMessageBox.question(self, _('Onay'), message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._custom_engines_draft[name]
        self._refresh_custom_engine_list()
        was_selected = self.engine_select.currentData() == name
        self._sync_engine_select_with_draft(name, None)
        if was_selected:
            self.engine_select.setCurrentIndex(0)

    # -- engine test ----------------------------------------------------------

    def _build_current_engine_prefs(self, engine_class):
        prefs = {}
        api_key_text = self.api_key_edit.text().strip()
        prefs['api_keys'] = [api_key_text] if api_key_text else []
        if hasattr(engine_class, 'model'):
            prefs['model'] = self.model_combo.currentText().strip()
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

        # Engine settings live on the class itself (set_config() is a
        # classmethod), not a per-instance copy -- swapping it to this
        # test's prefs while a queue translation is running in the main
        # window would have the *next file* QueueWorker picks up built
        # with the test's API key/model instead of the real one, since
        # get_translator() constructs a fresh engine instance per file
        # and reads whatever cls.config currently holds.
        main_window = self.parent()
        if (main_window is not None
                and getattr(main_window, 'worker', None) is not None
                and main_window.worker.isRunning()):
            QMessageBox.warning(
                self, _('Test Et'),
                _('Çeviri kuyruğu çalışırken motor testi yapılamaz -- '
                  'kuyruktaki bir dosya bu motoru kullanıyor olabilir. '
                  'Kuyruk bitince ya da durdurunca tekrar dene.'))
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

    def _selected_filter_mode(self):
        if self.filter_mode_case_radio.isChecked():
            return 'case'
        if self.filter_mode_regex_radio.isChecked():
            return 'regex'
        return 'normal'

    @staticmethod
    def _rules_to_lines(rules):
        return '\n'.join(rules or [])

    @staticmethod
    def _lines_to_rules(text):
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _save_and_close(self):
        if self._test_in_progress():
            return
        if self.filter_mode_regex_radio.isChecked():
            for rule in self._lines_to_rules(
                    self.filter_rules_edit.toPlainText()):
                try:
                    re.compile(rule)
                except re.error as e:
                    QMessageBox.warning(
                        self, _('Geçersiz Regex'),
                        _('Filtre kuralı "{}" geçerli bir regex değil:\n{}')
                        .format(rule, e))
                    return
        if (self.proxy_enabled_check.isChecked()
                and not self.proxy_host_edit.text().strip()):
            # proxy_setting only ever gets saved as [host, port] when the
            # host field is non-empty (further down) -- with the
            # checkbox left on and no host, that silently saved an empty
            # [] setting, so "Proxy kullan" looked enabled but quietly
            # did nothing.
            QMessageBox.warning(
                self, _('Proxy Sunucusu Eksik'),
                _('"Proxy kullan" işaretli ama sunucu adresi boş -- bir '
                  'adres gir ya da proxy\'yi kapat.'))
            return
        c = self.config
        c.update(
            to_source_folder=self.same_folder_radio.isChecked(),
            output_path=self.output_path_edit.text().strip() or None,
            translation_position=self._selected_position(),
            original_color=self.original_color_edit.text().strip() or None,
            translation_color=self.translation_color_edit.text().strip() or None,
            ignore_rules=self._lines_to_rules(
                self.ignore_rules_edit.toPlainText()),
            reserve_rules=self._lines_to_rules(
                self.reserve_rules_edit.toPlainText()),
            filter_rules=self._lines_to_rules(
                self.filter_rules_edit.toPlainText()),
            rule_mode=self._selected_filter_mode(),
            custom_engines=dict(self._custom_engines_draft),
            cache_enabled=self.cache_enabled_check.isChecked(),
            merge_enabled=self.merge_enabled_check.isChecked(),
            merge_length=self.merge_length_spin.value(),
            ui_theme='dark' if self.dark_theme_radio.isChecked() else 'light',
            show_notification=self.show_notification_check.isChecked(),
            proxy_enabled=self.proxy_enabled_check.isChecked(),
            proxy_setting=(
                [self.proxy_host_edit.text().strip(),
                 str(self.proxy_port_spin.value())]
                if self.proxy_host_edit.text().strip() else []),
            close_button_behavior=(
                'tray' if self.close_tray_radio.isChecked() else 'exit'),
            webnovel_check_enabled=self.webnovel_check_enabled_check.isChecked(),
            webnovel_check_interval_hours=(
                self.webnovel_check_interval_combo.currentData()),
        )

        # If the currently-active translate engine was a custom one that
        # just got deleted above, fall back to the default rather than
        # leaving translate_engine pointing at a name nothing resolves to
        # -- get_engine_class() already has a similar fallback for an
        # unrecognized name, but silently, with no indication to the user
        # that their engine choice just changed.
        builtin_names = {engine.name for engine in builtin_engines}
        if c.get('translate_engine') not in (
                builtin_names | set(self._custom_engines_draft)):
            c.save(translate_engine='Google(Free)New')

        engine_class = self._current_engine_class()
        engine_preferences = c.get('engine_preferences', {})
        prefs = engine_preferences.setdefault(engine_class.name, {})
        api_key_text = self.api_key_edit.text().strip()
        prefs['api_keys'] = [api_key_text] if api_key_text else []
        if hasattr(engine_class, 'model'):
            prefs['model'] = self.model_combo.currentText().strip()
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
