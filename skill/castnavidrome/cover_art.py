"""Cover art for the Alexa skill.

The cover art of the media server is not reachable by Amazon, because the
URL of the media server needs the credentials of the user.  The skill
therefore serves the images itself and Amazon fetches them from the public
URL of the skill.

Ported from locqust/asknavidrome (MIT), see CREDITS.md.  The proxy with a
separate module and the fallback to the logo of the media server are our own
local changes.
"""

import logging
import urllib.error
import urllib.request
from urllib.parse import quote


logger = logging.getLogger(__name__)

DEFAULT_ART_URL = 'https://github.com/navidrome/navidrome/raw/master/resources/logo-192x192.png'

CONTENT_TYPES = {
    'image/jpeg': 'image/jpeg',
    'image/jpg': 'image/jpeg',
    'image/png': 'image/png',
    'image/gif': 'image/gif',
    'image/webp': 'image/webp',
}


def build_cover_art_url(base_url: str, cover_id: str) -> str:
    """Build the public URL of the cover art proxy

    :param str base_url: The public URL of the skill, without a trailing slash
    :param str cover_id: The ID of the cover art
    :return: The URL of the cover art
    :rtype: str
    """

    if not base_url or not cover_id:
        return ''

    return f'{base_url.rstrip("/")}/cover/{quote(str(cover_id), safe="")}'


def get_art_url(base_url: str, cover_id: str) -> str:
    """Get the URL of the cover art to show in the Alexa app

    If no cover art is available, the logo of the media server is used, so
    that a card never has an empty image.

    :param str base_url: The public URL of the skill, without a trailing slash
    :param str cover_id: The ID of the cover art
    :return: The URL of the image
    :rtype: str
    """

    cover_art_url = build_cover_art_url(base_url, cover_id)

    if not cover_art_url:
        return DEFAULT_ART_URL

    return cover_art_url


def fetch_cover_art(url: str, timeout: int = 10) -> tuple:
    """Fetch an image from the media server

    :param str url: The URL of the image
    :param int timeout: The timeout of the request in seconds
    :return: A tuple of the image data and its content type
    :rtype: tuple
    """

    logger.debug('Fetching the cover art')

    with urllib.request.urlopen(url, timeout=timeout) as response:
        data = response.read()
        content_type = response.headers.get('Content-Type', 'image/jpeg')

    if content_type not in CONTENT_TYPES:
        content_type = 'image/jpeg'

    return data, content_type
