"""Orchestrates: format reader -> element extraction -> translation ->
cache -> format writer. Replaces the plugin's lib/conversion.py, which did
the same job through Calibre's Plumber; here each format module already
hands back something core.element can consume directly, so this is just
glue.
"""
import os

from .core.utils import uid, dummy, detect_encoding
from .core.config import get_config
from .core.cache import get_cache
from .core.element import (
    get_element_handler, get_metadata_elements, get_toc_elements,
    get_page_elements, get_srt_elements)
from .core.translation import get_translator, get_translation

from .formats.epub import EpubBook
from .formats.txt import get_txt_elements, save_txt


def _prepare_pipeline(cache_id_parts, title, source_lang, target_lang,
                       direction):
    translator = get_translator()
    translator.set_source_lang(source_lang)
    translator.set_target_lang(target_lang)

    element_handler = get_element_handler(
        translator.placeholder, translator.separator, direction)
    element_handler.set_translation_lang(
        translator.get_iso639_target_code(target_lang))

    merge_length = str(element_handler.get_merge_length())
    cache_id = uid(
        *cache_id_parts, translator.name, target_lang, merge_length)
    cache = get_cache(cache_id)
    cache.set_info('title', title or '')
    cache.set_info('engine_name', translator.name)
    cache.set_info('target_lang', target_lang)
    cache.set_info('merge_length', merge_length)

    return translator, element_handler, cache


def _run_translation(translator, element_handler, cache, elements,
                      progress=None, log=None, streaming=None,
                      cancel_request=None, pause_request=None, is_batch=False):
    original_group = element_handler.prepare_original(elements)
    cache.save(original_group)
    # cache.all_paragraphs() would return every row ever stored under this
    # cache id, not just this run's -- the cache is keyed by output path,
    # and a webnovel download re-creates the same path with a different
    # chapter range every time (or any file gets edited/replaced and
    # retranslated at the same path), so the old, larger run's leftover
    # rows would silently get treated as "also needs translating" even
    # though they're not part of the current file at all. Each tuple in
    # original_group is (oid, md5, raw, content, ignored, attrs, page_id)
    # -- restrict to exactly the ids this run just extracted, skipping the
    # ones already marked ignored (empty content), matching what
    # all_paragraphs()'s "WHERE NOT ignored" used to filter.
    current_ids = [unit[0] for unit in original_group if not unit[4]]
    paragraphs = cache.get_paragraphs(current_ids)

    translation = get_translation(translator, log or dummy)
    translation.set_batch(is_batch)
    progress and translation.set_progress(progress)
    streaming and translation.set_streaming(streaming)
    cancel_request and translation.set_cancel_request(cancel_request)
    pause_request and translation.set_pause_request(pause_request)
    translation.set_callback(cache.update_paragraph)
    translation.handle(paragraphs)
    element_handler.add_translations(paragraphs)
    return paragraphs


def translate_epub(
        path, output_path, source_lang, target_lang, direction='auto',
        title=None, progress=None, log=None, streaming=None,
        cancel_request=None, pause_request=None, is_batch=False):
    book = EpubBook(path)
    translator, element_handler, cache = _prepare_pipeline(
        (path,), title or os.path.basename(path), source_lang, target_lang,
        direction)

    elements = []
    elements.extend(get_metadata_elements(book.metadata))
    elements.extend(get_toc_elements(book.toc.nodes, []))
    elements.extend(get_page_elements(book.pages))

    _run_translation(
        translator, element_handler, cache, elements, progress, log,
        streaming, cancel_request, pause_request, is_batch)

    book.save(output_path)
    cache.done()
    return output_path


def translate_txt(
        path, output_path, source_lang, target_lang, direction='auto',
        title=None, encoding=None, progress=None, log=None,
        streaming=None, cancel_request=None, pause_request=None,
        is_batch=False):
    encoding = encoding or detect_encoding(path)
    elements = get_txt_elements(path, encoding)
    translator, element_handler, cache = _prepare_pipeline(
        (path, encoding), title or os.path.basename(path), source_lang,
        target_lang, direction)

    _run_translation(
        translator, element_handler, cache, elements, progress, log,
        streaming, cancel_request, pause_request, is_batch)

    save_txt(elements, output_path)
    cache.done()
    return output_path


def translate_srt(
        path, output_path, source_lang, target_lang, direction='auto',
        title=None, encoding=None, progress=None, log=None,
        streaming=None, cancel_request=None, pause_request=None,
        is_batch=False):
    encoding = encoding or detect_encoding(path)
    elements = get_srt_elements(path, encoding)
    translator, element_handler, cache = _prepare_pipeline(
        (path, encoding), title or os.path.basename(path), source_lang,
        target_lang, direction)

    _run_translation(
        translator, element_handler, cache, elements, progress, log,
        streaming, cancel_request, pause_request, is_batch)

    with open(output_path, 'w', encoding='utf-8', newline='\n') as file:
        file.write(
            '\n\n'.join(element.get_translation() for element in elements))
    cache.done()
    return output_path


TRANSLATORS_BY_FORMAT = {
    'epub': translate_epub,
    'txt': translate_txt,
    'srt': translate_srt,
}


def translate_file(input_format, *args, **kwargs):
    handler = TRANSLATORS_BY_FORMAT.get(input_format)
    if handler is None:
        raise ValueError('Unsupported format: %s' % input_format)
    return handler(*args, **kwargs)
