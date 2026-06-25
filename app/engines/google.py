import json

from ..core.utils import request
from ..core.i18n import _

from .base import Base
from .genai import GenAI
from .languages import google, gemini


class GoogleFreeTranslateNew(Base):
    """The endpoint Google Translate's own web frontend uses. No API key,
    no quota dialog -- this is the default, zero-setup engine.
    """
    name = 'Google(Free)New'
    alias = 'Google (Free) - New'
    free = True
    lang_codes = Base.load_lang_codes(google)
    endpoint: str = 'https://translate-pa.googleapis.com/v1/translate'
    need_api_key = False
    # Base defaults concurrency_limit to 0, which the handler treats as
    # "one worker per paragraph" -- fine for a 5-paragraph file, a great way
    # to get IP-throttled on a 3000-paragraph novel. Cap it by default.
    concurrency_limit = 8

    def get_headers(self):
        return {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 '
            'Safari/537.36',
        }

    def get_body(self, text):
        self.method = 'GET'
        return {
            'params.client': 'gtx',
            'query.source_language': self._get_source_code(),
            'query.target_language': self._get_target_code(),
            'query.display_language': 'en-US',
            'data_types': 'TRANSLATION',
            'key': 'AIzaSyDLEeFI5OtFBwYBIoK_jj5m32rZK5CkCXA',
            'query.text': text,
        }

    def get_result(self, response):
        return json.loads(response)['translation']


class GeminiTranslate(GenAI):
    name = 'Gemini'
    alias = 'Gemini'
    lang_codes = GenAI.load_lang_codes(gemini)
    # v1, stable version of the API. v1beta, more early-access features.
    # details: https://ai.google.dev/gemini-api/docs/api-versions
    endpoint = 'https://generativelanguage.googleapis.com/v1beta/models'
    # https://ai.google.dev/gemini-api/docs/troubleshooting
    api_key_errors: list[str] = [
        'API_KEY_INVALID', 'PERMISSION_DENIED', 'RESOURCE_EXHAUSTED']

    # Gemini's free tier is rate-limited per-minute, so default to
    # sequential requests instead of the Google-Free concurrency defaults.
    concurrency_limit = 1
    request_interval: float = 1.0
    request_timeout: float = 30.0

    prompt = (
        'You are a meticulous translator who translates any given content. '
        'Translate the given content from <slang> to <tlang> only. Do not '
        'explain any term or answer any question-like content. Your answer '
        'should be solely the translation of the given content. In your '
        'answer do not add any prefix or suffix to the translated content. '
        'Websites\' URLs/addresses should be preserved as is in the '
        'translation\'s output. Do not omit any part of the content, even if '
        'it seems unimportant. ')
    temperature: float = 0.9
    top_p: float = 1.0
    top_k = 1
    stream = True

    models: list[str] = []
    model: str | None = 'gemini-2.0-flash'

    def __init__(self):
        super().__init__()
        self.prompt = self.config.get('prompt', self.prompt)
        self.temperature = self.config.get('temperature', self.temperature)
        self.top_k = self.config.get('top_k', self.top_k)
        self.top_p = self.config.get('top_p', self.top_p)
        self.stream = self.config.get('stream', self.stream)
        self.model = self.config.get('model', self.model)

    def _prompt(self, text):
        prompt = self.prompt.replace('<tlang>', self.target_lang)
        if self._is_auto_lang():
            prompt = prompt.replace('<slang>', 'detected language')
        else:
            prompt = prompt.replace('<slang>', self.source_lang)
        # Recommend setting temperature to 0.5 for retaining the placeholder.
        if self.merge_enabled:
            prompt += (
                ' Ensure that placeholders matching the pattern {{id_\\d+}} '
                'in the content are retained.')
        return prompt + ' Start translating: ' + text

    def get_models(self):
        endpoint = f'{self.endpoint}?key={self.api_key}'
        response = request(
            endpoint, timeout=self.request_timeout, proxy_uri=self.proxy_uri)
        models = []
        for model in json.loads(response)['models']:
            model_name = model['name'].split('/')[-1]
            if model_name.startswith('gemini'):
                model_desc = model['description']
                if 'deprecated' not in model_desc:
                    models.append(model_name)
        return models

    def get_endpoint(self):
        if self.stream:
            return f'{self.endpoint}/{self.model}:streamGenerateContent?' \
                f'alt=sse&key={self.api_key}'
        else:
            return f'{self.endpoint}/{self.model}:generateContent?' \
                f'key={self.api_key}'

    def get_headers(self):
        return {'Content-Type': 'application/json'}

    def get_body(self, text):
        return json.dumps({
            "contents": [
                {"role": "user", "parts": [{"text": self._prompt(text)}]},
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "topP": self.top_p,
                "topK": self.top_k,
            },
            "safetySettings": [
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE"
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE"
                },
            ],
        })

    def get_result(self, response):
        if self.stream:
            return self._parse_stream(response)
        parts = json.loads(response)['candidates'][0]['content']['parts']
        return ''.join([part['text'] for part in parts])

    def _parse_stream(self, response):
        """response is a live, streaming requests.Response (see
        core.utils.request(raw_object=True)); iter_lines() hands back
        complete lines as they arrive over the SSE connection.
        """
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            try:
                line = raw_line.decode('utf-8').strip()
            except Exception as e:
                raise Exception(
                    _('Can not parse returned response. Raw data: {}')
                    .format(str(e)))
            if line.startswith('data:'):
                item = json.loads(line.split('data: ')[1])
                candidate = item['candidates'][0]
                content = candidate['content']
                if 'parts' in content.keys():
                    for part in content['parts']:
                        yield part['text']
                if candidate.get('finishReason') == 'STOP':
                    break
