import time
from urllib.parse import urlparse

import requests as requests_lib

from ..core.utils import request

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}


class NovelSourceError(Exception):
    """Raised for any scraping failure; the message is safe to show as-is."""


def hostname(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith('www.') else host


_NOISE_TAGS = ('script', 'style', 'noscript', 'iframe', 'ins')


def clean_text(element) -> str:
    """Text content of an lxml element with ad/script noise stripped first.

    lxml's text_content() concatenates every descendant text node,
    including the raw JS source inside <script> tags (ad networks like to
    inject these between paragraphs) -- it has no concept of "not actually
    visible text" the way a browser's rendered view does.
    """
    noise_elements = [
        noise for tag in _NOISE_TAGS for noise in element.iter(tag)]
    for noise in noise_elements:
        parent = noise.getparent()
        if parent is not None:
            parent.remove(noise)
    return element.text_content().strip()


class NovelSource:
    """One website's worth of scraping logic. Subclasses implement
    fetch_info() (title/author/cover/chapter list) and fetch_chapter()
    (one chapter's title + paragraphs).
    """

    domains: tuple[str, ...] = ()
    display_name = ''
    # Minimum gap between consecutive requests made through this source --
    # a chapter-list page is dozens of requests fired in a tight loop, easy
    # to get IP-throttled on without this.
    min_request_interval = 0.6

    def __init__(self):
        self._last_request_at = 0.0

    @classmethod
    def handles(cls, url: str) -> bool:
        return hostname(url) in cls.domains

    def search(self, query: str):
        """Returns a list[SearchResult]. Optional -- sources that can't be
        searched (e.g. the generic Madara fallback, which has no fixed
        domain) just don't override this.
        """
        raise NotImplementedError

    def fetch_info(self, url: str, progress=None, cancel_request=None):
        """progress(current, total) and cancel_request() -> bool are only
        meaningful for sources whose chapter list takes more than one
        request to assemble (e.g. NovelBuddy's chapter-by-chapter walk);
        sources that don't need them can just accept and ignore.
        """
        raise NotImplementedError

    def fetch_chapter(self, chapter_url: str):
        raise NotImplementedError

    def get_chapter_count(self, url: str) -> int:
        """Cheap "how many chapters does this novel have right now" check,
        for the periodic new-chapter-available scan -- deliberately
        separate from fetch_info() so that scan never accidentally
        triggers a slow full chapter-list walk (NovelBuddy) just to
        answer a yes/no question. Default: fall back to fetch_info() for
        sources where building the list is already cheap.
        """
        return len(self.fetch_info(url).chapters)

    def _throttle(self):
        wait = self.min_request_interval - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _get(self, url, data=None, headers=None, timeout=20, attempts=3):
        merged_headers = dict(BROWSER_HEADERS)
        if headers:
            merged_headers.update(headers)
        last_error = None
        for attempt in range(attempts):
            self._throttle()
            self._last_request_at = time.monotonic()
            try:
                return request(
                    url, data=data, headers=merged_headers, method='GET',
                    timeout=timeout)
            except requests_lib.exceptions.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response is not None else 0
                if status in (429, 503) and attempt + 1 < attempts:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise
        raise last_error

    def fetch_cover_bytes(self, cover_url):
        try:
            self._throttle()
            self._last_request_at = time.monotonic()
            response = request(
                cover_url, headers=BROWSER_HEADERS, method='GET',
                timeout=20, raw_object=True)
            return response.content
        except Exception:
            return None
