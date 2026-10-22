"""Parsing of the DIDL-Lite metadata that Navidrome sends to a media renderer."""

import logging
import xml.etree.ElementTree as ElementTree
import xml.sax.saxutils as saxutils

logger = logging.getLogger(__name__)

DIDL_NAMESPACE = 'urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/'
DC_NAMESPACE = 'http://purl.org/dc/elements/1.1/'
UPNP_NAMESPACE = 'urn:schemas-upnp-org:metadata-1-0/upnp/'


def _text(element, namespace: str, name: str) -> str:
    if element is None:
        return ''
    child = element.find(f'{{{namespace}}}{name}')
    if child is None or child.text is None:
        return ''
    return child.text.strip()


def _parse_duration(value: str) -> int:
    """Convert a DIDL duration such as ``0:03:45`` into seconds."""

    if not value:
        return 0

    parts = value.strip().split(':')
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return 0

    seconds = 0
    for number in numbers:
        seconds = seconds * 60 + number

    return seconds


def parse_didl_metadata(metadata: str) -> dict:
    """Return the track information of a DIDL-Lite document.

    The returned dictionary contains the keys ``title``, ``artist``, ``album``,
    ``art``, ``duration`` and ``uri``. Unknown values are empty strings.
    """

    result = {
        'title': '',
        'artist': '',
        'album': '',
        'art': '',
        'duration': 0,
        'uri': '',
    }

    if not metadata or not metadata.strip():
        return result

    try:
        root = ElementTree.fromstring(metadata)
    except ElementTree.ParseError as error:
        logger.warning('Could not parse the DIDL-Lite metadata: %s', error)
        return result

    item = root.find(f'{{{DIDL_NAMESPACE}}}item')
    if item is None:
        items = root.findall(f'.//{{{DIDL_NAMESPACE}}}item')
        item = items[0] if items else None

    if item is None:
        return result

    result['title'] = _text(item, DC_NAMESPACE, 'title')
    result['artist'] = _text(item, UPNP_NAMESPACE, 'artist')
    result['album'] = _text(item, UPNP_NAMESPACE, 'album')
    result['art'] = _text(item, UPNP_NAMESPACE, 'albumArtURI')

    resource = item.find(f'{{{DIDL_NAMESPACE}}}res')
    if resource is not None:
        result['uri'] = (resource.text or '').strip()
        result['duration'] = _parse_duration(resource.get('duration', ''))

    return result


def format_duration(seconds: int) -> str:
    """Format a number of seconds as the DIDL duration "H:MM:SS"."""

    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    return f'{hours}:{minutes:02d}:{secs:02d}'


def build_didl_metadata(track: dict) -> str:
    """Build the DIDL-Lite document of a track.

    The document is sent to the DLNA clients when the renderer changes the
    track, so that they show the new title instead of the old one.

    :param dict track: The track with the keys title, artist, album, art, duration and uri
    :return: The DIDL-Lite document
    :rtype: str
    """

    track = track or {}

    title = saxutils.escape(str(track.get('title') or ''))
    artist = saxutils.escape(str(track.get('artist') or ''))
    album = saxutils.escape(str(track.get('album') or ''))
    art = saxutils.escape(str(track.get('art') or ''))
    uri = saxutils.escape(str(track.get('uri') or ''))
    duration = format_duration(track.get('duration') or 0)
    identifier = saxutils.escape(str(track.get('id') or uri or title))

    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<DIDL-Lite xmlns="{DIDL_NAMESPACE}" xmlns:dc="{DC_NAMESPACE}" xmlns:upnp="{UPNP_NAMESPACE}">',
        f'  <item id="{identifier}" parentID="0" restricted="1">',
        f'    <dc:title>{title}</dc:title>',
        f'    <upnp:artist>{artist}</upnp:artist>',
        f'    <upnp:album>{album}</upnp:album>',
    ]

    if art:
        lines.append(f'    <upnp:albumArtURI>{art}</upnp:albumArtURI>')

    if uri:
        lines.append(
            f'    <res protocolInfo="http-get:*:audio/mpeg:*" duration="{duration}">{uri}</res>'
        )

    lines.extend([
        '  </item>',
        '</DIDL-Lite>',
        '',
    ])

    return '\n'.join(lines)
