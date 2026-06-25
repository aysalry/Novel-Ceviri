import os

RESOURCES_DIR = os.path.dirname(os.path.abspath(__file__)) + os.sep + 'resources'

THEME_FILES = {
    'light': 'theme.qss',
    'dark': 'theme_dark.qss',
}


def stylesheet_for(theme_name):
    filename = THEME_FILES.get(theme_name, THEME_FILES['light'])
    path = os.path.join(RESOURCES_DIR, filename)
    if not os.path.exists(path):
        return ''
    with open(path, 'r', encoding='utf-8') as file:
        return file.read()


def apply_theme(app, theme_name):
    app.setStyleSheet(stylesheet_for(theme_name))
