"""Disk cache for fetched chapter CONTENT, keyed by chapter URL.

Lets an interrupted batch download (crash, cancel, dropped connection)
resume from where it left off on retry instead of re-fetching chapters it
already has -- each chapter is written to its own file as soon as it's
fetched, so partial progress always survives.
"""
import os
import json
import hashlib

from ..core.config import config_root_dir
from ..core.utils import atomic_write_json
from .models import ChapterContent

_CACHE_DIR = os.path.join(config_root_dir(), 'webnovel_chapter_content')


def _path_for(chapter_url):
    digest = hashlib.sha1(chapter_url.encode('utf-8')).hexdigest()
    return os.path.join(_CACHE_DIR, digest + '.json')


def load(chapter_url):
    path = _path_for(chapter_url)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as file:
            data = json.load(file)
    except (ValueError, OSError):
        return None
    return ChapterContent(
        title=data.get('title', ''), paragraphs=data.get('paragraphs', []))


def save(chapter_url, content):
    atomic_write_json(
        _path_for(chapter_url),
        {'title': content.title, 'paragraphs': content.paragraphs})
