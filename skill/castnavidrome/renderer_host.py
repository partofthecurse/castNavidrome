"""Hosts one UPnP media renderer per Alexa device.

The host discovers the Alexa devices of the configured account, filters them
and exposes every remaining device as a UPnP media renderer. The renderers
are announced via SSDP and controlled through the Alexa text command API.
"""

import asyncio
import logging
import os
import signal
import socket
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from castnavidrome.alexa_device_filter import DeviceFilter
from castnavidrome.amazon_login import AioAmazonSession, AmazonSession
from castnavidrome.amazon_login import resolve_cookie_file
from castnavidrome.alexa_remote import (
    AlexaRemoteError,
    AlexaTextCommandClient,
    build_control_text,
    build_play_track_text,
)
from castnavidrome.localization import normalize_locale
from castnavidrome.renderer_registry import RendererRegistry
from castnavidrome.renderer_bridge import RendererBridge, RendererBridgeServer
from castnavidrome.upnp.renderer import MediaRenderer, RendererCommandError
from castnavidrome.upnp.server import RendererServer
from castnavidrome.upnp.ssdp import SsdpServer

logger = logging.getLogger(__name__)

DEFAULT_PORT = 49443
DEFAULT_REFRESH_SECONDS = 300
DEFAULT_MIN_REFRESH_SECONDS = 60
DEFAULT_STATE_FILE = '/var/lib/castnavidrome/renderer-devices.json'
DEFAULT_DISABLE_REFRESH = 'true'
DEFAULT_SSDP_MX = 2.0
DEFAULT_SSDP_SEARCH_COUNT = 1
DEFAULT_SSDP_SEARCH_DELAY = 0.15
DEFAULT_CLIENT_TIMEOUT = 0.0

# How long the renderer waits before it follows a PlaybackStopped event of
# the skill.  A voice interaction with the skill can stop the playback for a
# moment, the renderer only stops when the playback did not continue.
ECHO_STOP_GRACE_SECONDS = 5.0

# The prefix of the renderer names is optional.  Without it the renderers
# are named after the Alexa device, which is what most DLNA clients show
# in their player list.
DEFAULT_NAME_PREFIX = ''

# The language of the voice commands that are sent to the Alexa devices.
# It has to be the language that the devices are set to, otherwise they do
# not understand the commands.
DEFAULT_ALEXA_LOCALE = 'en-US'

# How the renderers announce the tracks they play.
#
# 'explicit' announces the tracks that a user starts, so that the title and
# the artist are read out, and plays the tracks that the renderer starts on
# its own, when the previous track has ended, without an answer.
# 'always' announces every track, 'never' announces no track at all.
ANNOUNCE_EXPLICIT = 'explicit'
ANNOUNCE_ALWAYS = 'always'
ANNOUNCE_NEVER = 'never'
ANNOUNCE_MODES = (ANNOUNCE_EXPLICIT, ANNOUNCE_ALWAYS, ANNOUNCE_NEVER)
DEFAULT_ANNOUNCE = ANNOUNCE_EXPLICIT


def detect_advertise_host() -> str:
    """Return the IP address of the primary network interface."""

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 53))
        address = probe.getsockname()[0]
        if address:
            return address
    except OSError:
        pass
    finally:
        probe.close()

    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return '127.0.0.1'


class AlexaRendererController:
    """Forwards the playback commands of a renderer to the Alexa device."""

    def __init__(self, cookie_file: str = None, domain: str = 'amazon.com', skill_name: str = 'castnavidrome',
                 locale: str = DEFAULT_ALEXA_LOCALE, subsonic_connection=None,
                 announce: str = DEFAULT_ANNOUNCE, aioamazon_session=None) -> None:
        self.cookie_file = cookie_file
        self.domain = domain
        self.skill_name = skill_name
        self.locale = normalize_locale(locale)
        self.subsonic_connection = subsonic_connection
        self.announce = announce if announce in ANNOUNCE_MODES else DEFAULT_ANNOUNCE
        self.aioamazon_session = aioamazon_session
        self.bridge = RendererBridge()

    def _client(self) -> AlexaTextCommandClient:
        return AlexaTextCommandClient(
            self.cookie_file, domain=self.domain,
        )

    def _device(self, renderer: MediaRenderer) -> dict:
        device = renderer.device
        if not device:
            raise RendererCommandError('The Alexa device of this renderer is unknown.')
        return device

    def _send(self, renderer: MediaRenderer, text: str) -> None:
        device = self._device(renderer)

        try:
            if self.aioamazon_session and self.aioamazon_session.is_configured:
                self.aioamazon_session.send_text_command(device, text, locale=self.locale)
            else:
                self._client().send_text_command(device, text, locale=self.locale)
        except Exception as error:
            raise RendererCommandError(str(error)) from error

        logger.info('Sent the Alexa command "%s" to %s.', text, device.get('name'))

    def _quiet(self, quiet: bool) -> bool:
        """Decide whether a track is played without an announcement

        :param bool quiet: True when the renderer starts the track on its own
        :return: True when the skill should not answer
        :rtype: bool
        """

        if self.announce == ANNOUNCE_NEVER:
            return True

        if self.announce == ANNOUNCE_ALWAYS:
            return False

        return quiet

    def _send_track(self, renderer: MediaRenderer, track: dict, quiet: bool) -> None:
        identifier = track.get('id') or ''
        if identifier:
            try:
                self.bridge.register_start(renderer.udid, identifier)
            except Exception as error:
                logger.warning('Could not register renderer playback for voice control: %s', error)
        try:
            self._send(renderer, build_play_track_text(self.skill_name, track.get('title', ''),
                                                      track.get('artist', ''), locale=self.locale,
                                                      quiet=self._quiet(quiet)))
        except Exception:
            if identifier:
                try:
                    self.bridge.cancel_start(renderer.udid, identifier)
                except Exception as error:
                    logger.warning('Could not clear renderer playback registration: %s', error)
            raise

    def play(self, renderer: MediaRenderer, track: dict = None) -> None:
        track = track or renderer.track or {}
        title = track.get('title', '')
        artist = track.get('artist', '')

        if not title:
            title, artist = self._lookup_track(renderer)

        if not title:
            raise RendererCommandError('The title of the track is unknown.')

        if not artist:
            self._send(renderer, build_control_text('resume', self.skill_name, locale=self.locale))
            return

        self._send_track(renderer, dict(track, title=title, artist=artist), quiet=False)

    def play_track(self, renderer: MediaRenderer, track: dict = None, quiet: bool = False) -> None:
        """Play a single track of the queue of the renderer

        The track is played with its title and its artist, so that the
        skill plays exactly this track and not the rest of the album.

        The quiet tracks are played without an answer of the skill, so that
        the title and the artist are not read out.  The renderer uses them
        for the tracks that it starts on its own, when the previous track
        has ended.

        :param renderer: The media renderer
        :param dict track: The track to play
        :param bool quiet: True when the skill should not answer
        """

        track = track or renderer.track or {}
        title = track.get('title', '')
        artist = track.get('artist', '')

        if not title:
            raise RendererCommandError('The title of the track is unknown.')

        if not artist:
            raise RendererCommandError('The artist of the track is unknown.')

        self._send_track(renderer, dict(track, title=title, artist=artist), quiet=quiet)

    def resolve_track(self, renderer: MediaRenderer) -> dict:
        """Look the track of the renderer up in the collection

        The track is looked up by the ID of its URI, or by its title and
        its artist.  Not every client sends the metadata of the track, so
        the collection is the only reliable source for the title, the
        artist and the duration of a track.

        :param renderer: The media renderer
        :return: The track of the collection, empty when it was not found
        :rtype: dict
        """

        if not self.subsonic_connection:
            return {}

        identifier = self._identifier_from_uri(renderer)

        if identifier:
            song = self.subsonic_connection.get_song(identifier)

            if song:
                return self._track_of(song)

        song = self.subsonic_connection.find_song_by_title(
            renderer.track.get('title'), renderer.track.get('artist'))

        if song:
            return self._track_of(song)

        return {}

    def resolve_next_track(self, renderer: MediaRenderer, uri: str, track: dict) -> dict:
        return self.resolve_track(SimpleNamespace(current_uri=uri, track=track))

    def resolve_queue(self, renderer: MediaRenderer, resolved=None) -> list:
        """Build the queue of the renderer from the collection

        The queue of a DLNA client is not known to the renderer, only the
        track that the client wants to play is.  The queue is therefore
        taken from the collection of the media server: the album of the
        track, or the play list when the client sent the URI of a play
        list.

        :param renderer: The media renderer
        :return: A list of the tracks of the queue
        :rtype: list
        """

        if not self.subsonic_connection:
            return []

        if resolved:
            return self._album_queue(resolved)

        identifier = self._identifier_from_uri(renderer)

        if identifier:
            song = self.subsonic_connection.get_song(identifier)

            if song:
                return self._album_queue(self._track_of(song))

            entries = self.subsonic_connection.get_playlist_songs(identifier)

            if entries:
                return [self._track_of(entry) for entry in entries]

        track = self.resolve_track(renderer)

        if not track:
            return []

        return self._album_queue(track)

    def report_now_playing(self, renderer: MediaRenderer, track: dict = None, client: str = None) -> None:
        """Report the track that the renderer plays to Navidrome

        The track is reported under the name of the client that asked for
        it, so that the now playing list of Navidrome shows the client
        that plays the track and not the skill.  The renderer calls this
        once for every client that has cast to it, so that every client
        casting to the same device sees the now playing entry.

        :param renderer: The media renderer
        :param dict track: The track that plays
        :param str client: The name of the client to report under, or None
                           to use the renderer's own client name
        """

        track = track or renderer.track or {}
        song_id = track.get('id')

        if not song_id or not self.subsonic_connection:
            return

        player = client or renderer.client_name or 'DLNA client'

        self.subsonic_connection.now_playing(song_id, player=player)

    def _identifier_from_uri(self, renderer: MediaRenderer) -> str:
        """Get the ID of the track or of the play list from the current URI."""

        uri = renderer.current_uri or renderer.track.get('uri', '')

        if not uri:
            return ''

        query = parse_qs(urlparse(uri).query)

        for name in ('id', 'playlistId', 'p'):
            values = query.get(name) or []

            if values:
                return values[0]

        return ''

    def _album_queue(self, song: dict) -> list:
        """Build the queue of a track from its album."""

        album_id = song.get('albumId') or song.get('parent')
        tracks = self.subsonic_connection.get_album_songs(album_id) if album_id else []

        if not tracks:
            return [self._track_of(song)]

        return [self._track_of(track) for track in tracks]

    def _track_of(self, entry: dict) -> dict:
        """Bring a track of the collection into the shape of the renderer."""

        entry = entry or {}
        song_id = entry.get('id') or ''

        art = ''

        if entry.get('coverArt'):
            try:
                art = self.subsonic_connection.get_cover_art_url(entry['coverArt'])
            except Exception as error:
                logger.debug('Could not build the cover art URL of %s: %s', song_id, error)

        uri = entry.get('uri') or ''

        if not uri and song_id:
            try:
                uri = self.subsonic_connection.get_song_uri(song_id)
            except Exception as error:
                logger.debug('Could not build the stream URL of %s: %s', song_id, error)

        try:
            duration = int(entry.get('duration') or 0)
        except (TypeError, ValueError):
            duration = 0

        return {
            'id': song_id,
            'title': entry.get('title') or '',
            'artist': entry.get('artist') or '',
            'album': entry.get('album') or '',
            'albumId': entry.get('albumId') or entry.get('parent') or '',
            'art': art,
            'duration': duration,
            'uri': uri,
        }

    def pause(self, renderer: MediaRenderer) -> None:
        self._send(renderer, build_control_text('pause', self.skill_name, locale=self.locale))

    def stop(self, renderer: MediaRenderer) -> None:
        self._send(renderer, build_control_text('stop', self.skill_name, locale=self.locale))

    def next(self, renderer: MediaRenderer) -> None:
        self._send(renderer, build_control_text('next', self.skill_name, locale=self.locale))

    def previous(self, renderer: MediaRenderer) -> None:
        self._send(renderer, build_control_text('previous', self.skill_name, locale=self.locale))

    def volume_up(self, renderer: MediaRenderer) -> None:
        self._send(renderer, build_control_text('volume_up', self.skill_name, locale=self.locale))

    def volume_down(self, renderer: MediaRenderer) -> None:
        self._send(renderer, build_control_text('volume_down', self.skill_name, locale=self.locale))

    def set_volume(self, renderer: MediaRenderer, volume: int = 0, adjust: str = 'absolute', use_current: bool = True) -> None:
        """Set the Alexa volume from an UPnP value in the range 0 to 100."""
        if adjust == 'increase':
            self.volume_up(renderer)
        elif adjust == 'decrease':
            self.volume_down(renderer)
        elif self.aioamazon_session and self.aioamazon_session.is_configured:
            try:
                self.aioamazon_session.set_device_volume(renderer.device, max(0, min(100, int(volume))))
            except Exception as error:
                raise RendererCommandError(str(error)) from error
        else:
            raise RendererCommandError('Absolute Alexa volume requires aioamazondevices credentials.')

    def get_volume(self, renderer: MediaRenderer) -> int:
        """Read the Alexa volume, returned on the UPnP 0-to-100 scale."""
        if not self.aioamazon_session or not self.aioamazon_session.is_configured:
            return None
        try:
            return self.aioamazon_session.get_device_volume(renderer.device)
        except Exception as error:
            raise RendererCommandError(str(error)) from error

    def _lookup_track(self, renderer: MediaRenderer) -> tuple:
        """Look the track of the current URI up in the Navidrome collection."""

        uri = renderer.current_uri or renderer.track.get('uri', '')
        if not uri or not self.subsonic_connection:
            return '', ''

        query = parse_qs(urlparse(uri).query)
        song_ids = query.get('id') or []
        if not song_ids:
            return '', ''

        try:
            details = self.subsonic_connection.get_song_details(song_ids[0])
        except Exception as error:
            logger.warning('Could not look the track %s up in Navidrome: %s', song_ids[0], error)
            return '', ''

        song = details.get('song') if isinstance(details, dict) else None
        if not isinstance(song, dict):
            return '', ''

        return song.get('title', ''), song.get('artist', '')


class RendererHost:
    """Keeps the list of media renderers in sync with the Alexa devices."""

    def __init__(self, env=None) -> None:
        self.env = os.environ if env is None else env

        self.state_file = self.env.get('NAVI_ALEXA_RENDERER_STATE_FILE', DEFAULT_STATE_FILE)
        self.advertise_host = self.env.get('NAVI_ALEXA_RENDERER_ADVERTISE_HOST', '').strip() or detect_advertise_host()
        self.port = int(self.env.get('NAVI_ALEXA_RENDERER_PORT', str(DEFAULT_PORT)))
        self.refresh_seconds = int(self.env.get('NAVI_ALEXA_RENDERER_REFRESH_SECONDS', str(DEFAULT_REFRESH_SECONDS)))
        self.min_refresh_seconds = int(self.env.get('NAVI_ALEXA_RENDERER_MIN_REFRESH_SECONDS', str(DEFAULT_MIN_REFRESH_SECONDS)))
        self.name_prefix = (self.env.get('NAVI_ALEXA_RENDERER_NAME_PREFIX') or '').strip()
        self.skill_name = self.env.get('NAVI_ALEXA_SKILL_NAME', 'castnavidrome')
        self.locale = normalize_locale(self.env.get('NAVI_ALEXA_LOCALE', DEFAULT_ALEXA_LOCALE))
        self.domain = self.env.get('NAVI_ALEXA_DOMAIN', 'amazon.com')
        self.announce = (self.env.get('NAVI_ALEXA_RENDERER_ANNOUNCE') or '').strip().lower()

        if self.announce not in ANNOUNCE_MODES:
            if self.announce:
                logger.warning('The announcement mode "%s" is not supported, "%s" is used instead.',
                               self.announce, DEFAULT_ANNOUNCE)
            self.announce = DEFAULT_ANNOUNCE

        configured_cookie_file = self.env.get('NAVI_ALEXA_COOKIE_FILE', '/run/secrets/alexa.cookies')
        self.cookie_file = str(resolve_cookie_file(configured_cookie_file))
        self.aioamazon_session = AioAmazonSession(
            domain=self.domain,
            cookie_file=self.cookie_file,
            login_data_file=self.env.get(
                'NAVI_ALEXA_AIODATA_FILE',
                '/var/lib/castnavidrome/aioamazondevices/login.json',
            ),
        )
        self.amazon_session = AmazonSession(domain=self.domain, session_file=self.cookie_file)
        self.auto_restart = self.env.get('NAVI_ALEXA_RENDERER_AUTO_RESTART', 'true').strip().lower() in ('1', 'true', 'yes', 'on')
        self._cookie_file_mtime = self._cookie_file_mtime()
        self._cookie_file_mtime_lock = threading.Lock()
        self.device_filter = DeviceFilter.from_env(self.env)
        self.registry = RendererRegistry(self.state_file)
        self.server = RendererServer(port=self.port, advertise_host=self.advertise_host)
        self.ssdp = SsdpServer(advertise_host=self.advertise_host, http_port=self.port,
                               mx=float(self.env.get('NAVI_ALEXA_RENDERER_SSDP_MX', str(DEFAULT_SSDP_MX))),
                               search_response_count=int(self.env.get('NAVI_ALEXA_RENDERER_SSDP_SEARCH_COUNT', str(DEFAULT_SSDP_SEARCH_COUNT))),
                               search_response_delay=float(self.env.get('NAVI_ALEXA_RENDERER_SSDP_SEARCH_DELAY', str(DEFAULT_SSDP_SEARCH_DELAY))))
        self.controller = AlexaRendererController(
            cookie_file=self.cookie_file,
            domain=self.domain,
            skill_name=self.skill_name,
            locale=self.locale,
            subsonic_connection=self._build_subsonic_connection(),
            announce=self.announce,
            aioamazon_session=self.aioamazon_session,
        )
        self.controller.bridge = RendererBridge(self.env.get('NAVI_RENDERER_BRIDGE_PATH'))
        self.bridge_server = RendererBridgeServer(self.controller.bridge, self._handle_voice_queue)

        self._last_refresh = 0.0
        self._refresh_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._cookie_watch_thread = None

        # Disable continuous device list updates - only update once at container start.
        # Can be re-enabled with NAVI_ALEXA_RENDERER_DISABLE_REFRESH=false.
        self.disable_refresh = (self.env.get('NAVI_ALEXA_RENDERER_DISABLE_REFRESH',
                                              DEFAULT_DISABLE_REFRESH).strip().lower()
                                != 'false')

        # Disable SSDP byebye announcements (e.g., on stop or when removing renderers).
        # Can be enabled with NAVI_ALEXA_RENDERER_DISABLE_BYEBYE=false.
        self.disable_byebye = (self.env.get('NAVI_ALEXA_RENDERER_DISABLE_BYEBYE',
                                            'false').strip().lower()
                               in ('1', 'true', 'yes', 'on'))
        if self.disable_byebye:
            logger.info('SSDP ssdp:byebye announcements are disabled via NAVI_ALEXA_RENDERER_DISABLE_BYEBYE.')

        self.announce_interval = int(self.env.get('NAVI_ALEXA_RENDERER_ANNOUNCE_INTERVAL', '720'))
        self._announce_stop = threading.Event()
        self.disable_announce = (self.env.get('NAVI_ALEXA_RENDERER_DISABLE_ANNOUNCE',
                                              'false').strip().lower()
                                in ('1', 'true', 'yes', 'on')) or self.announce_interval <= 0
        if self.disable_announce:
            logger.info('Periodic SSDP announcements are disabled via NAVI_ALEXA_RENDERER_DISABLE_ANNOUNCE or NAVI_ALEXA_RENDERER_ANNOUNCE_INTERVAL <= 0.')

        # The number of seconds of client inactivity after which the
        # renderer stops playback instead of advancing to the next track.
        # A value of 0 disables the check, so that the queue runs until the
        # client stops it explicitly.
        self.client_timeout = float(self.env.get('NAVI_ALEXA_RENDERER_CLIENT_TIMEOUT',
                                                 str(DEFAULT_CLIENT_TIMEOUT)))
        try:
            self.default_volume = int(self.env.get('NAVI_ALEXA_RENDERER_DEFAULT_VOLUME', '1'))
        except (TypeError, ValueError):
            raise ValueError('NAVI_ALEXA_RENDERER_DEFAULT_VOLUME must be an integer from 0 to 10.') from None
        if not 0 <= self.default_volume <= 10:
            raise ValueError('NAVI_ALEXA_RENDERER_DEFAULT_VOLUME must be from 0 to 10.')

    #
    # Setup
    #

    def _build_subsonic_connection(self):
        server_url = self.env.get('NAVI_URL', '')
        user = self.env.get('NAVI_USER', '')
        password = self.env.get('NAVI_PASS', '')

        if not (server_url and user and password):
            return None

        try:
            from castnavidrome.subsonic_api import SubsonicConnection
        except ImportError:
            logger.warning('The Navidrome client library is not available, track lookups are disabled.')
            return None

        try:
            return SubsonicConnection(
                server_url,
                user,
                password,
                self.env.get('NAVI_PORT', '443'),
                self.env.get('NAVI_API_PATH', '/rest'),
                self.env.get('NAVI_API_VER', '1.16.1'),
                timeout=int(self.env.get('NAVI_API_TIMEOUT', '10')),
            )
        except Exception as error:
            logger.warning('Could not connect to the Navidrome server: %s', error)
            return None

    def friendly_name(self, device: dict) -> str:
        name = (device.get('name') or '').strip() or 'Alexa'
        if self.name_prefix:
            return f'{self.name_prefix}: {name}'
        return name

    #
    # Lifecycle
    #

    def start(self) -> None:
        logger.info('Starting the castNavidrome renderer host on %s:%s.', self.advertise_host, self.port)

        self.registry.load()
        self.server.start()
        self.ssdp.on_search = self._on_discovery_request

        # Zuerst die Renderer-Liste füllen, bevor SSDP lauscht.  So gibt es
        # keine Phase, in der SSDP bereits antwortet, die Renderer-Liste aber
        # noch leer ist (Clients würden sonst leere M-SEARCH-Antworten erhalten).
        self.refresh()
        self._apply_default_volume()

        try:
            self.bridge_server.start()
        except OSError as error:
            logger.warning('Could not start the renderer voice-control bridge: %s', error)

        self.ssdp.start()

        # Announce the renderers several times so that clients that start
        # listening at slightly different times still receive them.  The
        # SSDP server repeats every notification internally, so a single
        # call is enough to survive a lost UDP multicast packet.
        self.ssdp.announce()

        if not getattr(self, 'disable_announce', False):
            announce_thread = threading.Thread(target=self._announce_loop, name='renderer-announce', daemon=True)
            announce_thread.start()

        if self.auto_restart:
            self._cookie_watch_thread = threading.Thread(
                target=self._cookie_watch_loop,
                name='renderer-cookie-watch',
                daemon=True,
            )
            self._cookie_watch_thread.start()

        if self.aioamazon_session.is_configured:
            threading.Thread(target=self._watch_echo_states, name='renderer-echo-state', daemon=True).start()

    def stop(self) -> None:
        logger.info('Stopping the castNavidrome renderer host.')
        self._stop_event.set()
        self._announce_stop.set()
        self.bridge_server.stop()
        if not getattr(self, 'disable_byebye', False):
            self.ssdp.announce_byebye()
        self.ssdp.stop()
        self.server.stop()
        self.aioamazon_session.close()

    def wait(self) -> None:
        self._stop_event.wait()

    def is_healthy(self) -> bool:
        """Return True when the renderer host and its SSDP sockets are alive."""
        return self.ssdp.is_healthy() and self.server.is_healthy()

    def _announce_loop(self) -> None:
        """Periodically re-announce the renderers via SSDP."""

        if getattr(self, 'disable_announce', False):
            return

        while not self._announce_stop.wait(self.announce_interval):
            if getattr(self, 'disable_announce', False):
                break
            self.ssdp.announce()

    def _cookie_watch_loop(self) -> None:
        while not self._stop_event.wait(1):
            self._maybe_restart_on_cookie_change()

    def _handle_voice_queue(self, request: dict) -> dict:
        renderer_id = request.get('renderer')
        current_id = request.get('current')
        if not isinstance(renderer_id, str) or not isinstance(current_id, str):
            return {}
        renderer = self.server.get_renderer(renderer_id)
        if renderer is None:
            return {}
        if request.get('action') == 'peek':
            track = renderer.peek_voice_next(current_id)
            return {'id': track['id']} if track else {}
        if request.get('action') == 'state':
            offset = request.get('offset')
            position = offset / 1000 if isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0 else None
            state = request.get('state')
            if state == 'PLAYING':
                return {'ok': renderer.echo_playback_resumed(current_id, position)}
            grace = ECHO_STOP_GRACE_SECONDS if request.get('grace') is True else 0
            return {'ok': renderer.echo_playback_ended(current_id, state, position, grace=grace)}
        next_id = request.get('next')
        if request.get('action') == 'commit' and isinstance(next_id, str):
            return {'ok': renderer.commit_voice_next(current_id, next_id)}
        return {}

    def _apply_default_volume(self) -> None:
        upnp_volume = self.default_volume * 10
        for renderer in self.server.renderers():
            renderer.volume = upnp_volume
            if not self.aioamazon_session.is_configured:
                logger.warning('Cannot set the default volume for %s without aioamazondevices credentials.',
                               renderer.friendly_name)
                continue
            try:
                self.controller.set_volume(renderer, volume=upnp_volume)
                logger.info('Set the default Alexa volume to %s/10 for %s.',
                            self.default_volume, renderer.friendly_name)
            except RendererCommandError as error:
                logger.warning('Could not set the default Alexa volume for %s: %s',
                               renderer.friendly_name, error)

    def _watch_echo_states(self) -> None:
        while not self._stop_event.is_set():
            try:
                asyncio.run(self._poll_echo_states())
            except Exception as error:
                logger.warning('Could not update Echo playback states: %s', error)
            if self._stop_event.wait(5):
                return

    async def _poll_echo_states(self) -> None:
        async with self.aioamazon_session._connected_api() as (api, devices):
            while not self._stop_event.is_set():
                renderers = self.server.renderers()
                snapshots = [(renderer, renderer.started_at, renderer.track.get('id')) for renderer in renderers
                             if renderer.transport_state in ('PLAYING', 'PAUSED_PLAYBACK')]
                if snapshots:
                    await api._media_handler.sync_media_state(devices)
                    states = await api._media_handler.media_states
                    for renderer, started_at, track_id in snapshots:
                        if renderer.track.get('id') != track_id:
                            continue
                        state = states.get(renderer.device.get('serialNumber'))
                        if state is not None:
                            title = state.now_playing_title
                            if title and title.casefold() != renderer.track.get('title', '').casefold():
                                continue
                            renderer.sync_echo_state(state.player_state, state.media_position,
                                                     state.media_length, started_at,
                                                     title_matches=bool(title))
                await asyncio.sleep(5)

    def _refresh_loop(self) -> None:
        if not self.disable_refresh:
            while not self._stop_event.wait(self.refresh_seconds):
                self.refresh()

    def _on_discovery_request(self) -> None:
        """Refresh the device list when a client searches for renderers."""

        if self.disable_refresh:
            return

        with self._refresh_lock:
            now = time.monotonic()
            if now - self._last_refresh < self.min_refresh_seconds:
                return

            # the timestamp is set before the devices are fetched, otherwise
            # parallel search requests would all trigger a refresh
            self._last_refresh = now

        threading.Thread(target=self.refresh, name='renderer-refresh-now', daemon=True).start()

    #
    # Device discovery
    #

    def _cookie_file_mtime(self) -> float:
        """Return the modification time of the cookie file, or 0 if missing."""
        try:
            return os.path.getmtime(self.cookie_file)
        except OSError:
            return 0.0

    def _maybe_restart_on_cookie_change(self) -> None:
        """Restart the renderer process when the cookie file has changed.

        The castnavidrome container writes new Alexa session cookies to
        NAVI_ALEXA_COOKIE_FILE after a successful proxy login.  When the file
        modification time changes, this renderer reloads itself so the new
        cookies are picked up immediately without a manual container restart.
        """
        try:
            mtime = os.path.getmtime(self.cookie_file)
        except OSError:
            return
        with self._cookie_file_mtime_lock:
            if mtime == self._cookie_file_mtime:
                return
            if not self.auto_restart:
                self._cookie_file_mtime = mtime
                logger.info('Cookie file %s changed, but auto-restart is disabled.', self.cookie_file)
                return
            self._cookie_file_mtime = mtime
            logger.info('Cookie file %s changed; requesting a container restart.', self.cookie_file)
        os.kill(os.getpid(), signal.SIGTERM)

    def list_devices(self) -> list:
        if self.aioamazon_session.is_configured:
            try:
                return self.aioamazon_session.list_devices()
            except Exception as error:
                logger.warning('Could not fetch Alexa devices via aioamazondevices, falling back to cookies: %s',
                               error)

        try:
            self.amazon_session.ensure_session()
        except Exception as error:
            logger.warning('Could not ensure Amazon session, falling back to cached cookies: %s', error)

        client = AlexaTextCommandClient(self.cookie_file, domain=self.domain)
        return client.list_devices()

    def refresh(self) -> None:
        """Fetch the Alexa devices and update the list of media renderers."""

        self._maybe_restart_on_cookie_change()

        with self._refresh_lock:
            try:
                devices = self.list_devices()
            except (AlexaRemoteError, Exception) as error:
                logger.warning('Could not fetch the Alexa devices, keeping the last known list: %s', error)
                self._hydrate_renderers_from_cache()
                return

            self._last_refresh = time.monotonic()

            selected = self.device_filter.filter(devices)
            logger.debug('Found %s Alexa device(s), %s of them are exposed as media renderers.',
                         len(devices), len(selected))

            self.sync_renderers(selected)

    def _hydrate_renderers_from_cache(self) -> None:
        """Rebuild renderers from the persisted registry when device discovery fails."""
        entries = self.registry.entries()
        if not entries:
            return
        if self.server.renderers():
            return
        devices = []
        for entry in entries:
            devices.append({
                'name': entry.get('name') or entry.get('friendlyName') or 'Alexa',
                'deviceType': entry.get('deviceType') or '',
                'deviceFamily': entry.get('deviceFamily') or '',
                'serialNumber': entry.get('serialNumber') or '',
                'deviceOwnerCustomerId': entry.get('deviceOwnerCustomerId') or '',
            })
        selected = self.device_filter.filter(devices) if devices else devices
        if not selected:
            selected = devices
        self.sync_renderers(selected)

    def sync_renderers(self, devices: list) -> None:
        renderers = {}

        for device in devices:
            friendly_name = self.friendly_name(device)
            entry = self.registry.register(device, friendly_name)
            udid = entry['uuid']

            renderer = self.server.get_renderer(udid)
            if renderer is None:
                renderer = MediaRenderer(udid, friendly_name, device, self.controller,
                                         client_timeout=self.client_timeout)
                self.server.add_renderer(renderer)
                logger.info('Added the media renderer "%s" (%s) for the Alexa device %s.',
                            friendly_name, udid, device.get('name'))
            else:
                renderer.friendly_name = friendly_name
                renderer.device = device
                renderer.client_timeout = self.client_timeout

            renderers[udid] = renderer

        for renderer in self.server.renderers():
            if renderer.udid not in renderers:
                if not getattr(self, 'disable_byebye', False):
                    self.ssdp.announce_byebye_for(renderer)
                self.server.remove_renderer(renderer.udid)
                logger.info('Removed the media renderer "%s" (%s).', renderer.friendly_name, renderer.udid)

        self.registry.save()
        self.ssdp.set_renderers(list(renderers.values()))
        if self.ssdp.is_healthy():
            self.ssdp.announce()
            # Zweiter Durchgang, damit Clients, die das M-SEARCH-Antwortfenster
            # bereits verpasst haben oder nur passiv auf ssdp:alive lauschen,
            # die neu gebauten Renderer dennoch entdecken.
            self.ssdp.announce()


def main() -> None:
    log_level = os.getenv('NAVI_ALEXA_RENDERER_LOG_LEVEL', 'INFO').strip().upper()

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    host = RendererHost()
    host.start()

    def shutdown(signum, frame):
        host.stop()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        host.wait()
    finally:
        host.stop()


if __name__ == '__main__':
    main()
