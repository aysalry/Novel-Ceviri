"""User-defined, JSON-described translation engines -- lets someone plug in
any HTTP translation API (a self-hosted LibreTranslate, Ollama/LM Studio
behind an OpenAI-compatible shim, a provider we haven't added a dedicated
engine class for, etc.) without needing a code change from us.

Unlike the Calibre plugin this was ported from, the response is NOT parsed
with eval() -- this app is distributed publicly and "paste this JSON to add
a engine" is exactly the kind of thing that gets shared in a Discord/forum
post, so letting that JSON execute arbitrary Python would be a real code
injection vector. Instead, response_path is a small, safe dotted/indexed
path (e.g. "data.translations[0].text") walked by _extract_by_path().
"""
import re
import json

from ..core.i18n import _
from .base import Base

_PATH_TOKEN_RE = re.compile(r'([^.\[\]]+)|\[(\d+)\]')


def _extract_by_path(data, path):
    """Walks a parsed JSON structure using a path like
    "data.translations[0].text" -- only ever indexes into dicts/lists by
    literal key/int, never executes anything.
    """
    current = data
    for key, index in _PATH_TOKEN_RE.findall(path or ''):
        current = current[int(index)] if index else current[key]
    return current


def create_engine_template(name=None):
    return json.dumps({
        'name': name or _('Motor Adım'),
        'languages': {
            'source': {_('Otomatik Algıla'): 'auto', 'English': 'en'},
            'target': {'Türkçe': 'tr'},
        },
        'request': {
            'url': 'https://example.api/translate',
            'method': 'POST',
            'headers': {'Content-Type': 'application/json'},
            'data': {
                'source': '<source>', 'target': '<target>', 'text': '<text>'},
        },
        'response_path': 'data.translations[0].text',
    }, indent=2, ensure_ascii=False)


def load_engine_data(text, existing_names=()):
    """Returns (True, parsed_dict) or (False, error_message)."""
    try:
        json_data = json.loads(text)
    except Exception:
        return (False, _('Motor verisi geçerli bir JSON olmalı.'))
    if not isinstance(json_data, dict):
        return (False, _('Geçersiz motor verisi.'))

    name = json_data.get('name')
    if not name:
        return (False, _('Motor adı gerekli.'))
    if name in existing_names:
        return (False, _('Bu isimde bir motor zaten var.'))

    languages = json_data.get('languages')
    if not languages:
        return (False, _('Dil kodları gerekli.'))
    has_source = 'source' in languages
    has_target = 'target' in languages
    if has_source != has_target:
        return (False, _('Kaynak ve hedef diller birlikte eklenmeli.'))

    request = json_data.get('request')
    if not request:
        return (False, _('İstek bilgisi gerekli.'))
    if 'url' not in request:
        return (False, _('API URL gerekli.'))
    data = request.get('data')
    if data is not None and '<text>' not in json.dumps(data):
        return (False, _('İstek verisinde <text> yer tutucusu gerekli.'))

    if not json_data.get('response_path'):
        return (False, _(
            'Cevabı okumak için bir "response_path" gerekli '
            '(örn. "data.translations[0].text").'))

    return (True, json_data)


def _custom_init(self):
    Base.__init__(self)
    self.endpoint = self.request.get('url')
    self.method = self.request.get('method') or 'GET'


def _custom_get_headers(self):
    return self.request.get('headers') or {}


def _custom_get_body(self, text):
    body = self.request.get('data')
    need_restore = isinstance(body, dict)
    raw = json.dumps(body)
    raw = raw.replace('<source>', self._get_source_code() or '') \
        .replace('<target>', self._get_target_code() or '') \
        .replace('<text>', json.dumps(text)[1:-1])
    headers = self.get_headers()
    is_json = any('application/json' in v for v in headers.values())
    if need_restore and not is_json:
        return json.loads(raw)
    return raw.encode('utf-8')


def _custom_get_result(self, response):
    try:
        parsed = json.loads(response)
    except Exception:
        raise Exception(_('Cevap geçerli bir JSON değil.'))
    try:
        result = _extract_by_path(parsed, self.response_path)
    except (KeyError, IndexError, TypeError) as e:
        raise Exception(
            _('Cevapta "{}" bulunamadı: {}').format(self.response_path, e))
    if not isinstance(result, str):
        raise Exception(_('Cevap doğru ayrıştırılamadı (metin değil).'))
    return result


def build_custom_engine_class(data):
    """One fresh Base subclass per engine definition -- unlike the Calibre
    plugin's CustomTranslate (a single class whose identity gets mutated
    per selection), this lets several custom engines coexist in the
    dropdown at once without one overwriting another's state.
    """
    class_name = 'CustomEngine_%s' % re.sub(r'\W+', '_', data['name'])
    return type(class_name, (Base,), {
        'name': data['name'],
        'alias': data['name'],
        'need_api_key': False,
        'lang_codes': Base.load_lang_codes(data.get('languages') or {}),
        'request': data.get('request') or {},
        'response_path': data.get('response_path') or '',
        '__init__': _custom_init,
        'get_headers': _custom_get_headers,
        'get_body': _custom_get_body,
        'get_result': _custom_get_result,
    })
