from urllib.parse import urljoin

from lxml import html as lxml_html

from ...core.i18n import _
from ..models import ChapterContent, ChapterRef, NovelInfo
from ..source_base import NovelSource, NovelSourceError, clean_text


class MadaraSource(NovelSource):
    """Generic fallback for the very common 'Madara' WordPress novel theme
    used by a large number of aggregator sites (novelfire.net and
    novelight.net have their own, more reliable dedicated sources above --
    this one is only reached when no specific source matches the URL).
    """

    domains = ()  # never auto-selected by hostname; reached via probing only

    def probe(self, url):
        """Returns (looks_like_madara, page_html)."""
        try:
            page_html = self._get(url)
        except Exception:
            return False, None
        tree = lxml_html.fromstring(page_html)
        looks_like_madara = bool(
            tree.find_class('wp-manga-chapter') or tree.find_class('reading-content'))
        return looks_like_madara, page_html

    def fetch_info(self, url, progress=None, cancel_request=None):
        looks_like_madara, page_html = self.probe(url)
        if not looks_like_madara or page_html is None:
            raise NovelSourceError(
                _('Bu site şu anda desteklenmiyor (tanınan bir şablon değil).'))
        tree = lxml_html.fromstring(page_html)

        title_el = (
            tree.find_class('post-title') or tree.xpath('//h1')
            or tree.xpath('//title'))
        title = title_el[0].text_content().strip() if title_el else url

        cover_url = None
        cover_el = tree.xpath('//div[contains(@class,"summary_image")]//img/@src')
        if cover_el:
            cover_url = urljoin(url, cover_el[0])

        genres = [
            a.text_content().strip()
            for a in tree.xpath('//div[contains(@class,"genres-content")]//a')
            if a.text_content().strip()]

        chapters = []
        for a in tree.xpath('//li[contains(@class,"wp-manga-chapter")]/a'):
            href = a.get('href') or ''
            chapters.append(ChapterRef(
                title=a.text_content().strip(), url=urljoin(url, href)))
        chapters.reverse()  # Madara lists newest-first

        if not chapters:
            raise NovelSourceError(_('Bölüm listesi bulunamadı.'))
        return NovelInfo(
            title=title, cover_url=cover_url, source_url=url, chapters=chapters,
            genres=genres)

    def fetch_chapter(self, chapter_url):
        try:
            page_html = self._get(chapter_url)
        except Exception as e:
            raise NovelSourceError(_('Bölüm alınamadı: {}').format(e))
        tree = lxml_html.fromstring(page_html)

        content_el = tree.find_class('reading-content')
        if not content_el:
            raise NovelSourceError(
                _('Bölüm içeriği bulunamadı (şablon eşleşmedi).'))
        paragraphs = [
            text for p in content_el[0].xpath('.//p')
            if (text := clean_text(p))]

        title = ''
        title_el = tree.xpath('//ol[contains(@class,"breadcrumb")]//li[last()]')
        if title_el:
            title = title_el[0].text_content().strip()
        return ChapterContent(title=title, paragraphs=paragraphs)
