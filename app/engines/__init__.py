from .google import GoogleFreeTranslateNew, GeminiTranslate
from .microsoft import MicrosoftEdgeTranslate
from .deepl import DeeplTranslate, DeeplProTranslate, DeeplFreeTranslate

builtin_engines = (
    GoogleFreeTranslateNew, MicrosoftEdgeTranslate, DeeplFreeTranslate,
    DeeplTranslate, DeeplProTranslate, GeminiTranslate)

__all__ = [
    'GoogleFreeTranslateNew', 'MicrosoftEdgeTranslate', 'DeeplFreeTranslate',
    'DeeplTranslate', 'DeeplProTranslate', 'GeminiTranslate',
    'builtin_engines',
]
