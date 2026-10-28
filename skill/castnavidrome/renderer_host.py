"""Hosts one UPnP media renderer per Alexa device.

The host discovers the Alexa devices of the configured account, filters them
and exposes every remaining device as a UPnP media renderer. The renderers
are announced via SSDP and controlled through the Alexa text command API.
"""

import logging
import os
import signal
import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

from castnavidrome.alexa_device_filter import DeviceFilter
from castnavidrome.alexa_remote import (
    AlexaRemoteError,
    AlexaTextCommandClient,
    build_control_text,
    build_play_track_text,
)
from castnavidrome.amazon_oauth import AmazonOAuthSession
from castnavidrome.localization import normalize_locale
from castnavidrome.renderer_registry import RendererRegistry
from castnavidrome.upnp.renderer import MediaRenderer, RendererCommandError
from castnavidrome.upnp.server import RendererServer
from castnavidrome.upnp.ssdp import SsdpServer

logger = logging.getLogger(__name__)

DEFAULT_PORT = 49443
DEFAULT_REFRESH_SECONDS = 300
DEFAULT_MIN_REFRESH_SECONDS = 10
DEFAULT_STATE_FILE = '/var/lib/castnavidrome/renderer-devices.json'
DEFAULT_DISABLE_REFRESH = 'true'
DEFAULT_SSDP_MX = 2.0
DEFAULT_CLIENT_TIMEOUT = 0.0

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
                 announce: str = DEFAULT_ANNOUNCE, session: AmazonOAuthSession = None) -> None:
        self.cookie_file = cookie_file
        self.domain = domain
        self.skill_name = skill_name
        self.locale = normalize_locale(locale)
        self.subsonic_connection = subsonic_connection
        self.announce = announce if announce in ANNOUNCE_MODES else DEFAULT_ANNOUNCE
        self.session = session

    def _client(self) -> AlexaTextCommandClient:
        return AlexaTextCommandClient(
            self.cookie_file, domain=self.domain, session=self.session,
        )

    def _device(self, renderer: MediaRenderer) -> dict:
        device = renderer.device
        if not device:
            raise RendererCommandError('The Alexa device of this renderer is unknown.')
        if not device.get('online'):
            raise RendererCommandError('The Alexa device is offline.')
        return device

    def _send(self, renderer: MediaRenderer, text: str) -> None:
        device = self._device(renderer)

        try:
            self._client().send_text_command(device, text, locale=self.locale)
        except AlexaRemoteError as error:
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

        self._send(renderer, build_play_track_text(self.skill_name, title, artist,
                                                    locale=self.locale,
                                                    quiet=self._quiet(False)))

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
            self._send(renderer, build_control_text('resume', self.skill_name, locale=self.locale))
            return

        self._send(renderer, build_play_track_text(self.skill_name, title, artist,
                                                    locale=self.locale,
                                                    quiet=self._quiet(quiet)))

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

    def resolve_queue(self, renderer: MediaRenderer) -> list:
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
        """Set the volume by direction only - ignore absolute values."""
        if adjust == 'increase':
            self.volume_up(renderer)
        elif adjust == 'decrease':
            self.volume_down(renderer)
        else:
            # Try to determine direction if called with absolute values
            self.volume_up(renderer)

    def get_volume(self, renderer: MediaRenderer) -> int:
        """Read the current volume of the Alexa device - no longer supported."""
        return None

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
        if self.env.get('NAVI_AMAZON_CLIENT_ID'):
            # Authenticate with OAuth 2.0 (Login with Amazon)
            # Still load cookies from file for Alexa Remote API (which requires cookies)
            self.cookie_file = self.env.get('NAVI_ALEXA_COOKIE_FILE', '/run/secrets/alexa.cookies')
            self.session = AmazonOAuthSession(domain=self.domain)
            self._token_file_mtime = 0.0
            try:
                if self.session.token_file.is_file():
                    self._token_file_mtime = self.session.token_file.stat().st_mtime
            except OSError:
                pass
        else:
            # Fallback: static cookie file
            self.cookie_file = self.env.get('NAVI_ALEXA_COOKIE_FILE', '/run/secrets/alexa.cookies')
            self.session = None
            self._token_file_mtime = 0.0
        self.announce = (self.env.get('NAVI_ALEXA_RENDERER_ANNOUNCE') or '').strip().lower()

        if self.announce not in ANNOUNCE_MODES:
            if self.announce:
                logger.warning('The announcement mode "%s" is not supported, "%s" is used instead.',
                               self.announce, DEFAULT_ANNOUNCE)
            self.announce = DEFAULT_ANNOUNCE

        self.device_filter = DeviceFilter.from_env(self.env)
        self.registry = RendererRegistry(self.state_file)
        self.server = RendererServer(port=self.port, advertise_host=self.advertise_host)
        self.ssdp = SsdpServer(advertise_host=self.advertise_host, http_port=self.port,
                               mx=float(self.env.get('NAVI_ALEXA_RENDERER_SSDP_MX', str(DEFAULT_SSDP_MX))))
        self.controller = AlexaRendererController(
            cookie_file=self.cookie_file,
            domain=self.domain,
            skill_name=self.skill_name,
            locale=self.locale,
            subsonic_connection=self._build_subsonic_connection(),
            announce=self.announce,
            session=self.session,
        )

        self._last_refresh = 0.0
        self._refresh_lock = threading.Lock()
        self._stop_event = threading.Event()

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

        self.announce_interval = int(self.env.get('NAVI_ALEXA_RENDERER_ANNOUNCE_INTERVAL', '60'))
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

        self.ssdp.start()

        # Announce the renderers several times so that clients that start
        # listening at slightly different times still receive them.  The
        # SSDP server repeats every notification internally, so a single
        # call is enough to survive a lost UDP multicast packet.
        self.ssdp.announce()

        if not getattr(self, 'disable_announce', False):
            announce_thread = threading.Thread(target=self._announce_loop, name='renderer-announce', daemon=True)
            announce_thread.start()

    def stop(self) -> None:
        logger.info('Stopping the castNavidrome renderer host.')
        self._stop_event.set()
        self._announce_stop.set()
        if not getattr(self, 'disable_byebye', False):
            self.ssdp.announce_byebye()
        self.ssdp.stop()
        self.server.stop()

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

    def _refresh_loop(self) -> None:
        if not self.disable_refresh:
            while not self._stop_event.wait(self.refresh_seconds):
                self.refresh()

    def _on_discovery_request(self) -> None:
        """Refresh the device list when a client searches for renderers."""

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

    def list_devices(self) -> list:
        client = AlexaTextCommandClient(self.cookie_file, domain=self.domain, session=self.session)
        return client.list_devices()

    def refresh(self) -> None:
        """Fetch the Alexa devices and update the list of media renderers."""

        # Reload OAuth tokens if the token file has changed
        if self.session is not None:
            try:
                if self.session.token_file.is_file():
                    mtime = self.session.token_file.stat().st_mtime
                    if mtime > getattr(self, '_token_file_mtime', 0.0):
                        self._token_file_mtime = mtime
                        self.session._load()
                        logger.info('Reloaded Amazon OAuth tokens from %s.', self.session.token_file)
            except OSError:
                pass

        with self._refresh_lock:
            try:
                devices = self.list_devices()
            except AlexaRemoteError as error:
                logger.warning('Could not fetch the Alexa devices, keeping the last known list: %s', error)
                return
            except Exception as error:
                logger.warning('Could not fetch the Alexa devices, keeping the last known list: %s', error)
                return

            self._last_refresh = time.monotonic()

            selected = self.device_filter.filter(devices)
            logger.debug('Found %s Alexa device(s), %s of them are exposed as media renderers.',
                         len(devices), len(selected))

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
