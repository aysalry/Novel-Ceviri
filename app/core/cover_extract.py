"""Pulls the embedded cover image out of an EPUB, for showing real book
covers in the library grid instead of plain text rows.
"""
import posixpath
import zipfile

from .utils import parse_xml_lenient

OPF_NS = 'http://www.idpf.org/2007/opf'
CONTAINER_NS = 'urn:oasis:names:tc:opendocument:xmlns:container'


def _join(base_dir, href):
    return posixpath.normpath(posixpath.join(base_dir, href.split('#')[0]))


def extract_cover_bytes(epub_path):
    """Returns the cover image's raw bytes, or None if the EPUB has no
    identifiable cover (some minimal/hand-built EPUBs genuinely don't)
    or can't be read at all -- callers fall back to a generated
    placeholder rather than showing a broken thumbnail.
    """
    try:
        with zipfile.ZipFile(epub_path, 'r') as zf:
            container = parse_xml_lenient(zf.read('META-INF/container.xml'))
            rootfile = container.find('.//{%s}rootfile' % CONTAINER_NS)
            opf_path = rootfile.get('full-path')
            opf_dir = posixpath.dirname(opf_path)
            opf_root = parse_xml_lenient(zf.read(opf_path))

            manifest_el = opf_root.find('{%s}manifest' % OPF_NS)
            items = [
                item for item in manifest_el if isinstance(item.tag, str)]

            href = _find_cover_href(opf_root, items)
            if href is None:
                return None
            return zf.read(_join(opf_dir, href))
    except Exception:
        return None


def _find_cover_href(opf_root, items):
    # EPUB3: a manifest item explicitly marked as the cover image.
    for item in items:
        if 'cover-image' in (item.get('properties') or '').split():
            return item.get('href')

    # EPUB2: <metadata><meta name="cover" content="some-item-id"/>, still
    # the more common convention even in EPUBs built today.
    metadata_el = opf_root.find('{%s}metadata' % OPF_NS)
    if metadata_el is not None:
        for meta in metadata_el.findall('{%s}meta' % OPF_NS):
            if meta.get('name') == 'cover':
                cover_id = meta.get('content')
                for item in items:
                    if item.get('id') == cover_id:
                        return item.get('href')

    # Last resort: a manifest item that merely looks like a cover image.
    for item in items:
        media_type = item.get('media-type') or ''
        if 'image' in media_type and 'cover' in (item.get('id') or '').lower():
            return item.get('href')
    return None
