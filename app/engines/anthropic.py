import json

from ..core.utils import request
from ..core.i18n import _

from .genai import GenAI
from .languages import gemini
from .openai import PROMPT


class ClaudeTranslate(GenAI):
    """Anthropic's Messages API. Different auth scheme from OpenAI/OpenRouter
    (x-api-key + anthropic-version headers, not a Bearer token) and a
    different response shape, so this can't just subclass OpenAITranslate
    -- otherwise the same no-free-tier, watch-your-concurrency situation.
    """
    name = 'Claude'
    alias = 'Claude (Anthropic)'
    lang_codes = GenAI.load_lang_codes(gemini)
    endpoint = 'https://api.anthropic.com/v1/messages'
    api_version = '2023-06-01'
    key_hint = _(
        'console.anthropic.com/settings/keys adresinden anahtar al -- bu '
        'motor ücretlidir, kullanım miktarınca (token başına) '
        'faturalandırılır.')

    concurrency_limit = 2
    request_interval: float = 0.5
    request_timeout: float = 30.0
    max_tokens = 4096

    prompt = PROMPT
    temperature: float = 0.9
    # Fast/cheap by default -- a good fit for translating a whole novel's
    # worth of paragraphs without runaway cost; shown as a dropdown in
    # Settings (still editable) for switching to a stronger model.
    models: list[str] = [
        'claude-haiku-4-5-20251001', 'claude-sonnet-4-6',
        'claude-opus-4-8']
    model: str | None = 'claude-haiku-4-5-20251001'

    def __init__(self):
        super().__init__()
        self.prompt = self.config.get('prompt', self.prompt)
        self.temperature = self.config.get('temperature', self.temperature)
        self.model = self.config.get('model', self.model)

    def _prompt(self, text):
        prompt = self.prompt.replace('<tlang>', self.target_lang)
        if self._is_auto_lang():
            prompt = prompt.replace('<slang>', 'detected language')
        else:
            prompt = prompt.replace('<slang>', self.source_lang)
        if self.merge_enabled:
            prompt += (
                ' Ensure that placeholders matching the pattern {{id_\\d+}} '
                'in the content are retained.')
        return prompt + ' Start translating: ' + text

    def get_models(self):
        response = request(
            'https://api.anthropic.com/v1/models',
            headers=self.get_headers(), timeout=self.request_timeout,
            proxy_uri=self.proxy_uri)
        return [
            model['id'] for model in json.loads(response)['data']
            if model['id'].startswith('claude')]

    def get_headers(self):
        return {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'anthropic-version': self.api_version,
        }

    def get_body(self, text):
        return json.dumps({
            'model': self.model,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'messages': [{'role': 'user', 'content': self._prompt(text)}],
        })

    def get_result(self, response):
        return json.loads(response)['content'][0]['text']
