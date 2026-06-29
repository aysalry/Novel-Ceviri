"""Standalone EPUB reader/writer.

Replaces Calibre's Plumber/OEB conversion. Since we only ever go EPUB -> EPUB
(translating content in place, never converting formats), this can just:
unzip, parse the OPF/NCX/nav XML with lxml, hand the parsed trees to the
existing (Calibre-independent) extraction/reinsertion logic in core.element,
then re-zip -- copying every untouched entry (images, CSS, fonts...)
byte-for-byte and only re-serializing the handful of XML documents that were
actually mutated.
"""
import posixpath
import zipfile
from itertools import zip_longest

from lxml import etree

from ..core.utils import parse_xml_lenient

XHTML_NS = 'http://www.w3.org/1999/xhtml'
DC_NS = 'http://purl.org/dc/elements/1.1/'
OPF_NS = 'http://www.idpf.org/2007/opf'
NCX_NS = 'http://www.daisy.org/z3986/2005/ncx/'
EPUB_OPS_NS = 'http://www.idpf.org/2007/ops'
CONTAINER_NS = 'urn:oasis:names:tc:opendocument:xmlns:container'

XHTML_MEDIA_TYPES = ('application/xhtml+xml', 'text/html')
NCX_MEDIA_TYPE = 'application/x-dtbncx+xml'


class Page:
    """Stand-in for one of Calibre's oeb.manifest.items, just enough for
    core.element.get_page_elements()/Extraction to work with: page.data
    must be the lxml root <html> element, page.href must end in a content
    extension, page.id is only used for bookkeeping.
    """

    def __init__(self, id, href, data):
        self.id = id
        self.href = href
        self.data = data


class MetadataItem:
    def __init__(self, element):
        self.element = element
        self.content = (element.text or '').strip()

    def flush(self):
        self.element.text = self.content


class EpubMetadata:
    """Stand-in for Calibre's oeb.metadata: iterkeys() + attribute access
    returning a list of mutable-.content items, read from the OPF's
    <metadata> block.
    """

    NAMES = (
        'title', 'creator', 'publisher', 'rights', 'subject', 'contributor',
        'description')

    def __init__(self, metadata_element):
        self._by_key: dict[str, list[MetadataItem]] = {}
        for name in self.NAMES:
            elements = metadata_element.findall('{%s}%s' % (DC_NS, name))
            if elements:
                self._by_key[name] = [MetadataItem(e) for e in elements]

    def iterkeys(self):
        return iter(list(self._by_key.keys()))

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._by_key.get(name, [])

    def all_items(self):
        for items in self._by_key.values():
            yield from items


class TocNode:
    """Stand-in for one of Calibre's TOC nodes: a mutable .title backed by
    whichever lxml element actually holds the visible label text (an NCX
    <navLabel><text> or an EPUB3 nav <a>), plus recursive .nodes.
    """

    def __init__(self, text_elements):
        # A book with both toc.ncx and nav.xhtml describes the same heading
        # twice; this can hold both elements so setting .title updates them
        # in lockstep instead of only translating whichever one we picked.
        self._text_elements = (
            text_elements if isinstance(text_elements, list)
            else [text_elements])
        self.nodes: list['TocNode'] = []

    @property
    def title(self):
        for element in self._text_elements:
            if element.text:
                return element.text.strip()
        return ''

    @title.setter
    def title(self, value):
        for element in self._text_elements:
            element.text = value


class Toc:
    def __init__(self, nodes):
        self.nodes = nodes


def _join(base_dir, href):
    return posixpath.normpath(posixpath.join(base_dir, href.split('#')[0]))


class EpubBook:
    def __init__(self, path):
        self.path = path
        self._modified_xml: dict[str, etree._Element] = {}

        with zipfile.ZipFile(path, 'r') as zf:
            container = parse_xml_lenient(zf.read('META-INF/container.xml'))
            rootfile = container.find(
                './/{%s}rootfile' % CONTAINER_NS)
            self.opf_path = rootfile.get('full-path')
            self.opf_dir = posixpath.dirname(self.opf_path)

            self.opf_root = parse_xml_lenient(zf.read(self.opf_path))
            self._modified_xml[self.opf_path] = self.opf_root

            manifest_el = self.opf_root.find('{%s}manifest' % OPF_NS)
            manifest_items = {
                item.get('id'): item for item in manifest_el
                if isinstance(item.tag, str)}

            metadata_el = self.opf_root.find('{%s}metadata' % OPF_NS)
            self.metadata = EpubMetadata(metadata_el)

            self.pages: list[Page] = []
            nav_id = None
            for item_id, item in manifest_items.items():
                properties = (item.get('properties') or '').split()
                if 'nav' in properties:
                    nav_id = item_id
                    continue
                if item.get('media-type') in XHTML_MEDIA_TYPES:
                    full_path = _join(self.opf_dir, item.get('href'))
                    root = parse_xml_lenient(zf.read(full_path))
                    self._modified_xml[full_path] = root
                    self.pages.append(Page(item_id, item.get('href'), root))

            self.toc = Toc(self._load_toc(zf, manifest_items, nav_id))

    def _load_toc(self, zf, manifest_items, nav_id):
        ncx_item = next(
            (item for item in manifest_items.values()
             if item.get('media-type') == NCX_MEDIA_TYPE), None)
        ncx_nodes = (
            self._load_ncx(zf, ncx_item.get('href'))
            if ncx_item is not None else None)
        nav_nodes = (
            self._load_nav(zf, manifest_items[nav_id].get('href'))
            if nav_id is not None else None)
        # Most real EPUBs carry both an EPUB2 toc.ncx and an EPUB3
        # nav.xhtml describing the same headings -- merge them so setting
        # .title updates both in lockstep instead of leaving whichever one
        # we didn't pick untranslated (many reading apps prefer nav.xhtml).
        if ncx_nodes is not None and nav_nodes is not None:
            return self._merge_toc_nodes(ncx_nodes, nav_nodes)
        return ncx_nodes if ncx_nodes is not None else (nav_nodes or [])

    @staticmethod
    def _merge_toc_nodes(a_nodes, b_nodes):
        merged = []
        for a, b in zip_longest(a_nodes, b_nodes):
            if a is not None and b is not None:
                node = TocNode(a._text_elements + b._text_elements)
                node.nodes = EpubBook._merge_toc_nodes(a.nodes, b.nodes)
            else:
                # Structural mismatch between the two TOCs (rare) -- keep
                # whichever side actually has this entry rather than
                # dropping it.
                node = a if a is not None else b
            merged.append(node)
        return merged

    def _load_ncx(self, zf, href):
        full_path = _join(self.opf_dir, href)
        root = parse_xml_lenient(zf.read(full_path))
        self._modified_xml[full_path] = root
        nav_map = root.find('{%s}navMap' % NCX_NS)
        if nav_map is None:
            return []

        def build(nav_point_parent):
            nodes = []
            for nav_point in nav_point_parent.findall(
                    '{%s}navPoint' % NCX_NS):
                text_el = nav_point.find(
                    '{%s}navLabel/{%s}text' % (NCX_NS, NCX_NS))
                if text_el is None:
                    continue
                node = TocNode([text_el])
                node.nodes = build(nav_point)
                nodes.append(node)
            return nodes

        return build(nav_map)

    def _load_nav(self, zf, href):
        full_path = _join(self.opf_dir, href)
        root = parse_xml_lenient(zf.read(full_path))
        self._modified_xml[full_path] = root
        toc_nav = None
        for nav in root.iter('{%s}nav' % XHTML_NS):
            types = (nav.get('{%s}type' % EPUB_OPS_NS) or '').split()
            if 'toc' in types:
                toc_nav = nav
                break
        if toc_nav is None:
            return []
        top_ol = toc_nav.find('{%s}ol' % XHTML_NS)
        if top_ol is None:
            return []

        def build(ol_element):
            nodes = []
            for li in ol_element.findall('{%s}li' % XHTML_NS):
                label_el = li.find('{%s}a' % XHTML_NS)
                if label_el is None:
                    label_el = li.find('{%s}span' % XHTML_NS)
                if label_el is None:
                    continue
                node = TocNode([label_el])
                child_ol = li.find('{%s}ol' % XHTML_NS)
                if child_ol is not None:
                    node.nodes = build(child_ol)
                nodes.append(node)
            return nodes

        return build(top_ol)

    def save(self, output_path):
        for item in self.metadata.all_items():
            item.flush()
        with zipfile.ZipFile(self.path, 'r') as src, \
                zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                modified = self._modified_xml.get(info.filename)
                if modified is not None:
                    data = etree.tostring(
                        modified, xml_declaration=True, encoding='utf-8',
                        standalone=True)
                else:
                    data = src.read(info.filename)
                dst.writestr(info, data)
