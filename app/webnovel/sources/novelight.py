import json
import re
from urllib.parse import urljoin

from lxml import html as lxml_html

from ...core.i18n import _
from ..models import ChapterContent, ChapterRef, NovelInfo, SearchResult
from ..source_base import NovelSource, NovelSourceError, clean_text

AJAX_BASE = 'https://novelight.net'


def _leading_number(title):
    match = re.match(r'\s*(\d+)', title)
    return int(match.group(1)) if match else None


class NovelightSource(NovelSource):
    domains = ('novelight.net',)
    display_name = 'Novelight'

    def search(self, query):
        try:
            page_html = self._get(
                AJAX_BASE + '/catalog/', data={'search': query})
        except Exception as e:
            raise NovelSourceError(_('Arama başarısız: {}').format(e))
        tree = lxml_html.fromstring(page_html)

        results = []
        seen_urls = set()
        for a in tree.xpath('//a[contains(@class,"item")][@href]'):
            href = a.get('href') or ''
            if '/book/' not in href:
                continue
            url = urljoin(AJAX_BASE, href)
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title_el = a.find_class('title')
            title = (
                title_el[0].text_content().strip() if title_el
                else a.text_content().strip())
            cover = a.xpath('.//img/@src')
            results.append(SearchResult(
                title=title, url=url, source_name=self.display_name,
                cover_url=urljoin(AJAX_BASE, cover[0]) if cover else None))
        return results

    def _book_url(self, url):
        match = re.match(r'(https?://[^/]+/book/[^/?#]+)', url)
        return match.group(1) if match else url.rstrip('/')

    def fetch_info(self, url, progress=None, cancel_request=None):
        book_url = self._book_url(url)
        try:
            page_html = self._get(book_url)
        except Exception as e:
            raise NovelSourceError(
                _('Roman sayfasına erişilemedi: {}').format(e))
        tree = lxml_html.fromstring(page_html)

        title_el = tree.xpath('//header[contains(@class,"header-manga")]//h1')
        title = title_el[0].text_content().strip() if title_el else book_url

        author = ''
        author_el = tree.find_class('author')
        if author_el:
            # Strip the leading icon glyph / "Author:" label noise.
            author = re.sub(r'^[^A-Za-z0-9]+', '', author_el[0].text_content()).strip()

        cover_url = None
        panel = tree.xpath('//div[contains(@class,"page-panel")]/@style')
        if panel:
            match = re.search(r'url\(([^)]+)\)', panel[0])
            if match:
                cover_url = urljoin(book_url, match.group(1).strip('\'"'))

        genres = []
        for item in tree.find_class('item'):
            label = item.find_class('sub-header')
            if label and label[0].text_content().strip() == 'Genres':
                info_div = item.find_class('info')
                if info_div:
                    genres = [
                        a.text_content().strip() for a in info_div[0].xpath('.//a')
                        if a.text_content().strip()]
                break

        csrf_match = re.search(r'CSRF_TOKEN\s*=\s*"([^"]+)"', page_html)
        book_id_match = re.search(r'BOOK_ID\s*=\s*"(\d+)"', page_html)
        if not (csrf_match and book_id_match):
            raise NovelSourceError(
                _('Bölüm listesi alınamadı (site yapısı değişmiş olabilir).'))

        chapters = self._fetch_all_chapters(
            page_html, book_url, csrf_match.group(1), book_id_match.group(1))
        if not chapters:
            raise NovelSourceError(
                _('Bölüm listesi bulunamadı. Adresi kontrol et.'))
        return NovelInfo(
            title=title, author=author, cover_url=cover_url,
            source_url=book_url, chapters=chapters, genres=genres)

    def _parse_chapter_fragment(self, fragment_html, chapters, seen_urls):
        tree = lxml_html.fromstring('<div>%s</div>' % fragment_html)
        added = 0
        for a in tree.xpath('//a[contains(@href, "/book/chapter/")]'):
            href = a.get('href') or ''
            full_url = urljoin(AJAX_BASE, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            title_el = a.find_class('title')
            title = (
                title_el[0].text_content().strip() if title_el
                else a.text_content().strip())
            locked = bool(a.find_class('cost'))
            chapters.append(ChapterRef(title=title, url=full_url, locked=locked))
            added += 1
        return added

    def _fetch_all_chapters(self, first_page_html, book_url, csrf, book_id):
        chapters = []
        seen_urls = set()
        self._parse_chapter_fragment(first_page_html, chapters, seen_urls)

        page = 2
        while page <= 500:
            try:
                response_text = self._get(
                    AJAX_BASE + '/book/ajax/chapter-pagination',
                    data={
                        'csrfmiddlewaretoken': csrf, 'book_id': book_id,
                        'page': page},
                    headers={
                        'X-Requested-With': 'XMLHttpRequest',
                        'Referer': book_url})
                payload = json.loads(response_text)
            except Exception as e:
                # A genuine failure (network/parse) is not the same as
                # "ran out of pages" (that's the empty-fragment/added==0
                # checks below) -- silently returning whatever was
                # gathered so far made an incomplete chapter list look
                # like a complete, successfully-fetched novel.
                raise NovelSourceError(
                    _('Bölüm listesi {}. sayfada kesildi (toplam {} bölüm '
                      'bulundu) -- hata: {}')
                    .format(page, len(chapters), e))
            fragment = payload.get('html', '')
            if not fragment.strip():
                break
            added = self._parse_chapter_fragment(fragment, chapters, seen_urls)
            if added == 0:
                break
            page += 1

        # Chapters are keyed by a non-sequential internal id, but most
        # novels number their titles ("1435 chapter..."); sort by that
        # when present, otherwise fall back to fetch order reversed (pages
        # come back newest-first).
        numbered = [c for c in chapters if _leading_number(c.title) is not None]
        if len(numbered) == len(chapters):
            chapters.sort(key=lambda c: _leading_number(c.title))
        else:
            chapters.reverse()
        return chapters

    def fetch_chapter(self, chapter_url):
        match = re.search(r'/chapter/(\d+)', chapter_url)
        if not match:
            raise NovelSourceError(_('Geçersiz bölüm adresi.'))
        chapter_id = match.group(1)

        try:
            # The actual chapter text loads via AJAX after the page itself,
            # so this fetch is only to establish the session/referer chain
            # the AJAX call below expects -- its title tag isn't reliably
            # splittable into "book title" vs "chapter title", so the
            # caller falls back to the chapter list's ChapterRef.title.
            self._get(chapter_url)
        except Exception as e:
            raise NovelSourceError(_('Bölüm alınamadı: {}').format(e))
        title = ''

        try:
            response_text = self._get(
                AJAX_BASE + '/book/ajax/read-chapter/' + chapter_id,
                headers={
                    'X-Requested-With': 'XMLHttpRequest',
                    'Referer': chapter_url})
            payload = json.loads(response_text)
        except Exception as e:
            raise NovelSourceError(_('Bölüm içeriği alınamadı: {}').format(e))

        raw_content = payload.get('content', '').strip()
        if not raw_content:
            raise NovelSourceError(_('Bölüm içeriği boş döndü (kilitli olabilir).'))
        content_class = payload.get('class', '')
        content_tree = lxml_html.fromstring(raw_content)
        if content_class:
            paragraph_divs = content_tree.xpath(
                '//div[contains(@class, "%s")]/div' % content_class)
        else:
            # No class to scope by -- this grabs every div on the
            # fragment, which is wrong often enough to flag rather than
            # silently hand back garbled/empty paragraphs.
            paragraph_divs = content_tree.xpath('//div')
        paragraphs = [
            text for div in paragraph_divs if (text := clean_text(div))]
        if not paragraphs:
            raise NovelSourceError(
                _('Bölüm metni ayrıştırılamadı (site yapısı değişmiş '
                  'olabilir).'))
        return ChapterContent(title=title, paragraphs=paragraphs)
