from ..core.i18n import _
from .source_base import NovelSourceError, hostname
from .sources.madara import MadaraSource
from .sources.novelbuddy import NovelBuddySource
from .sources.novelfire import NovelFireSource
from .sources.novelight import NovelightSource

SOURCES = (NovelFireSource(), NovelightSource(), NovelBuddySource())
GENERIC_FALLBACK = MadaraSource()

# Confirmed by direct testing -- these block plain HTTP requests even with
# realistic browser headers (Cloudflare or similar). Rather than chase
# bot-evasion, we surface this clearly instead of silently failing.
KNOWN_BLOCKED_DOMAINS = {
    'empirenovel.com': _(
        'Bu site bot koruması (Cloudflare) kullanıyor; otomatik olarak '
        'erişilemiyor.'),
    'lightnovelpub.me': _(
        'Bu sitenin bölüm sayfaları bot koruması kullanıyor; bölüm metni '
        'çekilemiyor.'),
    'novellive.app': _(
        'Bu sitenin bölüm sayfaları bot koruması kullanıyor; bölüm metni '
        'çekilemiyor.'),
}


def search_all(query):
    """Search every searchable source and pool the results, tagged with
    which source each came from so the GUI can show e.g. "[NovelFire]
    Shadow Slave" and let the user pick which site's copy to use.
    """
    results = []
    errors = []
    for source in SOURCES:
        try:
            results.extend(source.search(query))
        except Exception as e:
            errors.append('%s: %s' % (source.display_name, e))
    return results, errors


def get_source_for_url(url):
    host = hostname(url)
    if host in KNOWN_BLOCKED_DOMAINS:
        raise NovelSourceError(KNOWN_BLOCKED_DOMAINS[host])

    for source in SOURCES:
        if source.handles(url):
            return source

    looks_like_madara, _page_html = GENERIC_FALLBACK.probe(url)
    if looks_like_madara:
        return GENERIC_FALLBACK

    raise NovelSourceError(_(
        'Bu site şu anda desteklenmiyor. Şu an için novelfire.net, '
        'novelight.net, novelbuddy.com ve "Madara" temalı birçok roman '
        'sitesi destekleniyor.'))
