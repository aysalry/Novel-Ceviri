"""Remembers, per book path, which chapter the reader was last on -- not
scroll position within a chapter, just the chapter index, so reopening a
book in the built-in reader resumes roughly where the user left off.
"""
import os
import json
import threading

from .config import config_root_dir
from .utils import atomic_write_json

_PROGRESS_FILE = os.path.join(config_root_dir(), 'reading_progress.json')
# Same load-mutate-save race as the other JSON registries (see
# webnovel/library.py) -- only GUI-thread callers exist today, but
# locking here too means that stays true even if a background caller is
# ever added later, instead of silently becoming a hazard again.
_lock = threading.Lock()


def _load_all():
    if not os.path.exists(_PROGRESS_FILE):
        return {}
    try:
        with open(_PROGRESS_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    except (ValueError, OSError):
        return {}


def get_chapter_index(path):
    return _load_all().get(path, {}).get('chapter_index', 0)


def set_chapter_index(path, chapter_index, total_chapters=None):
    with _lock:
        data = _load_all()
        entry = {'chapter_index': chapter_index}
        # total_chapters only ever arrives from the reader itself;
        # preserve whatever was last recorded if this call doesn't have it.
        if total_chapters is not None:
            entry['total_chapters'] = total_chapters
        elif path in data:
            entry['total_chapters'] = data[path].get('total_chapters')
        data[path] = entry
        atomic_write_json(_PROGRESS_FILE, data, indent=2)


def get_progress_fraction(path):
    """Returns 0..1 for how far into the book the reader has gotten, or
    None if there's nothing to show (never opened in the built-in reader,
    or a format the reader doesn't track chapters for at all).
    """
    entry = _load_all().get(path)
    if not entry:
        return None
    total = entry.get('total_chapters')
    index = entry.get('chapter_index')
    if not total or index is None:
        return None
    return min(1.0, (index + 1) / total)
