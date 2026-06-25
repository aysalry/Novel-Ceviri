from PyQt6.QtCore import QThread, pyqtSignal

from ..core.i18n import _
from ..core.logging_setup import logger
from ..formats.cover_generator import generate_cover_bytes
from ..formats.epub_builder import merge_and_build_epub
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
    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def __init__(self, source, novel_info, chapter_refs, output_path, parent=None):
        super().__init__(parent)
        self.source = source
        self.novel_info = novel_info
        self.chapter_refs = chapter_refs
        self.output_path = output_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self.chapter_refs)
        if total == 0:
            self.finished_error.emit(_('İndirilecek bölüm seçilmedi.'))
            return

        contents = []
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
                cover_bytes=cover_bytes)
        except Exception as e:
            logger.exception('EPUB build failed for %s', self.output_path)
            self.finished_error.emit(_('EPUB oluşturulamadı: {}').format(e))
            return
        if carried_over:
            self.log.emit(
                _('Var olan {} bölüm korunup yeni {} bölüm eklendi.')
                .format(carried_over, len(contents)))

        self.finished_ok.emit(self.output_path)
