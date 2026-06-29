"""Built-in EPUB reader: a standalone, non-modal window rendering chapters
with real CSS/images/fonts via QWebEngineView. PreviewDialog (plain-text,
no rendering) stays in use for TXT/SRT, which have no markup worth
rendering anyway.

EPUB parsing here is deliberately separate from formats/epub.py's
EpubBook: that class exists to mutate and re-save a book for translation
and walks pages in manifest order, not reading order. The reader instead
needs the spine (actual reading order) and TOC hrefs (for chapter
titles) -- different enough information that duplicating the small
amount of XML-walking code is safer than reshaping the class the live
translation pipeline depends on.
"""
import os
import posixpath
import shutil
import tempfile
import zipfile

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ..core.config import get_config
from ..core.i18n import _
from ..core import reading_progress
from ..core.utils import parse_xml_lenient

XHTML_NS = 'http://www.w3.org/1999/xhtml'
OPF_NS = 'http://www.idpf.org/2007/opf'
NCX_NS = 'http://www.daisy.org/z3986/2005/ncx/'
EPUB_OPS_NS = 'http://www.idpf.org/2007/ops'
CONTAINER_NS = 'urn:oasis:names:tc:opendocument:xmlns:container'

THEMES = {
    'light': ('#ffffff', '#1a1a1a'),
    'dark': ('#1e1e1e', '#e8e8e8'),
    'sepia': ('#f4ecd8', '#5b4636'),
}
THEME_LABELS = [
    ('light', _('Açık')),
    ('dark', _('Karanlık')),
    ('sepia', _('Sepya')),
]

# First entry (None) leaves the book's own CSS font alone -- most EPUBs
# ship a font choice the author/translator picked on purpose, so
# overriding it should be something the reader opts into, not the
# default. The rest are common, widely-installed fonts rather than a
# QFontDatabase dump of every font on the system, which would be a huge,
# inconsistent list across machines.
FONT_FAMILIES = [
    (None, _('Kitabın kendi yazı tipi')),
    ('Georgia, serif', _('Georgia')),
    ('"Times New Roman", Times, serif', _('Times New Roman')),
    ('"Segoe UI", Arial, sans-serif', _('Segoe UI')),
    ('Verdana, Geneva, sans-serif', _('Verdana')),
    ('"Comic Sans MS", sans-serif', _('Comic Sans MS')),
    ('"Courier New", Courier, monospace', _('Courier New')),
]


def _join(base_dir, href):
    return posixpath.normpath(posixpath.join(base_dir, href.split('#')[0]))


class _Chapter:
    def __init__(self, title, href):
        self.title = title
        self.href = href


def _parse_chapters(zf):
    """Returns list[_Chapter] in spine (reading) order, titled from the
    TOC when available and falling back to the bare filename otherwise.
    """
    container = parse_xml_lenient(zf.read('META-INF/container.xml'))
    rootfile = container.find('.//{%s}rootfile' % CONTAINER_NS)
    opf_path = rootfile.get('full-path')
    opf_dir = posixpath.dirname(opf_path)
    opf_root = parse_xml_lenient(zf.read(opf_path))

    manifest_el = opf_root.find('{%s}manifest' % OPF_NS)
    items_by_id = {
        item.get('id'): item for item in manifest_el
        if isinstance(item.tag, str)}

    spine_el = opf_root.find('{%s}spine' % OPF_NS)
    hrefs = []
    for itemref in spine_el.findall('{%s}itemref' % OPF_NS):
        item = items_by_id.get(itemref.get('idref'))
        if item is not None:
            hrefs.append(_join(opf_dir, item.get('href')))

    titles_by_href = _parse_toc_titles(zf, opf_dir, items_by_id)
    return [
        _Chapter(titles_by_href.get(href) or posixpath.basename(href), href)
        for href in hrefs]


def _parse_toc_titles(zf, opf_dir, items_by_id):
    """Best-effort href -> title map from nav.xhtml (EPUB3) or toc.ncx
    (EPUB2), whichever is present. Returns {} on any parse failure --
    callers fall back to filenames, an uglier but harmless sidebar label.
    """
    try:
        for item in items_by_id.values():
            if 'nav' in (item.get('properties') or '').split():
                return _parse_nav_titles(zf, opf_dir, item.get('href'))
        for item in items_by_id.values():
            if item.get('media-type') == 'application/x-dtbncx+xml':
                return _parse_ncx_titles(zf, opf_dir, item.get('href'))
    except Exception:
        pass
    return {}


def _parse_nav_titles(zf, opf_dir, href):
    root = parse_xml_lenient(zf.read(_join(opf_dir, href)))
    nav_dir = posixpath.dirname(_join(opf_dir, href))
    titles = {}
    for nav in root.iter('{%s}nav' % XHTML_NS):
        if 'toc' not in (nav.get('{%s}type' % EPUB_OPS_NS) or '').split():
            continue
        for a in nav.iter('{%s}a' % XHTML_NS):
            target_href = a.get('href')
            if target_href and a.text and a.text.strip():
                titles[_join(nav_dir, target_href)] = a.text.strip()
    return titles


def _parse_ncx_titles(zf, opf_dir, href):
    root = parse_xml_lenient(zf.read(_join(opf_dir, href)))
    ncx_dir = posixpath.dirname(_join(opf_dir, href))
    nav_map = root.find('{%s}navMap' % NCX_NS)
    if nav_map is None:
        return {}
    titles = {}
    for nav_point in nav_map.iter('{%s}navPoint' % NCX_NS):
        text_el = nav_point.find('{%s}navLabel/{%s}text' % (NCX_NS, NCX_NS))
        content_el = nav_point.find('{%s}content' % NCX_NS)
        if text_el is None or content_el is None or not text_el.text:
            continue
        target_href = content_el.get('src')
        if target_href:
            titles[_join(ncx_dir, target_href)] = text_el.text.strip()
    return titles


class EpubReaderWindow(QWidget):
    """Independent top-level window -- callers must keep a reference
    (e.g. self._reader = EpubReaderWindow(path)) or Qt will garbage
    collect it the moment the opening function returns.
    """

    def __init__(self, epub_path, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.epub_path = epub_path
        self.setWindowTitle(os.path.basename(epub_path))
        self.resize(1000, 750)

        self._temp_dir = tempfile.mkdtemp(prefix='novelceviri_reader_')
        self._chapters: list[_Chapter] = []
        self._current_index = 0
        # Read as the last-saved reading preference instead of a fixed
        # default -- picking dark mode (or a bigger font) once shouldn't
        # mean re-picking it every single time a book is opened.
        config = get_config()
        self._font_pct = config.get('reader_font_pct', 100)
        self._theme = config.get('reader_theme', 'light')
        self._font_family = config.get('reader_font_family')

        try:
            with zipfile.ZipFile(epub_path, 'r') as zf:
                zf.extractall(self._temp_dir)
                self._chapters = _parse_chapters(zf)
        except Exception as e:
            QMessageBox.warning(
                self, _('EPUB açılamadı'),
                _('Bu dosya okunamadı:\n{}').format(e))

        self._build_ui()

        if self._chapters:
            start_index = reading_progress.get_chapter_index(epub_path)
            if not (0 <= start_index < len(self._chapters)):
                start_index = 0
            self.toc_list.setCurrentRow(start_index)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.prev_btn = QPushButton(_('◀ Önceki Bölüm'))
        self.prev_btn.clicked.connect(self._go_previous)
        controls.addWidget(self.prev_btn)

        self.next_btn = QPushButton(_('Sonraki Bölüm ▶'))
        self.next_btn.clicked.connect(self._go_next)
        controls.addWidget(self.next_btn)

        self.position_label = QLabel('')
        controls.addWidget(self.position_label)
        controls.addStretch()

        minus_btn = QPushButton(_('A-'))
        minus_btn.setToolTip(_('Yazıyı küçült'))
        minus_btn.clicked.connect(lambda: self._change_font(-10))
        controls.addWidget(minus_btn)

        plus_btn = QPushButton(_('A+'))
        plus_btn.setToolTip(_('Yazıyı büyüt'))
        plus_btn.clicked.connect(lambda: self._change_font(10))
        controls.addWidget(plus_btn)

        controls.addWidget(QLabel(_('Tema:')))
        self.theme_combo = QComboBox()
        for key, label in THEME_LABELS:
            self.theme_combo.addItem(label, key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self._theme)))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        controls.addWidget(self.theme_combo)

        controls.addWidget(QLabel(_('Yazı Tipi:')))
        self.font_combo = QComboBox()
        for family, label in FONT_FAMILIES:
            self.font_combo.addItem(label, family)
        self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(self._font_family)))
        self.font_combo.currentIndexChanged.connect(self._on_font_changed)
        controls.addWidget(self.font_combo)

        layout.addLayout(controls)

        splitter = QSplitter()
        self.toc_list = QListWidget()
        for chapter in self._chapters:
            self.toc_list.addItem(chapter.title)
        self.toc_list.currentRowChanged.connect(self._on_chapter_selected)
        splitter.addWidget(self.toc_list)

        self.web_view = QWebEngineView()
        splitter.addWidget(self.web_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 780])
        layout.addWidget(splitter, stretch=1)

        self._update_nav_buttons()

    def _on_chapter_selected(self, index):
        if not (0 <= index < len(self._chapters)):
            return
        self._current_index = index
        self._render_current_chapter()
        self._update_nav_buttons()
        reading_progress.set_chapter_index(
            self.epub_path, index, total_chapters=len(self._chapters))

    def _go_previous(self):
        if self._current_index > 0:
            self.toc_list.setCurrentRow(self._current_index - 1)

    def _go_next(self):
        if self._current_index < len(self._chapters) - 1:
            self.toc_list.setCurrentRow(self._current_index + 1)

    def _update_nav_buttons(self):
        self.prev_btn.setEnabled(self._current_index > 0)
        self.next_btn.setEnabled(self._current_index < len(self._chapters) - 1)
        if self._chapters:
            self.position_label.setText(
                _('Bölüm {}/{}').format(
                    self._current_index + 1, len(self._chapters)))

    def _change_font(self, delta):
        self._font_pct = max(50, min(250, self._font_pct + delta))
        get_config().save(reader_font_pct=self._font_pct)
        self._render_current_chapter()

    def _on_theme_changed(self, index):
        self._theme = self.theme_combo.itemData(index)
        get_config().save(reader_theme=self._theme)
        self._render_current_chapter()

    def _on_font_changed(self, index):
        self._font_family = self.font_combo.itemData(index)
        get_config().save(reader_font_family=self._font_family)
        self._render_current_chapter()

    def _render_current_chapter(self):
        if not (0 <= self._current_index < len(self._chapters)):
            return
        chapter = self._chapters[self._current_index]
        source_path = os.path.join(self._temp_dir, chapter.href)
        try:
            with open(source_path, 'r', encoding='utf-8', errors='replace') as f:
                html = f.read()
        except OSError as e:
            self.web_view.setHtml(_('Bölüm yüklenemedi: {}').format(e))
            return

        html = self._inject_style(html)
        # Written as a sibling file (rather than QWebEngineView.setHtml(),
        # which silently truncates content past ~2MB) and loaded by file://
        # URL so relative image/CSS links in the chapter keep resolving.
        rendered_path = source_path + '.reader.html'
        with open(rendered_path, 'w', encoding='utf-8') as f:
            f.write(html)
        self.web_view.load(QUrl.fromLocalFile(rendered_path))

    def _inject_style(self, html):
        bg, fg = THEMES[self._theme]
        font_rule = ''
        if self._font_family:
            # body * (not just body) -- some EPUBs set font-family on
            # individual <p>/<span> tags rather than just the body, which
            # would otherwise win over a body-only override by CSS
            # specificity even with !important on both (same specificity,
            # later/more specific selector wins).
            font_rule = (
                'body, body * { font-family: %s !important; }'
                % self._font_family)
        style = (
            '<style id="novelceviri-reader-override">'
            'html, body { background: %s !important; color: %s !important; }'
            'body { font-size: %d%% !important; line-height: 1.6 !important; '
            'padding: 0 24px !important; }'
            '%s'
            '</style>' % (bg, fg, self._font_pct, font_rule))
        lowered = html.lower()
        head_close = lowered.find('</head>')
        if head_close != -1:
            return html[:head_close] + style + html[head_close:]
        return style + html

    def closeEvent(self, event):
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        super().closeEvent(event)


def open_preview(path, parent=None):
    """Single dispatch point both queue tabs use: real reading experience
    for EPUB, the older plain-text PreviewDialog for everything else.
    Returns the opened widget -- callers must keep a reference to it.
    """
    if os.path.splitext(path)[1].lower() == '.epub':
        window = EpubReaderWindow(path, parent)
        window.show()
        return window
    from .preview_dialog import PreviewDialog
    dialog = PreviewDialog(path, parent)
    dialog.exec()
    return dialog
