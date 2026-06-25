import os

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout)

from ..core.i18n import _
from ..core.utils import trim

XHTML_BODY_TAG = '{http://www.w3.org/1999/xhtml}body'


def _page_text(page):
    root = page.data
    body = root.find('./%s' % XHTML_BODY_TAG)
    if body is None:
        body = root.find('./body')
    if body is None:
        body = root
    # page.data is a plain lxml.etree element (EpubBook parses with etree,
    # not lxml.html), so it has no .text_content() -- itertext() is the
    # etree-native equivalent (same approach core/element.py already uses).
    return trim(''.join(body.itertext()))


class PreviewDialog(QDialog):
    """Read-only viewer for a completed translation output -- lets the
    user spot-check a few chapters without opening a separate EPUB/text
    reader.
    """

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Önizleme: {}').format(os.path.basename(path)))
        self.setMinimumSize(640, 560)
        self.resize(720, 640)
        self.path = path
        self._sections: list[tuple[str, str]] = []

        layout = QVBoxLayout(self)

        nav_row = QHBoxLayout()
        nav_row.addWidget(QLabel(_('Bölüm:')))
        self.section_combo = QComboBox()
        nav_row.addWidget(self.section_combo, stretch=1)
        layout.addLayout(nav_row)

        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        layout.addWidget(self.text_view, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton(_('Kapat'))
        close_btn.setObjectName('primaryButton')
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._load()
        self.section_combo.currentIndexChanged.connect(self._show_section)

    def _load(self):
        extension = os.path.splitext(self.path)[1].lower()
        try:
            if extension == '.epub':
                self._load_epub()
            elif extension == '.srt':
                self._load_srt()
            else:
                self._load_txt()
        except Exception as e:
            self._sections = [(_('Hata'), str(e))]

        for title, _text in self._sections:
            self.section_combo.addItem(title)
        if self._sections:
            self._show_section(0)

    def _load_epub(self):
        from ..formats.epub import EpubBook
        book = EpubBook(self.path)
        for index, page in enumerate(book.pages, start=1):
            text = _page_text(page)
            if text:
                self._sections.append((page.href or str(index), text))
        if not self._sections:
            self._sections.append((_('(içerik bulunamadı)'), ''))

    def _load_srt(self):
        from ..core.element import get_srt_elements
        elements = get_srt_elements(self.path, 'utf-8')
        text = '\n\n'.join(element.get_translation() for element in elements)
        self._sections.append((_('Tüm altyazı'), text))

    def _load_txt(self):
        with open(self.path, 'r', encoding='utf-8', errors='replace') as file:
            content = file.read()
        self._sections.append((_('Tüm metin'), content))

    def _show_section(self, index):
        if 0 <= index < len(self._sections):
            self.text_view.setPlainText(self._sections[index][1])
