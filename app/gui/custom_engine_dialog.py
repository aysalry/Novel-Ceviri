import json

from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout)

from ..core.i18n import _
from ..engines.custom import create_engine_template, load_engine_data


class CustomEngineDialog(QDialog):
    """Editor for one user-defined engine's JSON description (see
    engines/custom.py for the schema/validation). Used both for adding a
    new custom engine and for editing an existing one.
    """

    def __init__(self, existing_data=None, existing_names=(), parent=None):
        super().__init__(parent)
        self.existing_names = existing_names
        self.result_data = None
        self.setWindowTitle(_('Özel Motor'))
        self.setMinimumSize(560, 480)

        layout = QVBoxLayout(self)
        hint = QLabel(_(
            'Herhangi bir çeviri API\'sini JSON ile tanımla. "<source>", '
            '"<target>" ve "<text>" yer tutucuları istek gönderilirken '
            'gerçek değerlerle değiştirilir. "response_path", cevaptaki '
            'çeviriyi bulmak için nokta ile ayrılmış bir yol (örn. '
            '"data.translations[0].text"). API anahtarını "headers" '
            'içine kendin yazmalısın -- bu JSON\'u paylaşırken anahtarını '
            'çıkarmayı unutma.'))
        hint.setWordWrap(True)
        hint.setObjectName('hintLabel')
        layout.addWidget(hint)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(create_engine_template())
        if existing_data is not None:
            self.editor.setPlainText(
                json.dumps(existing_data, indent=2, ensure_ascii=False))
        layout.addWidget(self.editor)

        row_buttons = QHBoxLayout()
        template_btn = QPushButton(_('Şablon Ekle'))
        template_btn.clicked.connect(self._insert_template)
        row_buttons.addWidget(template_btn)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)

        action_buttons = QHBoxLayout()
        action_buttons.addStretch()
        cancel_btn = QPushButton(_('İptal'))
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(_('Kaydet'))
        save_btn.setObjectName('primaryButton')
        save_btn.clicked.connect(self._validate_and_accept)
        action_buttons.addWidget(cancel_btn)
        action_buttons.addWidget(save_btn)
        layout.addLayout(action_buttons)

    def _insert_template(self):
        self.editor.setPlainText(create_engine_template())

    def _validate_and_accept(self):
        ok, result = load_engine_data(
            self.editor.toPlainText(), self.existing_names)
        if not ok:
            QMessageBox.warning(self, _('Geçersiz Motor Verisi'), result)
            return
        self.result_data = result
        self.accept()
