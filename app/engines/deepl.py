import json

from ..core.utils import request
from ..core.i18n import _

from .base import Base
from .languages import deepl


class DeeplTranslate(Base):
    """Official DeepL API, free tier -- needs a free DeepL account's API
    key (always ends in ":fx"), good for 500k chars/month at no cost.
    Translation quality is a step above Google for many languages,
    Turkish included. Pairs with api-free.deepl.com specifically -- a
    Pro key won't work here, see DeeplProTranslate.
    """
    name = 'DeepL'
    alias = 'DeepL (Ücretsiz API)'
    lang_codes = Base.load_lang_codes(deepl)
    endpoint = 'https://api-free.deepl.com/v2/translate'
    usage_endpoint = 'https://api-free.deepl.com/v2/usage'
    placeholder = ('<m id={} />', r'<m\s+id={}\s+/>')
    api_key_errors = ['403', '456']
    key_hint = _(
        'www.deepl.com/pro-api adresinden ücretsiz hesap açıp anahtar al '
        '-- anahtarın sonu ":fx" ile bitmeli, Pro anahtarla burada 403 '
        'hatası alırsın.')

    # Unlike every other engine here, this had no concurrency cap at all --
    # Base defaults to 0, which the handler treats as "one worker per
    # paragraph," so a normal-sized chapter fired its whole paragraph list
    # at DeepL simultaneously. DeepL's API rate-limits bursts like that
    # (429), so this was the one engine left exposed to constant
    # rate-limit failures on anything but a tiny file.
    concurrency_limit = 4
    request_interval: float = 0.3

    def get_usage(self):
        # See: https://www.deepl.com/docs-api/general/get-usage/
        headers = {'Authorization': 'DeepL-Auth-Key %s' % self.api_key}
        try:
            response = request(
                self.usage_endpoint, headers=headers, proxy_uri=self.proxy_uri)
            usage = json.loads(response)
        except Exception:
            return None
        total = usage.get('character_limit')
        used = usage.get('character_count')
        left = total - used

        return _('{} total, {} used, {} left').format(total, used, left)

    def get_headers(self):
        return {'Authorization': 'DeepL-Auth-Key %s' % self.api_key}

    def get_body(self, text):
        body = {
            'text': text,
            'target_lang': self._get_target_code()
        }
        if not self._is_auto_lang():
            body.update(source_lang=self._get_source_code())

        return body

    def get_result(self, response):
        return json.loads(response)['translations'][0]['text']


class DeeplProTranslate(DeeplTranslate):
    name = 'DeepL(Pro)'
    alias = 'DeepL (Pro API - Ücretli)'
    key_hint = _(
        'www.deepl.com/pro-api adresinden ücretli bir hesap açıp anahtar '
        'al -- anahtarın sonu ":fx" ile BİTMEMELİ, Ücretsiz anahtarla '
        'burada 403 hatası alırsın.')
    endpoint = 'https://api.deepl.com/v2/translate'
    usage_endpoint = 'https://api.deepl.com/v2/usage'

