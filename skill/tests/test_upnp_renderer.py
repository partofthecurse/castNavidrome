import unittest

from castnavidrome.upnp.didl import build_didl_metadata, parse_didl_metadata
from castnavidrome.upnp.renderer import (
    MediaRenderer,
    RendererCommandError,
    client_name_from_user_agent,
    format_duration,
)
from castnavidrome.upnp.soap import build_soap_response, parse_soap_request

DIDL = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
    '<item id="1" parentID="0" restricted="1">'
    '<dc:title>Some Song</dc:title>'
    '<upnp:class>object.item.audioItem.musicTrack</upnp:class>'
    '<upnp:artist>Some Artist</upnp:artist>'
    '<upnp:album>Some Album</upnp:album>'
    '<upnp:albumArtURI>http://navidrome/rest/getCoverArt?id=1</upnp:albumArtURI>'
    '<res duration="0:03:21" protocolInfo="http-get:*:audio/mpeg:*">http://navidrome/rest/stream?id=42</res>'
    '</item>'
    '</DIDL-Lite>'
)

QUEUE = [
    {
        'id': '42',
        'title': 'Some Song',
        'artist': 'Some Artist',
        'album': 'Some Album',
        'art': 'http://navidrome/rest/getCoverArt?id=1',
        'duration': 201,
        'uri': 'http://navidrome/rest/stream?id=42',
    },
    {
        'id': '43',
        'title': 'Another Song',
        'artist': 'Some Artist',
        'album': 'Some Album',
        'art': 'http://navidrome/rest/getCoverArt?id=1',
        'duration': 180,
        'uri': 'http://navidrome/rest/stream?id=43',
    },
]


class FakeController:
    def __init__(self, queue=None):
        self.calls = []
        self.queue = queue if queue is not None else []

    def play(self, renderer, track=None):
        self.calls.append(('play', track))

    def play_track(self, renderer, track=None, quiet=False):
        self.calls.append(('play_track', track, quiet))

    def pause(self, renderer):
        self.calls.append(('pause',))

    def stop(self, renderer):
        self.calls.append(('stop',))

    def next(self, renderer):
        self.calls.append(('next',))

    def previous(self, renderer):
        self.calls.append(('previous',))

    def set_volume(self, renderer, volume=0):
        self.calls.append(('set_volume', volume))

    def resolve_queue(self, renderer):
        return self.queue

    def report_now_playing(self, renderer, track=None, client=None):
        self.calls.append(('report_now_playing', track, client))


class FailingController(FakeController):
    def play(self, renderer, track=None):
        raise RendererCommandError('The Alexa device is offline.')


class DidlMetadataTests(unittest.TestCase):
    def test_the_track_information_is_read_from_the_metadata(self):
        track = parse_didl_metadata(DIDL)

        self.assertEqual(track['title'], 'Some Song')
        self.assertEqual(track['artist'], 'Some Artist')
        self.assertEqual(track['album'], 'Some Album')
        self.assertEqual(track['art'], 'http://navidrome/rest/getCoverArt?id=1')
        self.assertEqual(track['uri'], 'http://navidrome/rest/stream?id=42')
        self.assertEqual(track['duration'], 201)

    def test_broken_metadata_is_ignored(self):
        track = parse_didl_metadata('<not-xml')

        self.assertEqual(track['title'], '')
        self.assertEqual(track['duration'], 0)

    def test_empty_metadata_is_ignored(self):
        track = parse_didl_metadata('')

        self.assertEqual(track['title'], '')


class SoapTests(unittest.TestCase):
    def test_a_soap_request_is_parsed(self):
        body = (
            '<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body><u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
            '<InstanceID>0</InstanceID>'
            '<CurrentURI>http://navidrome/rest/stream?id=42</CurrentURI>'
            '<CurrentURIMetaData></CurrentURIMetaData>'
            '</u:SetAVTransportURI></s:Body></s:Envelope>'
        ).encode('utf-8')

        request = parse_soap_request(body)

        self.assertEqual(request.action, 'SetAVTransportURI')
        self.assertEqual(request.service_type, 'urn:schemas-upnp-org:service:AVTransport:1')
        self.assertEqual(request.argument('CurrentURI'), 'http://navidrome/rest/stream?id=42')
        self.assertEqual(request.argument('InstanceID'), '0')

    def test_a_soap_response_contains_the_returned_values(self):
        response = build_soap_response(
            'urn:schemas-upnp-org:service:RenderingControl:1', 'GetVolume', {'CurrentVolume': '42'})

        self.assertIn(b'<u:GetVolumeResponse', response)
        self.assertIn(b'<CurrentVolume>42</CurrentVolume>', response)


class DurationTests(unittest.TestCase):
    def test_a_duration_is_formatted_as_hours_minutes_seconds(self):
        self.assertEqual(format_duration(0), '0:00:00')
        self.assertEqual(format_duration(59), '0:00:59')
        self.assertEqual(format_duration(225), '0:03:45')
        self.assertEqual(format_duration(3661), '1:01:01')

    def test_the_duration_of_the_media_info_is_the_duration_of_the_track(self):
        controller = FakeController()
        device = {'name': 'Echo Dot', 'online': True}
        renderer = MediaRenderer('1234', 'castNavidrome: Echo Dot', device, controller)

        renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        self.assertEqual(renderer.get_media_info()['MediaDuration'], '0:03:21')
        self.assertEqual(renderer.get_position_info()['TrackDuration'], '0:03:21')


class MediaRendererTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        device = {'name': 'Echo Dot', 'online': True}
        self.renderer = MediaRenderer('uuid:1234', 'castNavidrome: Echo Dot', device, self.controller)

    def test_the_uuid_prefix_is_removed(self):
        self.assertEqual(self.renderer.udid, '1234')

    def test_the_track_is_taken_over_from_the_metadata(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        self.assertEqual(self.renderer.track['title'], 'Some Song')
        self.assertEqual(self.renderer.track['artist'], 'Some Artist')

    def test_play_starts_the_playback_on_the_alexa_device(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)
        self.renderer.play()

        self.assertEqual(self.renderer.transport_state, 'PLAYING')
        self.assertEqual(self.controller.calls[0][0], 'play')
        self.assertEqual(self.controller.calls[0][1]['title'], 'Some Song')

    def test_play_without_a_media_uri_is_rejected(self):
        with self.assertRaises(Exception):
            self.renderer.play()

        self.assertEqual(self.renderer.transport_state, 'NO_MEDIA_PRESENT')

    def test_a_failing_command_stops_the_playback(self):
        device = {'name': 'Echo Dot', 'online': True}
        renderer = MediaRenderer('uuid:1234', 'castNavidrome: Echo Dot', device, FailingController())
        renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        with self.assertRaises(Exception):
            renderer.play()

        self.assertEqual(renderer.transport_state, 'STOPPED')

    def test_pause_and_stop_change_the_transport_state(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)
        self.renderer.play()

        self.renderer.pause()
        self.assertEqual(self.renderer.transport_state, 'PAUSED_PLAYBACK')

        self.renderer.stop()
        self.assertEqual(self.renderer.transport_state, 'STOPPED')

    def test_the_volume_is_limited_to_the_upnp_range(self):
        self.renderer.set_volume('150')
        self.assertEqual(self.renderer.volume, 100)

        self.renderer.set_volume('-10')
        self.assertEqual(self.renderer.volume, 0)

    def test_the_alexa_volume_is_calculated_from_the_upnp_volume(self):
        self.assertEqual(self.renderer.alexa_volume(50), 5)
        self.assertEqual(self.renderer.alexa_volume(100), 10)
        self.assertEqual(self.renderer.alexa_volume(0), 0)

    def test_the_transport_info_reports_the_current_state(self):
        info = self.renderer.get_transport_info()

        self.assertEqual(info['CurrentTransportState'], 'STOPPED')
        self.assertEqual(info['CurrentSpeed'], '1')

    def test_a_track_without_an_id_is_not_advanced(self):
        # A Spotify track has no castnavidrome id, so the renderer must not
        # auto-advance at its end and surface an error to the client.
        self.renderer.set_av_transport_uri('spotify:track:abc', '')
        self.renderer.play()

        self.assertIsNone(self.renderer._advance_timer)
        self.renderer._advance()
        play_track_calls = [call for call in self.controller.calls if call[0] == 'play_track']
        self.assertEqual(play_track_calls, [])


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController(QUEUE)
        device = {'name': 'Echo Dot', 'online': True}
        self.renderer = MediaRenderer('uuid:1234', 'Echo Dot', device, self.controller)

    def test_the_queue_is_built_from_the_collection(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        self.assertEqual(len(self.renderer.queue), 2)
        self.assertEqual(self.renderer.queue_index, 0)
        self.assertEqual(self.renderer.queue[1]['title'], 'Another Song')

    def test_the_next_track_is_taken_from_the_queue(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        self.renderer.next()

        self.assertEqual(self.renderer.track['title'], 'Another Song')
        self.assertEqual(self.renderer.queue_index, 1)
        self.assertEqual(self.controller.calls[0][0], 'play_track')
        self.assertEqual(self.controller.calls[0][1]['title'], 'Another Song')

    def test_a_skipped_track_is_announced(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        self.renderer.next()

        self.assertFalse(self.controller.calls[0][2])

    def test_the_track_that_follows_on_its_own_is_played_quietly(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)
        self.renderer.play()
        self.renderer._cancel_advance()

        self.renderer._advance()

        played = [call for call in self.controller.calls if call[0] == 'play_track']
        self.assertEqual(len(played), 1)
        self.assertEqual(played[0][1]['title'], 'Another Song')
        self.assertTrue(played[0][2])

    def test_the_previous_track_is_taken_from_the_queue(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)
        self.renderer.next()

        self.renderer.previous()

        self.assertEqual(self.renderer.track['title'], 'Some Song')
        self.assertEqual(self.renderer.queue_index, 0)

    def test_the_skill_is_not_skipped_when_the_queue_is_at_its_end(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=43', DIDL)
        self.renderer.queue = [self.renderer.queue[1]]
        self.renderer.queue_index = 0

        self.renderer.next()

        self.assertEqual(self.controller.calls[0][0], 'next')

    def test_the_media_info_reports_the_queue(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        info = self.renderer.get_media_info()

        self.assertEqual(info['NrTracks'], '2')
        self.assertEqual(info['MediaDuration'], '0:06:21')

    def test_the_now_playing_is_reported_for_the_track(self):
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

        self.renderer.play()

        reported = [call for call in self.controller.calls if call[0] == 'report_now_playing']
        self.assertEqual(len(reported), 1)
        self.assertEqual(reported[0][1]['id'], '42')


class EventTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController(QUEUE)
        device = {'name': 'Echo Dot', 'online': True}
        self.renderer = MediaRenderer('uuid:1234', 'Echo Dot', device, self.controller)
        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)

    def test_the_event_carries_the_metadata_of_the_track(self):
        event = self.renderer.build_avtransport_event().decode('utf-8')

        self.assertIn('Some Song', event)
        self.assertIn('CurrentTrackURI', event)
        self.assertIn('CurrentTrackDuration', event)
        self.assertIn('NrTracks', event)
        self.assertIn('RelativeTimePosition', event)

    def test_the_event_carries_the_new_track_after_a_skip(self):
        self.renderer.next()

        event = self.renderer.build_avtransport_event().decode('utf-8')

        self.assertIn('Another Song', event)
        self.assertIn('PLAYING', event)


class ClientTests(unittest.TestCase):
    def test_the_name_of_the_client_is_taken_from_the_user_agent(self):
        self.assertEqual(client_name_from_user_agent('Jellybox/1.4.2 (Android)'), 'Jellybox')
        self.assertEqual(client_name_from_user_agent('Symfonium'), 'Symfonium')
        self.assertEqual(client_name_from_user_agent(''), 'DLNA client')

    def test_the_renderer_remembers_the_client(self):
        device = {'name': 'Echo Dot', 'online': True}
        renderer = MediaRenderer('uuid:1234', 'Echo Dot', device, FakeController())

        renderer.set_client('Jellybox/1.4.2 (Android)')

        self.assertEqual(renderer.client_name, 'Jellybox')

    def test_now_playing_is_reported_to_every_client(self):
        # Every client that casts to the same device gets its own now playing
        # entry, so all of them see what is playing.
        controller = FakeController(QUEUE)
        device = {'name': 'Echo Dot', 'online': True}
        renderer = MediaRenderer('uuid:1234', 'Echo Dot', device, controller)

        renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', DIDL)
        renderer.set_client('Symfonium/1.0 (Android)')
        renderer.set_client('Jellybox/1.4.2 (Android)')
        renderer.play()

        reported = [call for call in controller.calls if call[0] == 'report_now_playing']
        clients = {call[2] for call in reported}

        self.assertEqual(len(reported), 2)
        self.assertEqual(clients, {'Symfonium', 'Jellybox'})
        for call in reported:
            self.assertEqual(call[1]['id'], '42')


class DidlBuilderTests(unittest.TestCase):
    def test_the_built_metadata_can_be_read_again(self):
        metadata = build_didl_metadata(QUEUE[0])

        track = parse_didl_metadata(metadata)

        self.assertEqual(track['title'], 'Some Song')
        self.assertEqual(track['artist'], 'Some Artist')
        self.assertEqual(track['album'], 'Some Album')
        self.assertEqual(track['duration'], 201)
        self.assertEqual(track['uri'], 'http://navidrome/rest/stream?id=42')
