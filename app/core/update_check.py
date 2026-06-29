"""Checks GitHub's releases API for a newer published version than the
one currently running. The app has no auto-update mechanism, so this
is the whole feature: notice a newer release exists, point the user at
the download page, let them do the rest.
"""
import json

from .utils import request

REPO = 'aysalry/Novel-Ceviri'
RELEASES_API_URL = 'https://api.github.com/repos/%s/releases/latest' % REPO
RELEASES_PAGE_URL = 'https://github.com/%s/releases/latest' % REPO


def _parse_version(version_string):
    """'v1.2.3' or '1.2.3' -> (1, 2, 3); non-numeric parts become 0 so an
    unexpected tag format never raises, it just sorts as low as possible.
    """
    cleaned = version_string.lstrip('vV')
    parts = []
    for part in cleaned.split('.'):
        digits = ''.join(c for c in part if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_update_available(current, latest):
    return _parse_version(latest) > _parse_version(current)


def get_latest_release():
    """Returns {'version': 'v1.2.3', 'url': release_page_url} for the
    latest published GitHub release. Raises on any failure (network,
    rate limit, repo renamed...) -- callers (UpdateCheckWorker) are
    responsible for swallowing errors, since a failed check should
    never surface as an error to the user, just silence.
    """
    response = request(
        RELEASES_API_URL,
        headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'NovelCeviri-UpdateChecker'},
        timeout=10)
    data = json.loads(response)
    return {
        'version': data['tag_name'],
        'url': data.get('html_url') or RELEASES_PAGE_URL,
    }
