"""Disk cache for chapter lists that are expensive to (re)discover.

NovelBuddy has no bulk chapter-listing endpoint we could find -- building
the full list for a long-running novel means walking next-chapter links
one page at a time, which can take many minutes. Cache the result so that
walk only ever has to happen once per book.
"""
import os
import json

from ..core.config import config_root_dir
from ..core.utils import atomic_write_json
from .models import ChapterRef

_CACHE_FILE = os.path.join(config_root_dir(), 'webnovel_chapter_lists.json')


def _load_all():
    if not os.path.exists(_CACHE_FILE):
        return {}
    try:
        with open(_CACHE_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    except (ValueError, OSError):
        return {}


def _save_all(data):
    atomic_write_json(_CACHE_FILE, data)


def load(book_url):
    """Returns list[ChapterRef] or None if nothing is cached for this book."""
    entry = _load_all().get(book_url)
    if not entry:
        return None
    return [
        ChapterRef(title=item['title'], url=item['url'])
        for item in entry.get('chapters', [])]


def save(book_url, chapters):
    data = _load_all()
    data[book_url] = {
        'chapters': [{'title': c.title, 'url': c.url} for c in chapters]}
    _save_all(data)
