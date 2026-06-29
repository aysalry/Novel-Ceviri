import os

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.i18n import _
from ..core.logging_setup import logger
from ..formats.cover_generator import generate_cover_bytes
from ..formats.epub_builder import merge_and_build_epub, read_existing_chapters
from ..webnovel import content_cache, library
from ..webnovel.registry import get_source_for_url, search_all
from ..webnovel.source_base import NovelSourceError


class NovelSearchWorker(QThread):
    finished_ok = pyqtSignal(list, list)  # list[SearchResult], list[str] errors

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        results, errors = search_all(self.query)
        self.finished_ok.emit(results, errors)


class SearchCoverFetchWorker(QThread):
    """Search results can come from several different sites in one go,
    each with its own cover_url -- fetched here, one at a time in the
    background, so the results grid can render immediately with
    placeholders and fill in real covers as they arrive instead of
    blocking the UI until every single one has downloaded.
    """

    cover_ready = pyqtSignal(int, bytes)  # index into the results list

    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.results = results
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for index, result in enumerate(self.results):
            if self._cancelled:
                return
            if not result.cover_url:
                continue
            try:
                source = get_source_for_url(result.url)
                cover_bytes = source.fetch_cover_bytes(result.cover_url)
            except Exception:
                continue
            if cover_bytes and not self._cancelled:
                self.cover_ready.emit(index, cover_bytes)


class LibraryCheckWorker(QThread):
    """Periodically scans every novel the user has previously downloaded
    and checks (cheaply -- see NovelSource.get_chapter_count) whether it
    now has more chapters than last time.
    """

    finished_ok = pyqtSignal(list)  # list[(url, title, old_count, new_count)]

    def run(self):
        updates = []
        for url, entry in library.get_all().items():
            try:
                source = get_source_for_url(url)
                current_count = source.get_chapter_count(url)
            except Exception:
                continue
            old_count = entry.get('chapter_count', 0)
            if current_count > old_count:
                updates.append((url, entry.get('title', url), old_count, current_count))
        self.finished_ok.emit(updates)


class NovelInfoWorker(QThread):
    finished_ok = pyqtSignal(object, object)  # source, NovelInfo
    finished_error = pyqtSignal(str)
    # Only meaningful for sources whose chapter list takes a slow,
    # multi-request walk to assemble (currently just NovelBuddy on long
    # novels) -- otherwise simply never emitted.
    list_progress = pyqtSignal(int, int)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            source = get_source_for_url(self.url)
            info = source.fetch_info(
                self.url,
                progress=lambda cur, tot: self.list_progress.emit(cur, tot),
                cancel_request=lambda: self._cancelled)
        except NovelSourceError as e:
            self.finished_error.emit(str(e))
        except Exception as e:
            logger.exception('fetch_info failed for %s', self.url)
            self.finished_error.emit(_('Beklenmeyen hata: {}').format(e))
        else:
            self.finished_ok.emit(source, info)


class NovelDownloadWorker(QThread):
    progress = pyqtSignal(float, str)
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(str, int)  # output_path, failed_chapter_count
    finished_error = pyqtSignal(str)

    def __init__(self, source, novel_info, chapter_refs, output_path,
                 keep_existing_count=0, parent=None):
        super().__init__(parent)
        self.source = source
        self.novel_info = novel_info
        self.chapter_refs = chapter_refs
        self.output_path = output_path
        self.keep_existing_count = keep_existing_count
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.chapter_refs)
        if total == 0:
            self.finished_error.emit(_('İndirilecek bölüm seçilmedi.'))
            return

        contents = []
        failed_count = 0
        for index, chapter_ref in enumerate(self.chapter_refs, start=1):
            if self._cancelled:
                self.finished_error.emit(_('İptal edildi.'))
                return
            self.progress.emit(index / total, chapter_ref.title)

            cached = content_cache.load(chapter_ref.url)
            if cached is not None:
                contents.append(cached)
                self.log.emit(
                    _('Önbellekten alındı: {}')
                    .format(cached.title or chapter_ref.title))
                continue

            try:
                content = self.source.fetch_chapter(chapter_ref.url)
            except Exception as e:
                logger.exception('fetch_chapter failed for %s', chapter_ref.url)
                self.log.emit(_('Hata ({}): {}').format(chapter_ref.title, e))
                failed_count += 1
                continue
            if not content.title:
                content.title = chapter_ref.title
            content_cache.save(chapter_ref.url, content)
            contents.append(content)
            self.log.emit(
                _('İndirildi: {} ({} paragraf)')
                .format(content.title, len(content.paragraphs)))

        if self._cancelled:
            self.finished_error.emit(_('İptal edildi.'))
            return
        if not contents:
            self.finished_error.emit(_('Hiçbir bölüm indirilemedi.'))
            return

        self.progress.emit(1.0, _('EPUB oluşturuluyor...'))
        cover_bytes = None
        if self.novel_info.cover_url:
            cover_bytes = self.source.fetch_cover_bytes(self.novel_info.cover_url)
        if not cover_bytes:
            try:
                cover_bytes = generate_cover_bytes(
                    self.novel_info.title, self.novel_info.author)
            except Exception:
                cover_bytes = None

        try:
            carried_over = merge_and_build_epub(
                self.novel_info, contents, self.output_path,
                cover_bytes=cover_bytes,
                keep_existing_count=self.keep_existing_count)
        except Exception as e:
            logger.exception('EPUB build failed for %s', self.output_path)
            self.finished_error.emit(_('EPUB oluşturulamadı: {}').format(e))
            return
        if carried_over:
            self.log.emit(
                _('Var olan {} bölüm korunup yeni {} bölüm eklendi.')
                .format(carried_over, len(contents)))
        if failed_count:
            # Each failure already got its own log line above, but that's
            # easy to miss in a long run -- the EPUB still gets built from
            # whatever did succeed (better than discarding it all), so
            # this can't be a hard error, but the caller needs the count
            # to tell the user the result isn't actually complete.
            self.log.emit(
                _('UYARI: {} bölüm indirilemedi, EPUB eksik olabilir.')
                .format(failed_count))

        self.finished_ok.emit(self.output_path, failed_count)


class LibraryUpdateWorker(QThread):
    """Bulk counterpart to NovelDownloadWorker: walks every tracked novel
    (or a specific subset, for a single-row "Güncelle" click) and
    downloads whatever chapters have appeared since the last check,
    reusing the exact same fetch/merge logic so an update behaves
    identically to a fresh download of just the new chapters.
    """

    novel_started = pyqtSignal(str, str)  # url, title
    novel_progress = pyqtSignal(str, float, str)  # url, fraction, message
    novel_log = pyqtSignal(str, str)  # url, message
    novel_finished = pyqtSignal(str, str, str)  # url, status, message
    queue_finished = pyqtSignal()

    def __init__(self, urls=None, parent=None):
        super().__init__(parent)
        # None means "every tracked novel"; a specific list is used by
        # the per-row update button to update just one.
        self.urls = urls
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        entries = library.get_all()
        urls = self.urls if self.urls is not None else list(entries.keys())
        for url in urls:
            if self._cancelled:
                break
            entry = entries.get(url)
            if entry is None:
                continue
            title = entry.get('title', url)
            self.novel_started.emit(url, title)
            try:
                self._update_one(url, title, entry.get('output_path'))
            except NovelSourceError as e:
                self.novel_finished.emit(url, 'error', str(e))
            except Exception as e:
                logger.exception('Library update failed for %s', url)
                self.novel_finished.emit(url, 'error', str(e))
        self.queue_finished.emit()

    def _update_one(self, url, title, output_path):
        source = get_source_for_url(url)
        info = source.fetch_info(
            url,
            progress=lambda current, total: self.novel_progress.emit(
                url, current / total if total else 0,
                _('Bölüm listesi alınıyor: {}/{}').format(current, total)),
            cancel_request=lambda: self._cancelled)
        if self._cancelled:
            self.novel_finished.emit(url, 'canceled', _('İptal edildi.'))
            return

        existing_count = 0
        if output_path and os.path.exists(output_path):
            try:
                existing_count = len(read_existing_chapters(output_path))
            except Exception:
                existing_count = 0

        new_refs = [
            ref for ref in info.chapters[existing_count:] if not ref.locked]
        if not new_refs:
            library.update_chapter_count(url, len(info.chapters))
            self.novel_finished.emit(url, 'done', _('Yeni bölüm yok.'))
            return

        contents = []
        failed_count = 0
        total = len(new_refs)
        for index, chapter_ref in enumerate(new_refs, start=1):
            if self._cancelled:
                self.novel_finished.emit(url, 'canceled', _('İptal edildi.'))
                return
            self.novel_progress.emit(url, index / total, chapter_ref.title)

            cached = content_cache.load(chapter_ref.url)
            if cached is not None:
                contents.append(cached)
                continue
            try:
                content = source.fetch_chapter(chapter_ref.url)
            except Exception as e:
                self.novel_log.emit(
                    url, _('Hata ({}): {}').format(chapter_ref.title, e))
                failed_count += 1
                continue
            if not content.title:
                content.title = chapter_ref.title
            content_cache.save(chapter_ref.url, content)
            contents.append(content)

        if not contents:
            self.novel_finished.emit(
                url, 'error', _('Hiçbir yeni bölüm indirilemedi.'))
            return

        cover_bytes = None
        if info.cover_url:
            cover_bytes = source.fetch_cover_bytes(info.cover_url)
        if not cover_bytes:
            try:
                cover_bytes = generate_cover_bytes(info.title, info.author)
            except Exception:
                cover_bytes = None

        merge_and_build_epub(
            info, contents, output_path, cover_bytes=cover_bytes)
        if failed_count:
            # Recording the full info.chapters count here when some of
            # new_refs failed would tell the next "Tümünü Güncelle" run
            # those chapters are already accounted for -- they'd never
            # get retried, and the EPUB would be permanently missing
            # whichever ones failed. Recording the conservative count
            # instead means the next run re-includes them in new_refs
            # (the cache makes re-checking the ones that already
            # succeeded this time cheap, not a wasted re-download).
            library.update_chapter_count(url, existing_count + len(contents))
            self.novel_finished.emit(
                url, 'done',
                _('{} yeni bölüm eklendi, {} bölüm indirilemedi.')
                .format(len(contents), failed_count))
        else:
            library.update_chapter_count(url, len(info.chapters))
            self.novel_finished.emit(
                url, 'done',
                _('{} yeni bölüm eklendi.').format(len(contents)))
