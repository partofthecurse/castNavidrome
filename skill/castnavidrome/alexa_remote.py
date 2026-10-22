"""Client for the Alexa Remote API.

The module talks to the Alexa service of Amazon to list the Alexa devices of
an account and to send text and play commands to them.  Authentication is done
either with a static cookie file or with an authenticated Amazon session
(username, password and TOTP).
"""

import json
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .amazon_login import AmazonSession, AmazonLoginError
from .localization import alexa_command, normalize_locale


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
    :param volume: The volume level, from 0 to 10
    :param str locale: The locale of the command
    :return: The voice command
    :rtype: str
    """

    if command == 'set_volume':
        if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 10:
            raise ValueError('volume must be an integer between 0 and 10.')
        return alexa_command('set_volume', locale, volume=volume)

    try:
        return alexa_command(command, locale, skill_name=skill_name)
    except ValueError:
        raise ValueError('Unsupported Alexa control command.') from None


class AlexaTextCommandClient:
    def __init__(self, cookie_file: str = None, domain: str = 'amazon.com', timeout: int = 10,
                 opener=None, session: AmazonSession = None) -> None:
        self.domain = domain
        self.timeout = timeout
        self.session = session
        self.opener = opener or build_opener()
        if session:
            self.cookies = session.cookies
            self.csrf = session.csrf
        else:
            if cookie_file is None:
                raise AlexaRemoteError('No Alexa cookie file or Amazon session configured.')
            self.cookies = self._load_cookies(cookie_file)
            self.csrf = next((value for name, value in self.cookies.items() if name.lower() == 'csrf'), None)
            if not self.csrf:
                raise AlexaRemoteError('The Alexa cookie file has no csrf cookie.')

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
        url = f'https://alexa.{self.domain}{path}'
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        headers = {
            'Accept': 'application/json; charset=utf-8',
            'Cookie': '; '.join(f'{name}={value}' for name, value in self.cookies.items()),
            'User-Agent': 'PitanguiBridge/2.2.527420.0-[PLATFORM=Android][MANUFACTURER=samsung][RELEASE=13][BRAND=samsung][SDK=33][MODEL=S2]',
            'csrf': self.csrf,
            'Accept-Language': normalize_locale(locale),
        }
        if data is not None:
            headers['Content-Type'] = 'application/json; charset=utf-8'

        request = Request(url, data=data, headers=headers)
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

    def list_devices(self) -> list:
        response = self._request('/api/devices-v2/device?cached=false')
        try:
            devices = json.loads(response).get('devices', [])
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            raise AlexaRemoteError('Alexa returned an invalid device response.') from None

        if not isinstance(devices, list):
            raise AlexaRemoteError('Alexa returned an invalid device list.')

        return [
            {
                'name': device.get('accountName') or device.get('deviceTypeFriendlyName') or '',
                'deviceOwnerCustomerId': device.get('deviceOwnerCustomerId', ''),
                'deviceType': device.get('deviceType', ''),
                'deviceFamily': device.get('deviceFamily') or '',
                'serialNumber': device.get('serialNumber', ''),
                'online': device.get('online', False),
            }
            for device in devices
            if isinstance(device, dict)
        ]

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

    return alexa_command(key, locale, skill_name=skill_name, title=title, artist=artist)
