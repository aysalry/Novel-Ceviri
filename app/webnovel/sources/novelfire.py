import re
from urllib.parse import urljoin

from lxml import html as lxml_html

from ...core.i18n import _
from ..models import ChapterContent, ChapterRef, NovelInfo, SearchResult
from ..source_base import NovelSource, NovelSourceError, clean_text


def _chapter_number(url):
    match = re.search(r'/chapter-(\d+)', url)
    return int(match.group(1)) if match else 0


class NovelFireSource(NovelSource):
    domains = ('novelfire.net',)
    display_name = 'NovelFire'
    base_url = 'https://novelfire.net'

    def search(self, query):
        try:
            page_html = self._get(
                self.base_url + '/search', data={'keyword': query})
        except Exception as e:
            raise NovelSourceError(_('Arama başarısız: {}').format(e))
        tree = lxml_html.fromstring(page_html)

        results = []
        for item in tree.find_class('novel-item'):
            a = item.find('a')
            if a is None or not a.get('href'):
                continue
            title_el = item.find_class('novel-title')
            title = (
                title_el[0].text_content().strip() if title_el
                else (a.get('title') or '').strip())
            cover = item.xpath('.//img/@src')
            results.append(SearchResult(
                title=title, url=urljoin(self.base_url, a.get('href')),
                source_name=self.display_name,
                cover_url=urljoin(self.base_url, cover[0]) if cover else None))
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

        title_el = tree.find_class('novel-title')
        title = title_el[0].text_content().strip() if title_el else book_url

        author = ''
        author_el = tree.xpath('//*[@itemprop="author"]')
        if author_el:
            author = author_el[0].text_content().strip()

        cover_url = None
        cover_meta = tree.xpath('//meta[@property="og:image"]/@content')
        if cover_meta:
            cover_url = cover_meta[0]

        genres = [
            a.text_content().strip()
            for a in tree.xpath('//div[contains(@class,"categories")]//a')
            if a.text_content().strip()]

        chapters = self._fetch_all_chapters(book_url)
        if not chapters:
            raise NovelSourceError(
                _('Bölüm listesi bulunamadı. Adresi kontrol et.'))
        return NovelInfo(
            title=title, author=author, cover_url=cover_url,
            source_url=book_url, chapters=chapters, genres=genres)

    def _fetch_all_chapters(self, book_url):
        chapters = []
        seen_urls = set()
        page = 1
        while page <= 500:
            page_url = book_url + '/chapters'
            if page > 1:
                page_url += '?page=%d' % page
            try:
                page_html = self._get(page_url)
            except Exception as e:
                # A page genuinely failing to load (timeout, transient
                # 5xx) is not the same as "this was the last page" (that
                # case is new_count == 0 below) -- silently returning
                # whatever was gathered so far made an incomplete chapter
                # list look like a complete, successfully-fetched novel.
                raise NovelSourceError(
                    _('Bölüm listesi {}. sayfada kesildi (toplam {} bölüm '
                      'bulundu) -- ağ hatası: {}')
                    .format(page, len(chapters), e))
            tree = lxml_html.fromstring(page_html)
            new_count = 0
            for a in tree.xpath('//li/a[contains(@href, "/chapter-")]'):
                href = a.get('href') or ''
                full_url = urljoin(book_url, href)
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                title_el = a.find_class('chapter-title')
                title = (
                    title_el[0].text_content().strip() if title_el
                    else a.text_content().strip())
                chapters.append(ChapterRef(title=title, url=full_url))
                new_count += 1
            if new_count == 0:
                break
            page += 1
        chapters.sort(key=lambda c: _chapter_number(c.url))
        return chapters

    def fetch_chapter(self, chapter_url):
        try:
            page_html = self._get(chapter_url)
        except Exception as e:
            raise NovelSourceError(_('Bölüm alınamadı: {}').format(e))
        tree = lxml_html.fromstring(page_html)

        content_el = tree.get_element_by_id('content', None)
        if content_el is None:
            raise NovelSourceError(_('Bölüm içeriği bulunamadı.'))
        paragraphs = [
            text for p in content_el.xpath('./p')
            if (text := clean_text(p))]

        title_el = tree.find_class('chapter-title')
        title = title_el[-1].text_content().strip() if title_el else ''
        return ChapterContent(title=title, paragraphs=paragraphs)
