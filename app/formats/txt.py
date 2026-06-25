import re

from ..core.element import Element
from ..core.utils import open_file


class TxtElement(Element):
    """One translatable block of a plain-text file (a paragraph, separated
    from its neighbours by a blank line). Mirrors SrtElement/PgnElement in
    core/element.py: add_translation() folds the result back into
    self.element in place, get_translation() just reads it back.
    """

    def get_raw(self):
        return self.element

    def get_text(self):
        return self.element

    def get_content(self):
        return self.element

    def add_translation(self, translation=None):
        if translation is None:
            return
        if self.position == 'only':
            self.element = translation
        elif self.position in ('below', 'right'):
            self.element = '%s\n\n%s' % (self.element, translation)
        else:
            self.element = '%s\n\n%s' % (translation, self.element)

    def get_translation(self):
        return self.element


def get_txt_elements(path, encoding=None):
    content = open_file(path, encoding)
    blocks = re.split(r'\n\s*\n', content.strip())
    return [TxtElement(block.strip()) for block in blocks if block.strip()]


def save_txt(elements, output_path):
    with open(output_path, 'w', encoding='utf-8', newline='\n') as file:
        file.write('\n\n'.join(element.get_translation() for element in elements))


# A handful of ready-made chapter-heading patterns for the splitter dialog;
# the user can also type their own regex.
CHAPTER_PATTERN_PRESETS = {
    'Chapter N (English)': r'^[ \t]*Chapter\s+\d+.*$',
    'Bölüm N (Türkçe)': r'^[ \t]*B[öo]l[üu]m\s+\d+.*$',
    'Episode / Part N': r'^[ \t]*(Episode|Part)\s+\d+.*$',
    'Numbered heading (1. / 1) / #1)': r'^[ \t]*\d+[\.\)]\s+.*$',
}


def split_into_chapters(text, pattern):
    """Split one big raw text dump into (title, body) chapters using a
    heading regex matched line-by-line. Falls back to a single chapter
    containing the whole text when the pattern matches nothing.
    """
    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    matches = list(regex.finditer(text))
    if not matches:
        return [('', text.strip())]
    chapters = []
    for i, match in enumerate(matches):
        title = match.group(0).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            chapters.append((title, body))
    return chapters
