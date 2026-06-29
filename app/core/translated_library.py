"""Tracks every file the app has translated (path -> title, format, when),
so the Kütüphanem tab can list them without scanning arbitrary folders for
EPUBs that might not even be ours.
"""
import os
import json
import threading
from datetime import datetime

from .config import config_root_dir
from .utils import atomic_write_json

_LIBRARY_FILE = os.path.join(config_root_dir(), 'translated_library.json')
# See webnovel/library.py's _lock for why -- get_all() here also writes
# (the self-heal below), so it needs the same protection as record()/
# remove(), not just the plain writers.
_lock = threading.Lock()


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


def record(path, title, input_format):
    with _lock:
        data = _load_all()
        data[path] = {
            'title': title,
            'input_format': input_format,
            'translated_at': datetime.now().isoformat(timespec='seconds'),
        }
        _save_all(data)


def get_all():
    """Returns {path: {'title', 'input_format', 'translated_at'}}.

    Entries whose file no longer exists on disk (moved/deleted outside
    the app) are dropped here rather than shown as a broken row -- the
    registry self-heals on read instead of accumulating dead entries.
    """
    with _lock:
        data = _load_all()
        alive = {
            path: info for path, info in data.items()
            if os.path.exists(path)}
        if len(alive) != len(data):
            _save_all(alive)
        return alive


def remove(path):
    with _lock:
        data = _load_all()
        if path in data:
            del data[path]
            _save_all(data)
