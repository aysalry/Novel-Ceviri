"""First-launch welcome dialog: quick orientation plus an optional
engine + API key choice, so a brand new user isn't dropped straight
into the main window with no context. Fully skippable -- the app
already has sensible defaults (free Google engine, Turkish target)
without it.
"""
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout)

from ..core.config import get_config
from ..core.i18n import _
from ..engines import get_all_engines


class WelcomeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Novel Çeviri\'ye Hoş Geldin'))
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        title = QLabel('Novel Çeviri')
        title.setObjectName('aboutTitle')
        layout.addWidget(title)

        intro = QLabel(_(
            'Webnovel/lightnovel çevirisi için bağımsız bir araç. '
            'Varsayılan olarak ücretsiz Google motoruyla, anahtar '
            'gerekmeden hemen çeviriye başlayabilirsin -- istersen '
            'aşağıdan başka bir motor seçip API anahtarını şimdi '
            'girebilirsin (sonra Ayarlar\'dan da eklenebilir).'))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.engine_combo = QComboBox()
        for engine in get_all_engines():
            self.engine_combo.addItem(engine.alias, engine.name)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        form.addRow(_('Çeviri motoru:'), self.engine_combo)
        layout.addLayout(form)

        self.api_key_group = QGroupBox(_('API Anahtarı'))
        api_key_layout = QVBoxLayout(self.api_key_group)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(
            _('İstersen şimdi gir, istersen sonra Ayarlar\'dan ekle.'))
        api_key_layout.addWidget(self.api_key_edit)
        layout.addWidget(self.api_key_group)

        button_row = QHBoxLayout()
        button_row.addStretch()
        skip_btn = QPushButton(_('Atla'))
        skip_btn.clicked.connect(self._skip)
        button_row.addWidget(skip_btn)
        start_btn = QPushButton(_('Başla'))
        start_btn.setObjectName('primaryButton')
        start_btn.clicked.connect(self._start)
        button_row.addWidget(start_btn)
        layout.addLayout(button_row)

        self._on_engine_changed()

    def _current_engine_class(self):
        engine_name = self.engine_combo.currentData()
        engines = get_all_engines()
        return next(
            (e for e in engines if e.name == engine_name), engines[0])

    def _on_engine_changed(self):
        self.api_key_group.setVisible(
            self._current_engine_class().need_api_key)

    def _start(self):
        engine_class = self._current_engine_class()
        config = get_config()
        updates = {
            'translate_engine': engine_class.name,
            'first_run_completed': True,
        }

        api_key_text = self.api_key_edit.text().strip()
        if engine_class.need_api_key and api_key_text:
            engine_preferences = config.get('engine_preferences', {})
            prefs = engine_preferences.setdefault(engine_class.name, {})
            prefs['api_keys'] = [api_key_text]
            updates['engine_preferences'] = engine_preferences

        config.save(**updates)
        self.accept()

    def _skip(self):
        get_config().save(first_run_completed=True)
        self.accept()
