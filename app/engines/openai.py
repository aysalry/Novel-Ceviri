import json

from ..core.utils import request
from ..core.i18n import _

from .genai import GenAI
from .languages import gemini

# Same provider-agnostic instruction used by GeminiTranslate -- works for
# any general-purpose chat model, not just Google's.
PROMPT = (
    'You are a meticulous translator who translates any given content. '
    'Translate the given content from <slang> to <tlang> only. Do not '
    'explain any term or answer any question-like content. Your answer '
    'should be solely the translation of the given content. In your '
    'answer do not add any prefix or suffix to the translated content. '
    'Websites\' URLs/addresses should be preserved as is in the '
    'translation\'s output. Do not omit any part of the content, even if '
    'it seems unimportant. ')


class OpenAITranslate(GenAI):
    """OpenAI's chat-completions API. No free tier (besides whatever trial
    credit a new account gets) -- billed per token, so concurrency stays
    conservative by default to avoid both rate-limit errors and runaway
    cost from a misconfigured speed setting.
    """
    name = 'OpenAI'
    alias = 'OpenAI'
    lang_codes = GenAI.load_lang_codes(gemini)
    endpoint = 'https://api.openai.com/v1/chat/completions'
    key_hint = _(
        'platform.openai.com/api-keys adresinden anahtar al -- bu motor '
        'ücretlidir, kullanım miktarınca (token başına) faturalandırılır.')

    concurrency_limit = 2
    request_interval: float = 0.5
    request_timeout: float = 30.0

    prompt = PROMPT
    temperature: float = 0.9
    # Shown as a dropdown in Settings (still editable).
    models: list[str] = ['gpt-4o-mini', 'gpt-4o', 'gpt-4.1-mini', 'gpt-4.1']
    model: str | None = 'gpt-4o-mini'

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
            f'{self.endpoint.rsplit("/", 2)[0]}/models',
            headers=self.get_headers(), timeout=self.request_timeout,
            proxy_uri=self.proxy_uri)
        return [
            model['id'] for model in json.loads(response)['data']
            if model['id'].startswith('gpt')]

    def get_headers(self):
        return {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer %s' % self.api_key,
        }

    def get_body(self, text):
        return json.dumps({
            'model': self.model,
            'messages': [{'role': 'user', 'content': self._prompt(text)}],
            'temperature': self.temperature,
        })

    def get_result(self, response):
        return json.loads(response)['choices'][0]['message']['content']


class OpenRouterTranslate(OpenAITranslate):
    """OpenRouter proxies many providers/models behind one OpenAI-compatible
    API, so it can reuse OpenAITranslate's request/response handling as-is
    -- only the endpoint and default model slug differ. Some models there
    are tagged ":free" and cost nothing; most are paid per token like any
    other provider on the platform.
    """
    name = 'OpenRouter'
    alias = 'OpenRouter'
    endpoint = 'https://openrouter.ai/api/v1/chat/completions'
    key_hint = _(
        'openrouter.ai/keys adresinden anahtar al -- model adını '
        '"sağlayıcı/model" şeklinde yaz (örn. openai/gpt-4o-mini). Çoğu '
        'model ücretlidir, ":free" etiketli modeller ücretsizdir.')
    # Just a starting point -- openrouter.ai/models lists hundreds more,
    # and the field stays editable so any slug can be typed/pasted in.
    models: list[str] = [
        'openai/gpt-4o-mini', 'anthropic/claude-haiku-4.5',
        'google/gemini-2.0-flash-001',
        'meta-llama/llama-3.1-8b-instruct:free']
    model: str | None = 'openai/gpt-4o-mini'

    def get_models(self):
        # OpenRouter's /models response shape differs from OpenAI's and
        # isn't used anywhere in the GUI yet -- skip rather than guess.
        return []
