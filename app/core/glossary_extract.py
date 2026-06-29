"""Best-effort glossary-candidate extractor: scans a source file before
translation and surfaces repeated capitalized words (character names,
places, invented terms) as glossary candidates -- those are what
actually needs consistent translation, not common words, so raw word
frequency alone is a poor signal without the capitalization filter.
"""
import os
import re
from collections import Counter

XHTML_BODY_TAG = '{http://www.w3.org/1999/xhtml}body'

_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'is', 'was', 'were', 'are', 'be',
    'been', 'being', 'of', 'to', 'in', 'on', 'at', 'for', 'with', 'as', 'by',
    'that', 'this', 'these', 'those', 'it', 'its', 'he', 'she', 'they', 'you',
    'i', 'we', 'said', 'her', 'his', 'my', 'me', 'him', 'them', 'their',
    'your', 'our', 'us', 'if', 'so', 'not', 'no', 'do', 'did', 'does', 'have',
    'has', 'had', 'will', 'would', 'could', 'should', 'can', 'what', 'who',
    'when', 'where', 'why', 'how', 'there', 'here', 'then', 'than', 'just',
    'into', 'out', 'up', 'down', 'all', 'one', 'about', 'after', 'before',
    'over', 'chapter', 'mr', 'mrs', 'ms', 'however', 'well', 'even', 'great',
    'yet', 'still', 'now', 'though', 'although', 'perhaps', 'maybe',
    'suddenly', 'finally', 'meanwhile', 'indeed', 'instead', 'besides',
    'also', 'again', 'thus', 'therefore', 'nonetheless', 'okay', 'alright',
    'oh', 'ah', 'wait', 'unless', 'whether', 'since', 'while', 'until',
    'whatever', 'whenever', 'wherever', 'whoever', 'despite', 'regardless',
    'anyway', 'anyhow', 'otherwise', 'moreover', 'furthermore',
    'nevertheless', 'consequently', 'accordingly', 'hence', 'eventually',
    'currently', 'recently', 'immediately', 'naturally', 'obviously',
    'clearly', 'apparently', 'certainly', 'surely', 'probably', 'possibly',
    'sometimes', 'somehow', 'someone', 'something', 'somewhere', 'anyone',
    'anything', 'everyone', 'everything', 'nothing', 'nobody',
    # Common contractions -- a closed, well-known set, so listing them
    # outright is more reliable than trying to detect "verb + 't/'s/'re"
    # patterns algorithmically.
    "i'm", "i'll", "i've", "i'd", "you're", "you'll", "you've", "you'd",
    "he's", "he'll", "he'd", "she's", "she'll", "she'd", "it's", "it'll",
    "it'd", "we're", "we'll", "we've", "we'd", "they're", "they'll",
    "they've", "they'd", "that's", "that'll", "there's", "there'll",
    "here's", "what's", "what're", "who's", "who'll", "don't", "doesn't",
    "didn't", "won't", "wouldn't", "can't", "couldn't", "shouldn't",
    "isn't", "aren't", "wasn't", "weren't", "hasn't", "haven't", "hadn't",
    "let's", "ain't",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')

# Short connector words a multi-word title is allowed to bridge over --
# "Scholar of Yore", "Snake of Fate", "Baron of Corruption" all need the
# lowercase middle word to stay part of the one term instead of breaking
# it into two unrelated single words.
_CONNECTORS = {'of', 'the', 'and', 'in', 'on', 'for'}


def _is_candidate_word(word):
    return len(word) >= 3 and word[0].isupper() and word.lower() not in _STOPWORDS


def _find_phrases(sentence):
    """Yields (phrase, start_index) for each maximal run of capitalized
    words in a sentence, greedily bridging a single connector word when
    another capitalized word follows it -- this is what lets multi-word
    titles ("Mandated Punishers", "Scholar of Yore") get captured as one
    term instead of just their individual words.
    """
    words = _WORD_RE.findall(sentence)
    n = len(words)
    i = 0
    while i < n:
        if not _is_candidate_word(words[i]):
            i += 1
            continue
        start = i
        phrase_words = [words[i]]
        j = i + 1
        while j < n:
            if _is_candidate_word(words[j]):
                phrase_words.append(words[j])
                j += 1
                continue
            if (words[j].lower() in _CONNECTORS and j + 1 < n
                    and _is_candidate_word(words[j + 1])):
                phrase_words.append(words[j])
                j += 1
                continue
            break
        yield ' '.join(phrase_words), start
        i = j


def _page_text(page):
    root = page.data
    body = root.find('./%s' % XHTML_BODY_TAG)
    if body is None:
        body = root.find('./body')
    if body is None:
        body = root
    return ''.join(body.itertext())


def _read_text(path, input_format):
    if input_format == 'epub':
        from ..formats.epub import EpubBook
        book = EpubBook(path)
        return '\n'.join(_page_text(page) for page in book.pages)
    if input_format == 'srt':
        from .element import get_srt_elements
        elements = get_srt_elements(path, 'utf-8')
        return '\n'.join(element.get_text() for element in elements)
    with open(path, 'r', encoding='utf-8', errors='replace') as file:
        return file.read()


def count_characters(path, input_format):
    """Total character count of a file's translatable text -- used to
    warn the user about size before they commit to a paid engine.
    """
    return len(_read_text(path, input_format))


def extract_terms(path, input_format, top_n=200):
    """Returns up to top_n candidate glossary terms, most-repeated
    likely-proper-noun words and multi-word titles first.

    Raw frequency plus a capitalization filter alone still lets through
    ordinary words that happen to capitalize because they open a
    sentence ("However,", "Although", "They're") -- English capitalizes
    the first word of every sentence regardless of what that word is.
    The much stronger signal is capitalization in the MIDDLE of a
    sentence, where nothing grammatically requires it: a name like "Fang
    Yuan" gets capitalized there too ("He saw Fang Yuan again"), while
    "however" or "they're" would not ("...however, he..."). So a term
    only counts as a candidate if it appears capitalized at least once
    away from a sentence start; the stopword list stays as a second,
    belt-and-suspenders filter for short documents that don't give the
    mid-sentence signal much chance to show up.

    Terms aren't limited to single words -- _find_phrases() also chains
    adjacent capitalized words ("Mandated Punishers") and short
    connectors inside a title ("Scholar of Yore") into one candidate, so
    multi-word names/titles aren't lost as just their separate parts.
    """
    text = _read_text(path, input_format)
    total_counts = Counter()
    mid_sentence_phrases = set()

    for sentence in _SENTENCE_SPLIT_RE.split(text):
        for phrase, start_index in _find_phrases(sentence):
            total_counts[phrase] += 1
            if start_index > 0:
                mid_sentence_phrases.add(phrase)

    ranked = [
        phrase for phrase, count in total_counts.most_common()
        if count >= 2 and phrase in mid_sentence_phrases]
    return ranked[:top_n]


def merge_extracted_terms(glossary_path, terms):
    """Appends newly-found terms (translation left blank for the user to
    fill in) to the glossary file, skipping ones already present -- never
    overwrites a translation the user already typed in. Returns how many
    new terms were actually added.
    """
    existing_terms = set()
    existing_content = ''
    if os.path.exists(glossary_path):
        with open(
                glossary_path, 'r', encoding='utf-8',
                errors='replace') as file:
            existing_content = file.read().strip(chr(0xfeff)).strip()
        for group in re.split(r'\n{2,}', existing_content):
            lines = group.split('\n')
            if lines and lines[0].strip():
                existing_terms.add(lines[0].strip().lower())

    new_terms = [term for term in terms if term.lower() not in existing_terms]
    if not new_terms:
        return 0

    blocks = [existing_content] if existing_content else []
    blocks.extend(new_terms)
    with open(glossary_path, 'w', encoding='utf-8', newline='\n') as file:
        file.write('\n\n'.join(blocks))
    return len(new_terms)
