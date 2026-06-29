import re
import os
import sys
import json
import socket
import hashlib
import tempfile
import threading
import traceback
from urllib.request import getproxies
from subprocess import Popen

import requests
from lxml import etree

from .cssselect import GenericTranslator, SelectorError


ns = {'x': 'http://www.w3.org/1999/xhtml'}
is_test = 'unittest' in sys.modules

# Translation requests run concurrently across several worker threads (see
# core/handler.py). requests.Session() connection pooling isn't documented
# as safe to share across threads, so give each worker thread its own --
# it still gets the connection-reuse benefit across the many calls *that*
# thread makes over a file's lifetime.
_thread_local = threading.local()


def _get_session() -> requests.Session:
    session = getattr(_thread_local, 'session', None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session

_illegal_xml_chars_re = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Non-breaking space, ideographic space, zero-width space, BOM: written via
# chr() rather than literal glyphs/escapes to avoid any source-encoding
# ambiguity.
_NBSP, _IDEOGRAPHIC_SPACE = chr(0x00a0), chr(0x3000)
_ZERO_WIDTH_SPACE, _BOM = chr(0x200b), chr(0xfeff)
_whitespace_noise_re = re.compile(_NBSP + '|' + _IDEOGRAPHIC_SPACE)
_invisible_noise_re = re.compile(_ZERO_WIDTH_SPACE + '|' + _BOM)


def lang_as_iso639_1(code):
    """Languages with no real ISO 639-1 code fall back to None, same as
    Calibre's lang_as_iso639_1() would.
    """
    if not code:
        return None
    code = code.split('-')[0].split('_')[0].lower()
    return code if len(code) == 2 else None


def prepare_string_for_xml(raw, attribute=False):
    """Escape text for safe insertion into XML, mirroring Calibre's
    prepare_string_for_xml() (drop illegal XML control chars, escape the
    handful of characters that are actually unsafe in markup).
    """
    raw = _illegal_xml_chars_re.sub('', raw)
    raw = raw.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    if attribute:
        raw = raw.replace('"', '&quot;').replace("'", '&apos;')
    return raw


def dummy(*args, **kwargs):
    pass


def sep(char='=', count=38):
    return char * count


def css(selector):
    try:
        return GenericTranslator().css_to_xpath(selector, prefix='self::x:')
    except SelectorError:
        return None


def css_to_xpath(selectors):
    patterns = []
    for selector in selectors:
        if rule := css(selector):
            patterns.append(rule)
    return patterns


def create_xpath(selectors):
    selectors = (selectors,) if isinstance(selectors, str) else selectors
    return './/*[%s]' % ' or '.join(css_to_xpath(selectors))


def uid(*args):
    md5 = hashlib.md5()
    for arg in args:
        md5.update(arg if isinstance(arg, bytes) else arg.encode('utf-8'))
    return md5.hexdigest()


def trim(text):
    # Collapse non-breaking / ideographic spaces to a plain space.
    text = _whitespace_noise_re.sub(' ', text)
    # Drop zero-width-space / BOM noise some engines slip into output.
    text = _invisible_noise_re.sub('', text)
    # Combine multiple white spaces into a single space.
    text = re.sub(r'\s+', ' ', text)
    # Remove all potential non-printable characters.
    text = re.sub(r'(?![\n\r\t])[\x00-\x1f\x7f-\xa0\xad]', '', text)
    return text.strip()


def chunk(items, length=0):
    if length < 1:
        for item in items:
            yield [item]
        return
    item_length = len(items)
    length = item_length if length > item_length else length
    chunk_size = item_length / length
    for i in range(length):
        yield items[int(chunk_size*i):int(chunk_size*(i+1))]


def group(numbers):
    ranges = []
    current_range: list = []
    numbers = sorted(numbers)
    for number in numbers:
        if not current_range:
            current_range = [number, number]
        elif number - current_range[-1] == 1:
            current_range[-1] = number
        else:
            ranges.append(tuple(current_range))
            current_range = [number, number]
    ranges.append(tuple(current_range))
    return ranges


def sorted_mixed_keys(s):
    # https://docs.python.org/3/reference/expressions.html#value-comparisons
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', s)]


def is_str(data):
    return type(data).__name__ in ('str', 'unicode')


def is_proxy_available(host, port, timeout=1):
    try:
        host = host.replace('http://', '')
        socket.create_connection((host, int(port)), timeout).close()
    except Exception:
        return False
    return True


def size_by_unit(number, unit='KB'):
    unit = unit.upper()
    multiple = {'KB': 1, 'MB': 2}
    if unit not in multiple:
        unit = 'KB'
    return round(float(number) / (1000 ** multiple[unit]), 2)


def open_path(path):
    cmd = 'open'
    if sys.platform.startswith('win32'):
        cmd = 'explorer'
    if sys.platform.startswith('linux'):
        cmd = 'xdg-open'
    Popen([cmd, path])


def detect_encoding(path):
    """Raw webnovel/subtitle dumps are frequently not UTF-8 (GBK, Shift-JIS,
    Windows-125x...); sniff the real encoding instead of assuming.
    """
    from charset_normalizer import from_path
    best_match = from_path(path).best()
    return best_match.encoding if best_match else 'utf-8'


def open_file(path, encoding=None):
    if not encoding or encoding == 'auto':
        encoding = detect_encoding(path)
    with open(path, 'r', encoding=encoding, newline=None) as file:
        return file.read()


def atomic_write_json(path, data, **dump_kwargs):
    """Writes JSON to path without ever leaving a half-written, corrupt
    file behind if the process dies mid-write (crash, kill, power loss) --
    write to a temp file in the same directory, flush it fully, then
    os.replace() it over the real path, which is atomic on both Windows
    and POSIX as long as source and destination are on the same volume.
    """
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, **dump_kwargs)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def traceback_error():
    return traceback.format_exc(chain=False).strip()


def parse_xml_lenient(data):
    """A lot of real-world EPUBs (sloppy converters, scraped webnovels,
    hand-edited files) aren't well-formed XML -- an unescaped "&", an
    unclosed <br>/<img>, a stray HTML5 construct -- which etree.fromstring()
    refuses outright with XMLSyntaxError even though the document is
    perfectly readable as markup. Falling back to a recovering parser
    salvages whatever it can instead of failing the entire file (and
    everything downstream: translation, the built-in reader, cover
    extraction) over one malformed tag.
    """
    try:
        return etree.fromstring(data)
    except etree.XMLSyntaxError:
        root = etree.fromstring(data, parser=etree.XMLParser(recover=True))
        if root is None:
            raise
        return root


def request(
        url, data=None, headers=None, method='GET', timeout=30,
        proxy_uri=None, raw_object=False):
    """Replacement for the plugin's mechanize-based request(). Returns the
    decoded response body (str) normally, or the live requests.Response
    (for streaming reads, e.g. Gemini's SSE) when raw_object is True.
    """
    headers = headers or {}
    proxies = {}
    if proxy_uri is not None:
        proxies.update(http=proxy_uri, https=proxy_uri)
    else:
        system_proxies = getproxies()
        http_proxy = system_proxies.get('http')
        http_proxy and proxies.update(http=http_proxy, https=http_proxy)
        https_proxy = system_proxies.get('https')
        https_proxy and proxies.update(https=https_proxy)

    kwargs = dict(
        headers=headers, timeout=timeout, proxies=proxies or None,
        stream=raw_object)
    session = _get_session()

    if method.upper() == 'GET':
        if isinstance(data, dict):
            kwargs['params'] = data
        response = session.get(url, **kwargs)
    else:
        if isinstance(data, str):
            kwargs['data'] = data.encode('utf-8')
        else:
            kwargs['data'] = data
        response = session.post(url, **kwargs)

    response.raise_for_status()
    if raw_object:
        return response
    return response.content.decode('utf-8').strip()
