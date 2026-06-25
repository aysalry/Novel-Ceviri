"""Tracks novels the user has already downloaded (url -> title, chapter
count at the time, where the EPUB was saved), so reopening the same novel
later can detect "N new chapters since last time" instead of treating it
as a brand new download.
"""
import os
import json

from ..core.config import config_root_dir
from ..core.utils import atomic_write_json

_LIBRARY_FILE = os.path.join(config_root_dir(), 'webnovel_library.json')


def _load_all():
    if not os.path.exists(_LIBRARY_FILE):
        return {}
    try:
        with open(_LIBRARY_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    except (ValueError, OSError):
        return {}


def _save_all(data):
    atomic_write_json(_LIBRARY_FILE, data, indent=2)


def get(novel_url):
    """Returns {'title', 'chapter_count', 'output_path'} or None."""
    return _load_all().get(novel_url)


def get_all():
    """Returns {novel_url: {'title', 'chapter_count', 'output_path'}}."""
    return _load_all()


def update_chapter_count(novel_url, chapter_count):
    """Used by the background new-chapter checker to record what it saw,
    without touching title/output_path (record() is for after an actual
    download; this is just "yes, I've now told the user about N").
    """
    data = _load_all()
    if novel_url in data:
        data[novel_url]['chapter_count'] = chapter_count
        _save_all(data)


def record(novel_url, title, chapter_count, output_path):
    data = _load_all()
    data[novel_url] = {
        'title': title,
        'chapter_count': chapter_count,
        'output_path': output_path,
    }
    _save_all(data)
