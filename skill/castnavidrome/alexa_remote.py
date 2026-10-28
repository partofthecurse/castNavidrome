# Alexa Remote API endpoints, parameterised by domain.
# For Europe (amazon.de/etc.): api.eu.amazonalexa.com
# For North America (amazon.com): api.amazon.com
ALEXA_API_HOST_MAP = {
    'com': 'api.amazon.com',
    'de': 'api.eu.amazonalexa.com',
}

import json
import logging
import re
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .amazon_login import AmazonSession, AmazonLoginError
from .localization import alexa_command, normalize_locale

logger = logging.getLogger(__name__)


class AlexaRemoteError(RuntimeError):
    def __init__(self, message: str, status_code: int = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def find_devices_by_name(devices: list, name: str) -> list:
    normalized_name = name.strip().casefold()
    return [
        device for device in devices
        if isinstance(device, dict)
        and isinstance(device.get('name'), str)
        and device['name'].strip().casefold() == normalized_name
    ]


def build_control_text(command: str, skill_name: str, volume=None, locale: str = 'en-US') -> str:
    """Build the voice command of a playback control

    The command is built in the language of the locale, because an Alexa
    device only understands a voice command in the language that it is set
    to.  The text of the command and the locale that is sent with it have
    to match, otherwise the device does not understand the command.

    :param str command: The name of the command
    :param str skill_name: The invocation name of the skill
    :param volume: The volume level (ignored)
    :param str locale: The locale of the command
    :return: The voice command
    :rtype: str
    """

    try:
        return alexa_command(command, locale, skill_name=skill_name)
    except ValueError:
        raise ValueError('Unsupported Alexa control command.') from None


# The text of a text command that is sent to an Alexa device must not be
# too long, otherwise the Alexa service rejects it.  About 250 characters
# is the practical limit for such a command, this value stays below it.
MAX_TEXT_COMMAND_LENGTH = 240


def _fit_text(text: str, max_length: int) -> str:
    """Cut text to at most max_length characters

    The cut happens at a word boundary when possible, so that no word is
    split in the middle.

    :param str text: The text to shorten
    :param int max_length: The maximum length of the result
    :return: The shortened text
    :rtype: str
    """

    if len(text) <= max_length:
        return text

    if max_length <= 0:
        return ''

    cut = text[:max_length]
    space = cut.rfind(' ')

    if space > 0:
        return cut[:space]

    return cut


def _strip_parentheses(text: str) -> str:
    """Remove parenthetical additions from a title for a voice command

    Alexa's voice command handling often cannot cope with live/remaster
    tags and other parenthetical additions in song titles (e.g.
    ``Holiday (live at Makuhari Messe, Tokyo, Japan, 13/07/05)``).
    Stripping them makes the command shorter and easier for the device to
    understand.

    :param str text: The text to clean
    :return: The text without parenthetical parts
    :rtype: str
    """

    cleaned = re.sub(r'\s*\([^)]*\)', '', text or '')

    return ' '.join(cleaned.split())


class AlexaTextCommandClient:
    def __init__(self, cookie_file: str = None, domain: str = 'amazon.com', timeout: int = 10,
                 opener=None, session: AmazonSession = None) -> None:
        self.domain = domain
        self.timeout = timeout
        self.session = session
        self.opener = opener or build_opener()
        if session:
            self.cookies = dict(session.cookies) if session.cookies else {}
            self.csrf = session.csrf
            # Also load cookies from file if available (needed for Alexa Remote API)
            if cookie_file and not self.cookies:
                try:
                    file_cookies = self._load_cookies(cookie_file)
                    if file_cookies:
                        self.cookies = file_cookies
                        if not self.csrf:
                            self.csrf = next((value for name, value in self.cookies.items() if name.lower() == 'csrf'), None)
                except AlexaRemoteError:
                    pass
        else:
            if cookie_file is None:
                raise AlexaRemoteError('No Alexa cookie file or Amazon session configured.')
            self.cookies = self._load_cookies(cookie_file)
            self.csrf = next((value for name, value in self.cookies.items() if name.lower() == 'csrf'), None)
            if not self.csrf:
                raise AlexaRemoteError('The Alexa cookie file has no csrf cookie.')
        # Dynamically resolved Alexa API host (from /api/endpoints).  Falls back
        # to ``alexa.{domain}`` when unset.
        self.api_host: str | None = None

    @staticmethod
    def _load_cookies(cookie_file: str) -> dict:
        path = Path(cookie_file)
        if not path.is_file():
            raise AlexaRemoteError('The Alexa cookie file does not exist.')

        cookies = {}
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parsed_cookie = SimpleCookie()
            try:
                parsed_cookie.load(line)
            except Exception:
                parsed_cookie = SimpleCookie()

            if parsed_cookie:
                cookies.update({name: morsel.value for name, morsel in parsed_cookie.items()})
            elif '=' in line:
                name, value = line.split('=', 1)
                cookies[name.strip()] = value.strip()

        return cookies

    def _request(self, path: str, payload: dict = None, locale: str = 'en-US') -> bytes:
        domain = self.domain
        # Normalize domain: 'amazon.de' -> 'de', 'amazon.com' -> 'com'
        domain_key = domain.split('amazon.')[-1] if 'amazon.' in domain else domain
        # Use the dynamically resolved Alexa API host (from /api/endpoints) when
        # available, otherwise fall back to ``alexa.{domain}``.
        if self.api_host:
            alexa_host = self.api_host
        else:
            alexa_host = f'alexa.{self.domain}'
        url = f'https://{alexa_host}{path}'
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        headers = {
            'Accept': 'application/json; charset=utf-8',
            'Cookie': '; '.join(f'{name}={value}' for name, value in self.cookies.items()),
            'User-Agent': 'PitanguiBridge/2.2.527420.0-[PLATFORM=Android][MANUFACTURER=samsung][RELEASE=13][BRAND=samsung][SDK=33][MODEL=S2]',
            'Accept-Language': normalize_locale(locale),
        }
        if self.csrf:
            headers['csrf'] = self.csrf
        if data is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'

        request = Request(url, data=data, headers=headers)
        # Use cookies directly (opener) if cookies are available (Alexa Remote API requires cookies)
        if self.cookies:
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return response.read()
            except HTTPError as error:
                raise AlexaRemoteError(f'Alexa returned HTTP {error.code}.', status_code=error.code) from None
            except URLError:
                raise AlexaRemoteError('Could not connect to the Alexa service.') from None
        if self.session is not None:
            try:
                return self.session.request(url, data=data, headers=headers)
            except AmazonLoginError as error:
                raise AlexaRemoteError(str(error)) from error
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as error:
            raise AlexaRemoteError(f'Alexa returned HTTP {error.code}.', status_code=error.code) from None
        except URLError:
            raise AlexaRemoteError('Could not connect to the Alexa service.') from None

    def get_endpoints(self) -> dict | None:
        """Query /api/endpoints and cache the Alexa API host.

        Alexa-remote2 does the same: it asks Amazon for the correct API host
        instead of hardcoding ``alexa.amazon.com``.  This avoids HTML responses
        when the default host does not serve the requested endpoint.

        :return: The parsed JSON response, or None on failure.
        :rtype: dict | None
        """

        try:
            response = self._request('/api/endpoints')
        except AlexaRemoteError as error:
            logger.warning('Could not query Alexa endpoints: %s', error)
            return None

        try:
            data = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning('Alexa endpoints returned HTML instead of JSON: %r', response[:300])
            return None

        if not isinstance(data, dict):
            return None

        # Prefer websiteApiUrl/alexaApiUrl, fall back to websiteApiUrl.
        api_url = data.get('alexaApiUrl') or data.get('websiteApiUrl')
        if isinstance(api_url, str) and api_url:
            host = api_url
            for prefix in ('https://', 'http://'):
                if host.startswith(prefix):
                    host = host[len(prefix):]
                    break
            # Strip any trailing path.
            host = host.split('/', 1)[0]
            self.api_host = host
            logger.debug('Using Alexa API host %s.', host)

        return data

    def list_devices(self) -> list:
        # Resolve the correct Alexa API host first (alexa-remote2 pattern).
        if self.api_host is None:
            self.get_endpoints()

        # Try the newer endpoint first, fall back to older ones if needed
        last_error = None
        hosts_to_try = []
        if self.api_host:
            hosts_to_try.append(self.api_host)
        # Fallback hosts for different regions
        if self.domain in ('amazon.de', 'de'):
            hosts_to_try.extend(['eu-api-alexa.amazon.de', 'api.eu.amazonalexa.com', 'alexa.amazon.de'])
        elif self.domain in ('amazon.com', 'com'):
            hosts_to_try.extend(['api.amazonalexa.com', 'pitangui.amazon.com', 'alexa.amazon.com'])
        else:
            hosts_to_try.extend(['alexa.amazon.com'])
        # Deduplicate while preserving order
        seen_hosts = set()
        hosts_to_try = [h for h in hosts_to_try if not (h in seen_hosts or seen_hosts.add(h))]

        paths = ['/api/devices-v2/device?cached=false', '/api/devices?cached=false', '/api/devices-v2']

        for host in hosts_to_try:
            self.api_host = host
            for path in paths:
                try:
                    response = self._request(path)
                except AlexaRemoteError as error:
                    last_error = error
                    continue

                try:
                    data = json.loads(response)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    last_error = AlexaRemoteError('Alexa returned an invalid device response.')
                    continue

                devices = []
                if isinstance(data, dict):
                    devices = data.get('devices') or data.get('deviceList') or data.get('items') or []
                elif isinstance(data, list):
                    devices = data
                else:
                    last_error = AlexaRemoteError('Alexa returned an invalid device list.')
                    continue

                if not isinstance(devices, list):
                    last_error = AlexaRemoteError('Alexa returned an invalid device list.')
                    continue

                return [
                    {
                        'name': (device.get('accountName') or device.get('deviceTypeFriendlyName') or
                                 device.get('friendlyName') or device.get('name') or
                                 device.get('displayName') or ''),
                        'deviceOwnerCustomerId': (device.get('deviceOwnerCustomerId') or
                                                  device.get('ownerCustomerId') or
                                                  device.get('customerId') or ''),
                        'deviceType': device.get('deviceType') or device.get('deviceTypeId') or '',
                        'deviceFamily': device.get('deviceFamily') or device.get('familyName') or '',
                        'serialNumber': device.get('serialNumber') or device.get('dsn') or device.get('deviceSerialNumber') or '',
                        'online': device.get('online') if device.get('online') is not None else device.get('isOnline', False),
                    }
                    for device in devices
                    if isinstance(device, dict)
                ]

        if last_error:
            raise last_error
        raise AlexaRemoteError('Alexa returned an invalid device response.') from None

    def send_text_command(self, device: dict, text: str, locale: str = 'en-US') -> None:
        """Send a voice command to an Alexa device

        The text of the command has to be written in the language of the
        locale, because the device interprets it with the language model of
        its own language.

        :param device: The Alexa device that is addressed
        :param str text: The voice command
        :param str locale: The locale of the command
        """

        locale = normalize_locale(locale)

        sequence = {
            '@type': 'com.amazon.alexa.behaviors.model.Sequence',
            'startNode': {
                '@type': 'com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode',
                'type': 'Alexa.TextCommand',
                'skillId': 'amzn1.ask.1p.tellalexa',
                'operationPayload': {
                    'deviceType': device['deviceType'],
                    'deviceSerialNumber': device['serialNumber'],
                    'customerId': device['deviceOwnerCustomerId'],
                    'locale': locale,
                    'text': text,
                },
            },
        }
        command = {
            'behaviorId': 'PREVIEW',
            'sequenceJson': json.dumps(sequence, separators=(',', ':')),
            'status': 'ENABLED',
        }
        self._request('/api/behaviors/preview', command, locale=locale)

    def send_play_command(self, device: dict, skill_name: str, locale: str = 'en-US', playlist_name: str = '') -> None:
        """Ask an Alexa device to play a play list or random music

        The text of the command and the locale that is sent with it are
        built in the same language, so that the device understands it.

        :param device: The Alexa device that is addressed
        :param str skill_name: The invocation name of the skill
        :param str locale: The locale of the command
        :param str playlist_name: The name of the play list, empty for random music
        """

        if playlist_name:
            text_command = alexa_command('play_playlist', locale, skill_name=skill_name, playlist_name=playlist_name)
        else:
            text_command = alexa_command('play_random', locale, skill_name=skill_name)

        self.send_text_command(device, text_command, locale)

    def get_device_volume(self, device: dict) -> int | None:
        """Read the current volume of an Alexa device

        The volume is read from the Alexa device on the Alexa scale of 0 to 10.

        First tries the ``allDeviceVolumes`` endpoint which returns the volume
        of all devices as JSON.  Falls back to the single-device
        ``/api/device-volume`` endpoint when that is unavailable.

        :param device: The Alexa device
        :return: The volume, from 0 to 10, or None when it cannot be read
        :rtype: int | None
        """

        serial = device.get('serialNumber', '')
        device_type = device.get('deviceType', '')

        # Resolve the correct Alexa API host first (alexa-remote2 pattern).
        if self.api_host is None:
            self.get_endpoints()

        volume = self._volume_from_all_devices(serial, device_type)
        if volume is not None:
            return volume

        path = f'/api/device-volume?deviceSerialNumber={serial}&deviceType={device_type}'
        response = self._request(path)

        try:
            data = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning('Alexa device-volume returned HTML instead of JSON: %r', response[:300])
            return None

        volume = None

        if isinstance(data, dict):
            volume = data.get('volume')
            if isinstance(volume, dict):
                volume = volume.get('value')

        if volume is None:
            logger.warning('Alexa returned an invalid volume response: %r', response[:300])
            return None

        try:
            volume = int(volume)
        except (TypeError, ValueError):
            logger.warning('Alexa returned an invalid volume value: %r', response[:300])
            return None

        return max(0, min(10, volume))

    def _volume_from_all_devices(self, serial: str, device_type: str) -> int | None:
        """Read all device volumes and return the one matching serial/deviceType.

        :return: The volume, from 0 to 10, or None when not found.
        :rtype: int | None
        """

        path = '/api/devices/deviceType/dsn/audio/v1/allDeviceVolumes'
        try:
            response = self._request(path)
        except AlexaRemoteError as error:
            logger.warning('Could not read all device volumes: %s', error)
            return None

        try:
            data = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning('Alexa allDeviceVolumes returned HTML instead of JSON: %r', response[:300])
            return None

        entries = data if isinstance(data, list) else (data.get('devices') if isinstance(data, dict) else None)
        if not isinstance(entries, list):
            return None

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_serial = entry.get('deviceSerialNumber') or entry.get('serialNumber') or ''
            entry_type = entry.get('deviceType') or entry.get('type') or ''
            if entry_serial != serial or (device_type and entry_type != device_type):
                continue
            volume = entry.get('volume')
            if isinstance(volume, dict):
                volume = volume.get('value')
            if volume is None:
                continue
            try:
                return max(0, min(10, int(volume)))
            except (TypeError, ValueError):
                continue
        return None


def build_play_track_text(skill_name: str, title: str, artist: str, locale: str = 'en-US',
                          quiet: bool = False) -> str:
    """Build the voice command that plays a track

    The command is built in the language of the locale, because an Alexa
    device only understands a voice command in the language that it is set
    to.

    The quiet command plays the track without an answer of the skill, so
    that the title and the artist are not read out.  It is used for the
    tracks that the renderer starts on its own.

    :param str skill_name: The invocation name of the skill
    :param str title: The title of the track
    :param str artist: The artist of the track
    :param str locale: The locale of the command
    :param bool quiet: True when the skill should not answer
    :return: The voice command
    :rtype: str
    """

    key = 'play_track_quiet' if quiet else 'play_track'

    # Parenthetical additions in song titles (live/remaster tags, dates,
    # venues) confuse Alexa's voice command handling and make the command
    # longer.  Strip them before building the command so the artist stays
    # at the end and the device can actually match the track.
    title = _strip_parentheses(title)

    text = alexa_command(key, locale, skill_name=skill_name, title=title, artist=artist)

    if len(text) <= MAX_TEXT_COMMAND_LENGTH:
        return text

    # The title comes before the artist in the command, so the title is
    # shortened first.  The artist is always kept complete at the end of
    # the command, so that it is not cut off or moved to the wrong place.
    excess = len(text) - MAX_TEXT_COMMAND_LENGTH
    title = _fit_text(title, max(0, len(title) - excess))
    text = alexa_command(key, locale, skill_name=skill_name, title=title, artist=artist)

    if len(text) > MAX_TEXT_COMMAND_LENGTH:
        excess = len(text) - MAX_TEXT_COMMAND_LENGTH
        artist = _fit_text(artist, max(0, len(artist) - excess))
        text = alexa_command(key, locale, skill_name=skill_name, title=title, artist=artist)

    return text
