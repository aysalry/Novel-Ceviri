import os
import sys
import json

from .utils import atomic_write_json


APP_DIR_NAME = 'NovelCeviri'
_OLD_APP_DIR_NAME = 'CeviriNovel'

defaults = {
    'ui_language': 'tr',
    'ui_theme': 'light',
    'close_button_behavior': 'exit',
    'webnovel_check_enabled': False,
    'webnovel_check_interval_hours': 6,
    'target_lang': 'Turkish',
    'source_lang': 'Auto detect',
    'translate_engine': 'Google(Free)New',
    'engine_preferences': {},
    'proxy_enabled': False,
    'proxy_setting': [],

    'output_path': None,
    'to_source_folder': True,

    'cache_enabled': True,
    'cache_path': None,

    'translation_position': 'below',
    'column_gap': {
        '_type': 'percentage',
        'percentage': 10,
        'space_count': 6,
    },
    'original_color': None,
    'translation_color': None,

    'priority_rules': [],
    'rule_mode': 'normal',
    'filter_scope': 'text',
    'filter_rules': [],
    'ignore_rules': [],
    'reserve_rules': [],

    'glossary_enabled': False,
    'glossary_path': None,

    'merge_enabled': True,
    'merge_length': 1800,

    'ebook_metadata': {},
    'search_paths': [],

    'log_translation': True,
}


def config_root_dir() -> str:
    """Per-user app-data folder, e.g. %APPDATA%/NovelCeviri on Windows."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    elif sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Application Support')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser(
            '~/.config')
    path = os.path.join(base, APP_DIR_NAME)
    if not os.path.exists(path):
        # One-time migration from the app's old name -- without this,
        # everyone's existing settings/library/cache would silently look
        # empty after the rename.
        old_path = os.path.join(base, _OLD_APP_DIR_NAME)
        if os.path.exists(old_path):
            try:
                os.rename(old_path, path)
            except OSError:
                pass
    os.makedirs(path, exist_ok=True)
    return path


def config_file_path() -> str:
    return os.path.join(config_root_dir(), 'config.json')


class JSONConfig(dict):
    """Minimal stand-in for Calibre's JSONConfig: a dict that lazily loads
    from / persists to a JSON file on disk, falling back to .defaults for
    missing keys.
    """

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.defaults: dict = {}
        self.refresh()

    def refresh(self):
        self.clear()
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as file:
                    self.update(json.load(file))
            except Exception:
                pass

    def commit(self):
        atomic_write_json(self.path, dict(self), indent=2)

    def get(self, key, default=None):
        if key in self:
            return self[key]
        if default is not None:
            return default
        return self.defaults.get(key)


class Configuration:
    def __init__(self, config):
        self.preferences = config

    def get(self, key, default=None):
        """Get config value with dot flavor. e.g. get('a.b.c')"""
        if key is None:
            return default
        temp = self.preferences
        for part in key.split('.'):
            if isinstance(temp, dict) and part in temp:
                temp = temp.get(part)
                continue
            temp = defaults.get(part)
        return default if temp is None else temp

    def set(self, key, value):
        """Set config value with dot flavor. e.g. set('a.b.c', '1')"""
        temp = self.preferences
        keys = key.split('.')
        while len(keys) > 0:
            part = keys.pop(0)
            if len(keys) > 0:
                if part in temp and isinstance(temp.get(part), dict):
                    temp = temp[part]
                    continue
                temp[part] = {}
                temp = temp.get(part)
                continue
        temp[part] = value

    def update(self, *args, **kwargs):
        self.preferences.update(*args, **kwargs)

    def delete(self, key):
        if key in self.preferences:
            del self.preferences[key]
            return True
        return False

    def refresh(self):
        self.preferences.refresh()

    def commit(self):
        self.preferences.commit()

    def save(self, *args, **kwargs):
        self.update(*args, **kwargs)
        self.commit()


_preferences = None


def get_config() -> Configuration:
    global _preferences
    if _preferences is None:
        _preferences = JSONConfig(config_file_path())
        _preferences.defaults = defaults
    return Configuration(_preferences)
