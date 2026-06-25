import re
import json
from urllib.parse import urljoin

from lxml import html as lxml_html

from ...core.i18n import _
from .. import chapter_cache
from ..models import ChapterContent, ChapterRef, NovelInfo, SearchResult
from ..source_base import NovelSource, NovelSourceError, clean_text

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _next_data_props(page_html):
    match = _NEXT_DATA_RE.search(page_html)
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return {}
    return data.get('props', {}).get('pageProps', {})


class NovelBuddySource(NovelSource):
    """NovelBuddy is a Next.js app -- the data we need is embedded as JSON
    in a <script id="__NEXT_DATA__"> tag on every page, so there's no HTML
    scraping involved, just picking the right keys out of that payload.

    A novel's page only ships its ~50 most recent chapters plus a separate
    "first chapter" pointer -- there's no bulk chapter-list endpoint we
    could find. When there are more chapters than that, _walk_chapter_gap
    fills in the rest by following nextChapter links one page at a time
    (slow for 1000+ chapter novels), and the result is cached to disk via
    chapter_cache so that walk only ever happens once per book.
    """

    domains = ('novelbuddy.com',)
    display_name = 'NovelBuddy'
    base_url = 'https://novelbuddy.com'
    # Higher request volume than the other sources (the chapter-gap walk
    # is one request per chapter) -- still respectful, just less padded.
    min_request_interval = 0.35

    def search(self, query):
        try:
            page_html = self._get(self.base_url + '/search', data={'q': query})
        except Exception as e:
            raise NovelSourceError(_('Arama başarısız: {}').format(e))
        items = _next_data_props(page_html).get('ssrItems') or []
        results = []
        for item in items:
            results.append(SearchResult(
                title=item.get('name') or item.get('slug', ''),
                url=urljoin(self.base_url, item.get('url', '')),
                source_name=self.display_name,
                cover_url=item.get('cover')))
        return results

    def get_chapter_count(self, url):
        try:
            page_html = self._get(url)
        except Exception as e:
            raise NovelSourceError(
                _('Roman sayfasına erişilemedi: {}').format(e))
        manga = _next_data_props(page_html).get('initialManga')
        if not manga:
            raise NovelSourceError(_('Roman bilgisi bulunamadı.'))
        return (manga.get('stats') or {}).get('chaptersCount', 0)

    def fetch_info(self, url, progress=None, cancel_request=None):
        try:
            page_html = self._get(url)
        except Exception as e:
            raise NovelSourceError(
                _('Roman sayfasına erişilemedi: {}').format(e))
        manga = _next_data_props(page_html).get('initialManga')
        if not manga:
            raise NovelSourceError(_('Roman bilgisi bulunamadı.'))

        title = manga.get('name') or url
        author = ', '.join(
            a.get('name', '') for a in (manga.get('authors') or [])
            if a.get('name'))
        genres = [
            g.get('name') for g in (manga.get('genres') or [])
            if g.get('name')]

        # The API returns chapters newest-first; we want reading order.
        raw_chapters = list(manga.get('chapters') or [])
        raw_chapters.reverse()
        chapters = [
            ChapterRef(
                title=c.get('name', ''),
                url=urljoin(self.base_url, c.get('url', '')))
            for c in raw_chapters]

        first_chapter = manga.get('firstChapter')
        if first_chapter and first_chapter.get('url'):
            first_url = urljoin(self.base_url, first_chapter['url'])
            if not any(c.url == first_url for c in chapters):
                chapters.insert(0, ChapterRef(
                    title=first_chapter.get('name', ''), url=first_url))

        chapters_count = (manga.get('stats') or {}).get(
            'chaptersCount', len(chapters))
        if chapters_count > len(chapters) and chapters:
            cached = chapter_cache.load(url)
            if cached and len(cached) >= chapters_count:
                chapters = cached
            else:
                chapters = self._walk_chapter_gap(
                    chapters, chapters_count, progress, cancel_request)
                if len(chapters) >= chapters_count:
                    chapter_cache.save(url, chapters)

        if not chapters:
            raise NovelSourceError(_('Bölüm listesi bulunamadı.'))
        return NovelInfo(
            title=title, author=author, cover_url=manga.get('cover'),
            source_url=url, chapters=chapters, genres=genres)

    def _walk_chapter_gap(self, known_chapters, total_count, progress,
                           cancel_request):
        """known_chapters[0] is the earliest chapter we know about (chapter
        1) and the rest is the newest-N tail from the initial fetch. Walk
        forward via nextChapter links to fill in the gap, splicing into
        the known tail as soon as we reach it instead of re-walking
        through chapters we already have.
        """
        known_by_url = {c.url: i for i, c in enumerate(known_chapters)}
        result = [known_chapters[0]]
        current_url = known_chapters[0].url
        seen = {current_url}

        while len(result) < total_count:
            if cancel_request and cancel_request():
                return known_chapters
            try:
                page_html = self._get(current_url)
            except Exception:
                break
            next_chapter = _next_data_props(page_html).get('nextChapter')
            if not next_chapter or not next_chapter.get('url'):
                break
            next_url = urljoin(self.base_url, next_chapter['url'])
            if next_url in seen:
                break
            seen.add(next_url)
            if next_url in known_by_url:
                result.extend(known_chapters[known_by_url[next_url]:])
                break
            result.append(ChapterRef(
                title=next_chapter.get('name', ''), url=next_url))
            current_url = next_url
            if progress:
                progress(len(result), total_count)
        return result

    def fetch_chapter(self, chapter_url):
        try:
            page_html = self._get(chapter_url)
        except Exception as e:
            raise NovelSourceError(_('Bölüm alınamadı: {}').format(e))
        chapter = _next_data_props(page_html).get('initialChapter')
        if not chapter:
            raise NovelSourceError(_('Bölüm içeriği bulunamadı.'))

        content_html = chapter.get('content') or ''
        tree = lxml_html.fromstring('<div>%s</div>' % content_html)
        paragraphs = [
            text for p in tree.xpath('.//p') if (text := clean_text(p))]
        return ChapterContent(
            title=chapter.get('name', ''), paragraphs=paragraphs)
