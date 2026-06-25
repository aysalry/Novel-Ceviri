"""Builds a brand-new EPUB from scraped web-novel chapters. Unlike
formats/epub.py (which edits an existing EPUB in place), there is no
source container to preserve here -- this writes one from scratch, using
the same NCX-based TOC shape that formats/epub.py already knows how to
read back in, so a downloaded book can later be reopened and translated
through the normal EpubBook path.
"""
import os
import uuid
import zipfile

from ..core.utils import prepare_string_for_xml
from ..webnovel.models import ChapterContent

XHTML_NS = 'http://www.w3.org/1999/xhtml'

CONTAINER_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
'''

STYLE_CSS = (
    'body { font-family: serif; line-height: 1.5; margin: 1.2em; }\n'
    'h1 { font-size: 1.4em; margin-bottom: 1em; }\n'
    'p { margin: 0 0 0.8em 0; text-indent: 1.2em; }\n'
)


def _chapter_filename(index):
    return 'chapter_%04d.xhtml' % index


def _chapter_xhtml(title, paragraphs):
    safe_title = prepare_string_for_xml(title or '')
    body = ''.join(
        '<p>%s</p>' % prepare_string_for_xml(p)
        for p in paragraphs if p and p.strip())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        '<meta charset="utf-8"/><title>%s</title>'
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
        '<body><h1>%s</h1>%s</body></html>'
    ) % (safe_title, safe_title, body)


def build_epub(novel_info, chapters, output_path, cover_bytes=None, language='en'):
    """novel_info: webnovel.models.NovelInfo; chapters: list[ChapterContent]."""
    book_id = 'urn:uuid:%s' % uuid.uuid4()
    title = prepare_string_for_xml(novel_info.title or 'Untitled')
    author = prepare_string_for_xml(novel_info.author or '')

    manifest_items = []
    spine_items = []
    nav_points = []
    for index, chapter in enumerate(chapters, start=1):
        filename = _chapter_filename(index)
        chapter_title = prepare_string_for_xml(chapter.title or 'Chapter %d' % index)
        manifest_items.append(
            '<item id="chap%04d" href="%s" media-type="application/xhtml+xml"/>'
            % (index, filename))
        spine_items.append('<itemref idref="chap%04d"/>' % index)
        nav_points.append(
            '<navPoint id="nav%04d" playOrder="%d">'
            '<navLabel><text>%s</text></navLabel>'
            '<content src="%s"/></navPoint>'
            % (index, index, chapter_title, filename))

    cover_manifest = ''
    cover_meta = ''
    if cover_bytes:
        cover_manifest = (
            '<item id="cover-image" href="cover.jpg" '
            'media-type="image/jpeg" properties="cover-image"/>')
        cover_meta = '<meta name="cover" content="cover-image"/>'

    opf = '''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">%s</dc:identifier>
    <dc:title>%s</dc:title>
    <dc:creator>%s</dc:creator>
    <dc:language>%s</dc:language>
    %s
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="style" href="style.css" media-type="text/css"/>
    %s
    %s
  </manifest>
  <spine toc="ncx">
    %s
  </spine>
</package>
''' % (
        book_id, title, author, language, cover_meta, cover_manifest,
        '\n    '.join(manifest_items), '\n    '.join(spine_items))

    ncx = '''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="%s"/></head>
  <docTitle><text>%s</text></docTitle>
  <navMap>
    %s
  </navMap>
</ncx>
''' % (book_id, title, '\n    '.join(nav_points))

    with zipfile.ZipFile(output_path, 'w') as zf:
        mimetype_info = zipfile.ZipInfo('mimetype')
        mimetype_info.compress_type = zipfile.ZIP_STORED
        zf.writestr(mimetype_info, 'application/epub+zip')

        zf.writestr('META-INF/container.xml', CONTAINER_XML)
        zf.writestr(
            'OEBPS/content.opf', opf,
            compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(
            'OEBPS/toc.ncx', ncx, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(
            'OEBPS/style.css', STYLE_CSS, compress_type=zipfile.ZIP_DEFLATED)
        if cover_bytes:
            zf.writestr(
                'OEBPS/cover.jpg', cover_bytes,
                compress_type=zipfile.ZIP_DEFLATED)
        for index, chapter in enumerate(chapters, start=1):
            zf.writestr(
                'OEBPS/%s' % _chapter_filename(index),
                _chapter_xhtml(chapter.title, chapter.paragraphs),
                compress_type=zipfile.ZIP_DEFLATED)


def read_existing_chapters(epub_path):
    """Reads back the chapters of an EPUB this module built (matching the
    <h1>title</h1><p>...</p> shape _chapter_xhtml() writes), so a later
    "download the new chapters" run can prepend what's already there
    instead of overwriting it with just the new range.
    """
    from .epub import EpubBook
    book = EpubBook(epub_path)
    chapters = []
    for page in book.pages:
        body = page.data.find('./{%s}body' % XHTML_NS)
        if body is None:
            continue
        title_el = body.find('./{%s}h1' % XHTML_NS)
        title = ''.join(title_el.itertext()).strip() if title_el is not None else ''
        paragraphs = [
            text for p in body.findall('./{%s}p' % XHTML_NS)
            if (text := ''.join(p.itertext()).strip())]
        chapters.append(ChapterContent(title=title, paragraphs=paragraphs))
    return chapters


def merge_and_build_epub(
        novel_info, new_chapters, output_path, cover_bytes=None, language='en'):
    """Like build_epub(), but if output_path already exists (e.g. an
    earlier download of the same novel), its existing chapters are read
    back and kept ahead of the newly fetched ones instead of being
    discarded. Returns how many existing chapters were carried over.
    """
    existing_chapters = []
    if os.path.exists(output_path):
        try:
            existing_chapters = read_existing_chapters(output_path)
        except Exception:
            existing_chapters = []
    build_epub(
        novel_info, existing_chapters + new_chapters, output_path,
        cover_bytes=cover_bytes, language=language)
    return len(existing_chapters)
