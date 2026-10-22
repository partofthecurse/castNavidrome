"""The UPnP media renderer that represents a single Alexa device."""

import logging
import threading
import time
import xml.sax.saxutils as saxutils

from .constants import (
    ALEXA_VOLUME_MAX,
    ALEXA_VOLUME_MIN,
    AVTRANSPORT_EVENT_TYPE,
    UPNP_VOLUME_MAX,
)
from .didl import build_didl_metadata, parse_didl_metadata
from .soap import SoapError

logger = logging.getLogger(__name__)

TRANSPORT_STOPPED = 'STOPPED'
TRANSPORT_PLAYING = 'PLAYING'
TRANSPORT_PAUSED = 'PAUSED_PLAYBACK'
TRANSPORT_TRANSITIONING = 'TRANSITIONING'
TRANSPORT_NO_MEDIA = 'NO_MEDIA_PRESENT'

TRANSPORT_ACTIONS = 'Play,Pause,Stop,Seek,X_DLNA_SeekTime'

UNKNOWN_CLIENT = 'DLNA client'

TRACK_KEYS = ('id', 'title', 'artist', 'album', 'albumId', 'art', 'duration', 'uri')


def format_duration(seconds: int) -> str:
    """Format a number of seconds as the UPnP duration "H:MM:SS".

    :param int seconds: The number of seconds
    :return: The formatted duration
    :rtype: str
    """

    seconds = max(0, int(seconds or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    return f'{hours}:{minutes:02d}:{secs:02d}'


def normalise_track(track: dict) -> dict:
    """Bring a track into the shape that the renderer uses

    :param dict track: The track
    :return: The track with all the known keys
    :rtype: dict
    """

    track = track or {}

    try:
        duration = int(track.get('duration') or 0)
    except (TypeError, ValueError):
        duration = 0

    return {
        'id': str(track.get('id') or ''),
        'title': str(track.get('title') or ''),
        'artist': str(track.get('artist') or ''),
        'album': str(track.get('album') or ''),
        'albumId': str(track.get('albumId') or ''),
        'art': str(track.get('art') or ''),
        'duration': duration,
        'uri': str(track.get('uri') or ''),
    }


def client_name_from_user_agent(user_agent: str) -> str:
    """Build the name of a DLNA client from its user agent

    The name of the client is used for the now playing entry of
    Navidrome, so that the track that a media renderer plays is attributed
    to the client that asked for it.

    :param str user_agent: The user agent of the request
    :return: The name of the client
    :rtype: str
    """

    if not user_agent:
        return UNKNOWN_CLIENT

    name = user_agent.split('/')[0].split(' ')[0].strip()

    return name or UNKNOWN_CLIENT


class RendererCommandError(RuntimeError):
    """Raised when a command could not be forwarded to the Alexa device."""


class MediaRenderer:
    """A UPnP media renderer that forwards the playback to an Alexa device.

    The renderer owns the play queue of the DLNA clients.  A DLNA client
    only tells the renderer which track it wants to play, the queue of the
    client is not known to it.  The renderer therefore builds the queue
    from the collection of the media server and plays the single tracks
    of that queue, so that the skip commands of the clients skip in the
    queue of the collection and not in the queue of the skill.
    """

    def __init__(self, udid: str, friendly_name: str, device: dict = None, command_handler=None) -> None:
        self.udid = udid[5:] if udid.startswith('uuid:') else udid
        self.friendly_name = friendly_name
        self.device = device or {}
        self.command_handler = command_handler
        self.event_sink = None

        self.transport_state = TRANSPORT_STOPPED
        self.transport_status = 'OK'
        self.play_mode = 'NORMAL'
        self.current_uri = ''
        self.current_metadata = ''
        self.next_uri = ''
        self.next_metadata = ''
        self.track = normalise_track({})
        self.queue = []
        self.queue_index = -1
        self.client_name = ''
        self.client_names = set()
        self.volume = 50
        self.muted = False
        self.started_at = None
        self._advance_timer = None

    #
    # State helpers
    #

    def _set_transport_state(self, state: str) -> None:
        if self.transport_state == state:
            return

        self.transport_state = state
        self.notify_state_change()

    def notify_state_change(self) -> None:
        """Send the current state to all event subscribers."""

        if not self.event_sink:
            return

        try:
            self.event_sink(self.udid, 'AVTransport', self.build_avtransport_event())
            self.event_sink(self.udid, 'RenderingControl', self.build_renderingcontrol_event())
        except Exception as error:  # pragma: no cover - defensive
            logger.warning('Could not send the UPnP event for %s: %s', self.udid, error)

    def elapsed_seconds(self) -> int:
        """Get the number of seconds that the current track is playing."""

        if not self.started_at or self.transport_state != TRANSPORT_PLAYING:
            return 0

        return int(time.time() - self.started_at)

    def media_duration(self) -> int:
        """Get the duration of the whole queue in seconds."""

        if not self.queue:
            return int(self.track.get('duration') or 0)

        return sum(int(track.get('duration') or 0) for track in self.queue)

    @staticmethod
    def _escape(value: str) -> str:
        return saxutils.escape(str(value or ''), {'"': '&quot;'})

    def build_avtransport_event(self) -> bytes:
        elapsed = self.elapsed_seconds()
        duration = int(self.track.get('duration') or 0)
        metadata = self._escape(self.current_metadata)
        uri = self._escape(self.current_uri)

        event = (
            f'<Event xmlns="{AVTRANSPORT_EVENT_TYPE}" '
            'xmlns:r="urn:schemas-upnp-org:metadata-1-0/rendering/">'
            '<InstanceID val="0">'
            f'<TransportState val="{self.transport_state}"/>'
            f'<TransportStatus val="{self.transport_status}"/>'
            '<TransportPlaySpeed val="1"/>'
            f'<CurrentTransportActions val="{TRANSPORT_ACTIONS}"/>'
            f'<PlayMode val="{self.play_mode}"/>'
            f'<CurrentTrackMetaData val="{metadata}"/>'
            f'<CurrentTrackURI val="{uri}"/>'
            f'<CurrentTrackDuration val="{format_duration(duration)}"/>'
            f'<CurrentTrackNumber val="{max(self.queue_index + 1, 1)}"/>'
            f'<CurrentMediaDuration val="{format_duration(self.media_duration())}"/>'
            f'<NrTracks val="{max(len(self.queue), 1)}"/>'
            f'<RelativeTimePosition val="{format_duration(elapsed)}"/>'
            f'<AbsoluteTimePosition val="{format_duration(elapsed)}"/>'
            f'<AVTransportURI val="{uri}"/>'
            f'<AVTransportURIMetaData val="{metadata}"/>'
            f'<NextAVTransportURI val="{self._escape(self.next_uri)}"/>'
            f'<NextAVTransportURIMetaData val="{self._escape(self.next_metadata)}"/>'
            '<PlaybackStorageMedium val="NETWORK"/>'
            '<RecordStorageMedium val="NOT_IMPLEMENTED"/>'
            '<PossiblePlaybackStorageMedia val="NETWORK,HDD,UNKNOWN"/>'
            '<PossibleRecordStorageMedia val="NOT_IMPLEMENTED"/>'
            '<RecordMedium val="NOT_IMPLEMENTED"/>'
            '<CurrentRecordQualityMode val="NOT_IMPLEMENTED"/>'
            '<PossibleRecordQualityModes val="NOT_IMPLEMENTED"/>'
            '</InstanceID>'
            '</Event>'
        )

        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
            f'<e:property><LastChange>{saxutils.escape(event)}</LastChange></e:property>'
            '</e:propertyset>'
        ).encode('utf-8')

    def build_renderingcontrol_event(self) -> bytes:
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
            f'<e:property><Volume channel="Master" val="{self.volume}"/></e:property>'
            f'<e:property><Mute channel="Master" val="{1 if self.muted else 0}"/></e:property>'
            '</e:propertyset>'
        ).encode('utf-8')

    #
    # The client that drives the renderer
    #

    def set_client(self, user_agent: str) -> None:
        """Remember the client that sent the last command

        The client is reported to the media server as the player of the
        track, so that the now playing list shows the client that asked
        for the track and not the skill that plays it.

        :param str user_agent: The user agent of the request
        """

        name = client_name_from_user_agent(user_agent)

        if not name:
            return

        self.client_names.add(name)

        if name != self.client_name:
            self.client_name = name
            logger.info('The client "%s" drives the renderer %s.', name, self.friendly_name)

    #
    # The queue of the renderer
    #

    def set_av_transport_uri(self, current_uri: str, current_metadata: str = '') -> dict:
        self.current_uri = current_uri or ''
        self.current_metadata = current_metadata or ''
        self.track = normalise_track(parse_didl_metadata(current_metadata))

        if not self.track['uri']:
            self.track['uri'] = self.current_uri

        self._cancel_advance()
        self.queue = []
        self.queue_index = -1
        self._load_queue()

        return {}

    def set_next_av_transport_uri(self, next_uri: str, next_metadata: str = '') -> dict:
        self.next_uri = next_uri or ''
        self.next_metadata = next_metadata or ''
        return {}

    def _load_queue(self) -> None:
        """Build the queue of the renderer from the collection.

        The track that the client wants to play is looked up in the
        collection, so that the renderer knows the title, the artist and
        the duration of the track even when the client does not send them.
        """

        resolved = self._query('resolve_track') or {}
        tracks = self._query('resolve_queue') or []

        self.queue = [normalise_track(track) for track in tracks]

        if not self.queue:
            if not resolved:
                return

            self.queue = [normalise_track(resolved)]

        index = self._index_of_track(resolved)

        if index < 0:
            index = self._index_of_current()

        if index < 0:
            merged = dict(self.track)

            for key, value in resolved.items():
                if value and not merged.get(key):
                    merged[key] = value

            self.queue.insert(0, normalise_track(merged))
            index = 0
        else:
            # the collection knows the ID, the artist and the duration of
            # the track, the URI of the client is kept
            merged = dict(self.queue[index])
            merged['uri'] = self.current_uri or merged.get('uri', '')
            self.track = merged

        self.queue_index = index
        self._update_next_entry()

        logger.info('The renderer %s plays the queue "%s" with %s track(s).',
                    self.friendly_name, self.track.get('album') or self.track.get('title'),
                    len(self.queue))

    def _index_of_track(self, track: dict) -> int:
        """Get the position of a track of the collection in the queue."""

        song_id = str((track or {}).get('id') or '')

        if not song_id:
            return -1

        for index, entry in enumerate(self.queue):
            if entry.get('id') == song_id:
                return index

        return -1

    def _index_of_current(self) -> int:
        """Get the position of the current track in the queue."""

        title = str(self.track.get('title') or '').casefold()
        artist = str(self.track.get('artist') or '').casefold()

        if not title:
            return -1

        for index, entry in enumerate(self.queue):
            if str(entry.get('title') or '').casefold() != title:
                continue

            if artist and str(entry.get('artist') or '').casefold() != artist:
                continue

            return index

        return -1

    def _update_next_entry(self) -> None:
        """Set the next entry of the queue as the next URI of the renderer."""

        if self.queue_index + 1 >= len(self.queue):
            self.next_uri = ''
            self.next_metadata = ''
            return

        entry = self.queue[self.queue_index + 1]
        self.next_uri = entry.get('uri') or ''
        self.next_metadata = build_didl_metadata(entry)

    def _has_next(self) -> bool:
        return 0 <= self.queue_index < len(self.queue) - 1

    def _has_previous(self) -> bool:
        return self.queue_index > 0

    def _play_queue_entry(self, index: int, quiet: bool = False) -> bool:
        """Play a track of the queue of the renderer.

        The quiet tracks are played without an answer of the skill, so that
        the title and the artist are not read out.  The renderer uses them
        for the tracks that it starts on its own, when the previous track
        has ended.

        :param int index: The position of the track in the queue
        :param bool quiet: True when the skill should not answer
        :return: True when the track was played
        :rtype: bool
        """

        if index < 0 or index >= len(self.queue):
            return False

        entry = self.queue[index]

        self.queue_index = index
        self.track = dict(entry)
        self.current_uri = entry.get('uri') or self.current_uri
        self.current_metadata = build_didl_metadata(entry)
        self._update_next_entry()

        self._set_transport_state(TRANSPORT_TRANSITIONING)

        try:
            self._command('play_track', track=entry, quiet=quiet)
        except RendererCommandError as error:
            self.transport_status = 'ERROR_OCCURRED'
            self._set_transport_state(TRANSPORT_STOPPED)
            raise SoapError(str(error), 701) from None

        self.transport_status = 'OK'
        self.started_at = time.time()
        self._set_transport_state(TRANSPORT_PLAYING)
        self._report_now_playing()
        self._schedule_advance()
        self.notify_state_change()

        return True

    #
    # The end of a track
    #

    def _schedule_advance(self) -> None:
        """Play the next track of the queue when the current one ends.

        Only tracks that come from the castnavidrome collection (they carry an
        id) are advanced automatically.  Tracks from other clients such as
        Spotify must not trigger an advance, otherwise the renderer would try
        to play the next castnavidrome track at the end of every foreign track
        and surface an error to the client.
        """

        self._cancel_advance()

        if not self.track.get('id'):
            return

        duration = int(self.track.get('duration') or 0)

        if duration <= 0:
            return

        timer = threading.Timer(duration, self._advance)
        timer.daemon = True
        self._advance_timer = timer
        timer.start()

    def _cancel_advance(self) -> None:
        if self._advance_timer:
            self._advance_timer.cancel()
            self._advance_timer = None

    def _advance(self) -> None:
        """Continue with the next track of the queue.

        The track is played quietly, the user did not ask for it, so the
        skill does not answer with the title and the artist.
        """

        self._advance_timer = None

        # Only castnavidrome tracks are advanced automatically.  A track from
        # another client (e.g. Spotify) has no collection id and must not be
        # advanced here.
        if not self.track.get('id'):
            return

        if self.transport_state != TRANSPORT_PLAYING:
            return

        if not self._has_next():
            logger.info('The queue of the renderer %s has ended.', self.friendly_name)
            self.stop()
            return

        try:
            self._play_queue_entry(self.queue_index + 1, quiet=True)
        except SoapError as error:
            logger.warning('Could not play the next track of the renderer %s: %s',
                           self.friendly_name, error)

    #
    # AVTransport actions
    #

    def play(self, speed: str = '1') -> dict:
        if not self.current_uri and not self.track['title']:
            self._set_transport_state(TRANSPORT_NO_MEDIA)
            raise SoapError('No media has been set for this renderer.', 701)

        self._set_transport_state(TRANSPORT_TRANSITIONING)

        try:
            self._command('play', track=self.track)
        except RendererCommandError as error:
            self.transport_status = 'ERROR_OCCURRED'
            self._set_transport_state(TRANSPORT_STOPPED)
            raise SoapError(str(error), 701) from None

        self.transport_status = 'OK'
        self.started_at = time.time()
        self._set_transport_state(TRANSPORT_PLAYING)
        self._report_now_playing()
        self._schedule_advance()

        return {}

    def pause(self) -> dict:
        if self.transport_state != TRANSPORT_PLAYING:
            return {}

        try:
            self._command('pause')
        except RendererCommandError as error:
            raise SoapError(str(error), 701) from None

        self._cancel_advance()
        self._set_transport_state(TRANSPORT_PAUSED)

        return {}

    def stop(self) -> dict:
        try:
            self._command('stop')
        except RendererCommandError as error:
            raise SoapError(str(error), 701) from None

        self._cancel_advance()
        self.started_at = None
        self._set_transport_state(TRANSPORT_STOPPED)

        return {}

    def next(self) -> dict:
        if self._has_next():
            self._play_queue_entry(self.queue_index + 1)
            return {}

        try:
            self._command('next')
        except RendererCommandError as error:
            raise SoapError(str(error), 701) from None

        return {}

    def previous(self) -> dict:
        if self._has_previous():
            self._play_queue_entry(self.queue_index - 1)
            return {}

        try:
            self._command('previous')
        except RendererCommandError as error:
            raise SoapError(str(error), 701) from None

        return {}

    def seek(self, unit: str = '', target: str = '') -> dict:
        logger.info('Seek is not supported by the Alexa renderer %s.', self.friendly_name)
        return {}

    def set_play_mode(self, new_play_mode: str = 'NORMAL') -> dict:
        self.play_mode = new_play_mode or 'NORMAL'
        return {}

    def get_transport_info(self) -> dict:
        return {
            'CurrentTransportState': self.transport_state,
            'CurrentTransportStatus': self.transport_status,
            'CurrentSpeed': '1',
        }

    def get_position_info(self) -> dict:
        duration = int(self.track.get('duration') or 0)
        elapsed = self.elapsed_seconds()

        return {
            'Track': str(max(self.queue_index + 1, 1)),
            'TrackDuration': format_duration(duration),
            'TrackMetaData': self.current_metadata,
            'TrackURI': self.current_uri,
            'RelTime': format_duration(min(elapsed, duration) if duration else elapsed),
            'AbsTime': format_duration(elapsed),
            'RelCount': str(elapsed),
            'AbsCount': str(elapsed),
        }

    def get_media_info(self) -> dict:
        return {
            'NrTracks': str(max(len(self.queue), 1)),
            'MediaDuration': format_duration(self.media_duration()),
            'CurrentURI': self.current_uri,
            'CurrentURIMetaData': self.current_metadata,
            'NextURI': self.next_uri,
            'NextURIMetaData': self.next_metadata,
            'PlayMedium': 'NETWORK',
            'RecordMedium': 'NOT_IMPLEMENTED',
            'WriteMedium': 'NOT_IMPLEMENTED',
        }

    def get_device_capabilities(self) -> dict:
        return {
            'PlayMedia': 'network,http',
            'RecMedia': 'NOT_IMPLEMENTED',
            'RecQualityModes': 'NOT_IMPLEMENTED',
        }

    def get_current_transport_actions(self) -> dict:
        return {'Actions': TRANSPORT_ACTIONS}

    def get_transport_settings(self) -> dict:
        return {'PlayMode': self.play_mode, 'RecQualityMode': 'NOT_IMPLEMENTED'}

    #
    # RenderingControl actions
    #

    def get_volume(self, channel: str = 'Master') -> dict:
        return {'CurrentVolume': str(self.volume)}

    def set_volume(self, desired_volume: str, channel: str = 'Master') -> dict:
        try:
            value = int(float(desired_volume))
        except (TypeError, ValueError):
            raise SoapError('The requested volume is not a number.', 402) from None

        value = max(0, min(UPNP_VOLUME_MAX, value))
        self.volume = value

        try:
            self._command('set_volume', volume=value)
        except RendererCommandError as error:
            raise SoapError(str(error), 701) from None

        self.notify_state_change()

        return {}

    def get_mute(self, channel: str = 'Master') -> dict:
        return {'CurrentMute': '1' if self.muted else '0'}

    def set_mute(self, desired_mute: str, channel: str = 'Master') -> dict:
        self.muted = str(desired_mute).strip() not in ('0', 'false', 'False', '')

        if not self.muted:
            try:
                self._command('set_volume', volume=self.volume)
            except RendererCommandError as error:
                raise SoapError(str(error), 701) from None

        self.notify_state_change()

        return {}

    def get_volume_db(self, channel: str = 'Master') -> dict:
        return {'CurrentVolume': str(self.volume)}

    def set_volume_db(self, desired_volume: str, channel: str = 'Master') -> dict:
        return self.set_volume(desired_volume, channel)

    def get_volume_range(self, channel: str = 'Master') -> dict:
        return {'MinValue': '0', 'MaxValue': str(UPNP_VOLUME_MAX)}

    def alexa_volume(self, volume: int = None) -> int:
        """Convert the UPnP volume into the Alexa volume range of 0 to 10."""

        if volume is None:
            volume = self.volume

        scaled = round(volume * ALEXA_VOLUME_MAX / UPNP_VOLUME_MAX)
        return max(ALEXA_VOLUME_MIN, min(ALEXA_VOLUME_MAX, scaled))

    #
    # ConnectionManager actions
    #

    def get_protocol_info(self) -> dict:
        return {
            'SourceProtocolInfo': 'http-get:*:audio/mpeg:*',
            'SinkProtocolInfo': 'http-get:*:audio/mpeg:*',
        }

    def get_current_connection_ids(self) -> dict:
        return {'ConnectionIDs': '0'}

    def get_current_connection_info(self, connection_id: str = '0') -> dict:
        return {
            'RcsID': '0',
            'AVTransportID': '0',
            'ProtocolInfo': 'http-get:*:audio/mpeg:*',
            'PeerConnectionManager': '',
            'PeerConnectionID': '-1',
            'Direction': 'Input',
            'Status': 'OK',
        }

    def prepare_for_connection(self, remote_protocol_info: str = '',
                               peer_connection_manager: str = '',
                               peer_connection_id: str = '-1',
                               direction: str = 'Input') -> dict:
        return {'ConnectionID': '0', 'AVTransportID': '0', 'Result': ''}

    def connection_complete(self, connection_id: str = '0') -> dict:
        return {'Result': ''}

    #
    # Command forwarding
    #

    def _report_now_playing(self) -> None:
        """Tell the media server which track is playing and which client wants it.

        The track is reported once for every client that has cast to this
        renderer, so that every client casting to the same Alexa device sees
        the now playing entry under its own name.
        """

        if not self.track.get('id'):
            return

        clients = self.client_names or {self.client_name or UNKNOWN_CLIENT}

        for client in clients:
            self._query('report_now_playing', track=self.track, client=client)

    def _command(self, name: str, **kwargs) -> None:
        if not self.command_handler:
            raise RendererCommandError('No command handler is configured for this renderer.')

        handler = getattr(self.command_handler, name, None)
        if handler is None:
            raise RendererCommandError(f'The command {name} is not supported.')

        try:
            handler(self, **kwargs)
        except RendererCommandError:
            raise
        except Exception as error:
            raise RendererCommandError(str(error)) from error

    def _query(self, name: str, **kwargs):
        """Call a command of the controller and return its result

        A failing query is not an error for the renderer, it only means
        that the information is not available.

        :param str name: The name of the command
        :param kwargs: The arguments of the command
        :return: The result of the command or None
        """

        if not self.command_handler:
            return None

        handler = getattr(self.command_handler, name, None)
        if handler is None:
            return None

        try:
            return handler(self, **kwargs)
        except Exception as error:
            logger.warning('The query %s of the renderer %s failed: %s', name, self.friendly_name, error)
            return None
