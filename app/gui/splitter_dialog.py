import os

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QVBoxLayout)

from ..core.i18n import _
from ..core.utils import open_file
from ..formats.txt import CHAPTER_PATTERN_PRESETS, split_into_chapters


class SplitterDialog(QDialog):
    """Splits one big raw-text dump (a common way webnovel raws get shared)
    into per-chapter .txt files, which can then be dropped straight into
    the main queue instead of translating one giant blob at once.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Ham Metni Bölümlere Ayır'))
        self.setMinimumSize(560, 480)
        self.source_path = None
        self.chapters: list[tuple[str, str]] = []
        self.written_files: list[str] = []

        layout = QVBoxLayout(self)

        file_row = QHBoxLayout()
        self.file_label = QLabel(_('Henüz dosya seçilmedi.'))
        choose_btn = QPushButton(_('Ham Metin Dosyası Seç...'))
        choose_btn.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_label, stretch=1)
        file_row.addWidget(choose_btn)
        layout.addLayout(file_row)

        pattern_row = QHBoxLayout()
        pattern_row.addWidget(QLabel(_('Bölüm başlığı kalıbı:')))
        self.pattern_combo = QComboBox()
        self.pattern_combo.setEditable(True)
        for name, pattern in CHAPTER_PATTERN_PRESETS.items():
            self.pattern_combo.addItem(name, pattern)
        pattern_row.addWidget(self.pattern_combo, stretch=1)
        preview_btn = QPushButton(_('Önizle'))
        preview_btn.clicked.connect(self._preview)
        pattern_row.addWidget(preview_btn)
        layout.addLayout(pattern_row)

        self.preview_list = QListWidget()
        layout.addWidget(self.preview_list, stretch=1)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel(_('Çıktı klasörü:')))
        self.output_dir_edit = QLineEdit()
        out_row.addWidget(self.output_dir_edit, stretch=1)
        out_browse_btn = QPushButton(_('Seç...'))
        out_browse_btn.clicked.connect(self._choose_output_dir)
        out_row.addWidget(out_browse_btn)
        layout.addLayout(out_row)

        action_row = QHBoxLayout()
        action_row.addStretch()
        close_btn = QPushButton(_('Kapat'))
        close_btn.clicked.connect(self.reject)
        self.split_btn = QPushButton(_('Bölümlere Ayır ve Kaydet'))
        self.split_btn.setObjectName('primaryButton')
        self.split_btn.clicked.connect(self._split_and_save)
        action_row.addWidget(close_btn)
        action_row.addWidget(self.split_btn)
        layout.addLayout(action_row)

    def _choose_file(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, _('Ham Metin Dosyası Seç'), '', 'Metin Dosyası (*.txt)')
        if not path:
            return
        self.source_path = path
        self.file_label.setText(os.path.basename(path))
        if not self.output_dir_edit.text():
            self.output_dir_edit.setText(
                os.path.join(os.path.dirname(path), 'bolumler'))

    def _choose_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, _('Çıktı Klasörü Seç'))
        if path:
            self.output_dir_edit.setText(path)

    def _current_pattern(self):
        index = self.pattern_combo.currentIndex()
        data = self.pattern_combo.itemData(index)
        return data or self.pattern_combo.currentText()

    def _preview(self):
        if not self.source_path:
            QMessageBox.warning(self, _('Uyarı'), _('Önce bir dosya seç.'))
            return
        text = open_file(self.source_path)
        try:
            self.chapters = split_into_chapters(text, self._current_pattern())
        except Exception as e:
            QMessageBox.critical(self, _('Hata'), str(e))
            return
        self.preview_list.clear()
        for index, (title, body) in enumerate(self.chapters, start=1):
            label = title or _('(başlıksız bölüm)')
            self.preview_list.addItem(
                '%02d. %s — %d karakter' % (index, label, len(body)))

    def _split_and_save(self):
        if not self.chapters:
            self._preview()
        if not self.chapters:
            return
        output_dir = self.output_dir_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, _('Uyarı'), _('Önce çıktı klasörü seç.'))
            return
        os.makedirs(output_dir, exist_ok=True)

        written = []
        for index, (title, body) in enumerate(self.chapters, start=1):
            safe_title = ''.join(
                c for c in (title or '') if c.isalnum() or c in ' _-').strip()
            filename = '%02d_%s.txt' % (index, safe_title[:60] or 'bolum')
            out_path = os.path.join(output_dir, filename)
            with open(out_path, 'w', encoding='utf-8', newline='\n') as file:
                if title:
                    file.write(title + '\n\n')
                file.write(body)
            written.append(out_path)

        self.written_files = written
        QMessageBox.information(
            self, _('Tamamlandı'),
            _('{} bölüm "{}" klasörüne kaydedildi.')
            .format(len(written), output_dir))
        self.accept()
