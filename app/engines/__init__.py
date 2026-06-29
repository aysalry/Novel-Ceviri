from .google import GoogleFreeTranslateNew, GeminiTranslate
from .microsoft import MicrosoftEdgeTranslate
from .deepl import DeeplTranslate, DeeplProTranslate
from .openai import OpenAITranslate, OpenRouterTranslate
from .anthropic import ClaudeTranslate
from .custom import build_custom_engine_class

builtin_engines = (
    GoogleFreeTranslateNew, MicrosoftEdgeTranslate,
    DeeplTranslate, DeeplProTranslate, GeminiTranslate,
    OpenAITranslate, ClaudeTranslate, OpenRouterTranslate)

__all__ = [
    'GoogleFreeTranslateNew', 'MicrosoftEdgeTranslate',
    'DeeplTranslate', 'DeeplProTranslate', 'GeminiTranslate',
    'OpenAITranslate', 'ClaudeTranslate', 'OpenRouterTranslate',
    'builtin_engines', 'get_all_engines',
]


def get_all_engines():
    """builtin_engines plus a fresh class per user-defined custom engine --
    rebuilt on every call so editing/adding a custom engine in Settings
    takes effect immediately, no restart needed.
    """
    from ..core.config import get_config
    custom_engines = get_config().get('custom_engines', {})
    custom_classes = tuple(
        build_custom_engine_class(data) for data in custom_engines.values())
    return builtin_engines + custom_classes
