import os
import re

from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout)

from ..core.i18n import _


class GlossaryDialog(QDialog):
    """Editor for the glossary file consumed by core.translation.Glossary.
    File format: entries separated by blank lines, each entry is 1-2 lines
    (term, optional fixed translation). A term with no second line is kept
    untouched by translation -- handy for character/place names.
    """

    def __init__(self, path, parent=None, highlight_last_n=0):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(_('Sözlük Düzenle'))
        self.setMinimumSize(560, 460)

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
        layout.addWidget(self.table, stretch=1)

        # Row-editing actions on the left, importing from an outside file
        # on the right -- kept on one row (rather than each getting its
        # own) so the extra buttons don't push the dialog into looking
        # like a wall of controls.
        row_buttons = QHBoxLayout()
        add_btn = QPushButton(_('+ Satır Ekle'))
        add_btn.clicked.connect(lambda: self._add_row())
        select_all_btn = QPushButton(_('Tümünü Seç'))
        select_all_btn.clicked.connect(self.table.selectAll)
        remove_btn = QPushButton(_('Seçili Satırları Sil'))
        remove_btn.clicked.connect(self._remove_selected)
        row_buttons.addWidget(add_btn)
        row_buttons.addWidget(select_all_btn)
        row_buttons.addWidget(remove_btn)
        row_buttons.addStretch()
        import_btn = QPushButton(_('İçe Aktar...'))
        import_btn.setToolTip(_(
            'Başka bir sözlük dosyasından terimleri bu listeye ekler '
            '(zaten var olanlar atlanır).'))
        import_btn.clicked.connect(self._import_glossary)
        row_buttons.addWidget(import_btn)
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
        if highlight_last_n:
            self._highlight_last_rows(highlight_last_n)

    def _highlight_last_rows(self, count):
        """Selects and scrolls to the rows a glossary-extraction run just
        added -- they land at the end of the table, easy to miss among
        whatever was already there, which otherwise makes a correctly
        working extraction look like it's showing unrelated leftovers.
        """
        total = self.table.rowCount()
        first_new_row = max(0, total - count)
        self.table.clearSelection()
        for row in range(first_new_row, total):
            self.table.selectRow(row)
        self.table.scrollToItem(self.table.item(first_new_row, 0))

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

    def _existing_terms(self):
        return {
            self.table.item(row, 0).text().strip().lower()
            for row in range(self.table.rowCount())
            if self.table.item(row, 0) and self.table.item(row, 0).text().strip()}

    def _import_glossary(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, _('Sözlük Dosyası Seç'), '', 'Metin Dosyası (*.txt)')
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as file:
                content = file.read().strip(chr(0xfeff)).strip()
        except OSError as e:
            QMessageBox.warning(
                self, _('Hata'), _('Dosya okunamadı: {}').format(e))
            return

        existing_terms = self._existing_terms()
        added = 0
        for group in re.split(r'\n{2,}', content) if content else []:
            lines = group.split('\n')
            term = lines[0].strip()
            if not term or term.lower() in existing_terms:
                continue
            translation = lines[1].strip() if len(lines) > 1 else ''
            self._add_row(term, translation)
            existing_terms.add(term.lower())
            added += 1

        if added:
            QMessageBox.information(
                self, _('İçe Aktarıldı'),
                _('{} terim eklendi.').format(added))
        else:
            QMessageBox.information(
                self, _('İçe Aktarıldı'),
                _('Eklenecek yeni terim bulunamadı (hepsi zaten listede).'))

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

    def _save(self):
        """Returns True on success -- callers must not treat a failed
        write (read-only path, deleted parent folder, etc.) as if the
        edits were actually persisted."""
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
        try:
            with open(self.path, 'w', encoding='utf-8', newline='\n') as file:
                file.write('\n\n'.join(entries))
        except OSError as e:
            QMessageBox.warning(
                self, _('Kaydedilemedi'),
                _('Sözlük dosyasına yazılamadı:\n{}').format(e))
            return False
        return True

    def _save_and_close(self):
        if self._save():
            self.accept()

    def closeEvent(self, event):
        # The titlebar X doesn't go through reject()/accept() the way the
        # "İptal"/"Kaydet ve Kapat" buttons do -- most people expect
        # closing the window to keep whatever they just did (e.g. deleted
        # a pile of junk entries) rather than silently discarding it, so
        # only the explicit "İptal" button still means "throw this away".
        # If the write actually fails, don't close -- otherwise the only
        # sign anything went wrong is a warning box behind a window that
        # vanishes right after, easy to miss.
        if self._save():
            super().closeEvent(event)
        else:
            event.ignore()
