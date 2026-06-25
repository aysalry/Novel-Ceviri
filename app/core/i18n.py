"""Tiny in-house i18n helper.

Replaces Calibre's plugin-injected ``_()``/``load_translations()`` builtins.
Call ``set_language('tr'|'en')`` once at startup; every other module just
imports ``_`` and wraps English strings with it, same as before.
"""

_LANG = 'tr'

_STRINGS: dict[str, dict[str, str]] = {
    'en': {},
    'tr': {},
}


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in _STRINGS else 'en'


def get_language() -> str:
    return _LANG


def register(lang: str, strings: dict[str, str]) -> None:
    """Merge a batch of {english: translated} pairs for the given language."""
    _STRINGS.setdefault(lang, {}).update(strings)


def _(text: str) -> str:
    return _STRINGS.get(_LANG, {}).get(text, text)
