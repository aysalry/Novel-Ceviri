import os
import re

from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.i18n import _


class GlossaryDialog(QDialog):
    """Editor for the glossary file consumed by core.translation.Glossary.
    File format: entries separated by blank lines, each entry is 1-2 lines
    (term, optional fixed translation). A term with no second line is kept
    untouched by translation -- handy for character/place names.
    """

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(_('Sözlük Düzenle'))
        self.setMinimumSize(560, 440)

        layout = QVBoxLayout(self)
        hint = QLabel(_(
            'Karakter/yer adlarını burada listele. "Sabit çeviri" alanını '
            'boş bırakırsan o terim çeviri sırasında hiç değiştirilmeden '
            'bırakılır (örn. özel isimler için).'))
        hint.setWordWrap(True)
        hint.setObjectName('hintLabel')
        layout.addWidget(hint)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(
            [_('Orijinal terim'), _('Sabit çeviri (isteğe bağlı)')])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        row_buttons = QHBoxLayout()
        add_btn = QPushButton(_('+ Satır Ekle'))
        add_btn.clicked.connect(lambda: self._add_row())
        remove_btn = QPushButton(_('Seçili Satırı Sil'))
        remove_btn.clicked.connect(self._remove_selected)
        row_buttons.addWidget(add_btn)
        row_buttons.addWidget(remove_btn)
        row_buttons.addStretch()
        layout.addLayout(row_buttons)

        action_buttons = QHBoxLayout()
        action_buttons.addStretch()
        cancel_btn = QPushButton(_('İptal'))
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton(_('Kaydet ve Kapat'))
        save_btn.setObjectName('primaryButton')
        save_btn.clicked.connect(self._save_and_close)
        action_buttons.addWidget(cancel_btn)
        action_buttons.addWidget(save_btn)
        layout.addLayout(action_buttons)

        self._load()

    def _add_row(self, term='', translation=''):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(term))
        self.table.setItem(row, 1, QTableWidgetItem(translation))

    def _remove_selected(self):
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()},
            reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def _load(self):
        if not os.path.exists(self.path):
            return
        with open(self.path, 'r', encoding='utf-8', newline=None) as file:
            content = file.read().strip(chr(0xfeff)).strip()
        if not content:
            return
        for group in re.split(r'\n{2,}', content):
            lines = group.split('\n')
            term = lines[0].strip()
            translation = lines[1].strip() if len(lines) > 1 else ''
            if term:
                self._add_row(term, translation)

    def _save_and_close(self):
        entries = []
        for row in range(self.table.rowCount()):
            term_item = self.table.item(row, 0)
            term = (term_item.text() if term_item else '').strip()
            if not term:
                continue
            translation_item = self.table.item(row, 1)
            translation = (
                translation_item.text() if translation_item else '').strip()
            entries.append(
                term if not translation else '%s\n%s' % (term, translation))
        with open(self.path, 'w', encoding='utf-8', newline='\n') as file:
            file.write('\n\n'.join(entries))
        self.accept()
