import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

from castnavidrome.alexa_remote import AlexaRemoteError
from castnavidrome.renderer_host import AlexaRendererController, RendererHost
from castnavidrome.upnp.renderer import MediaRenderer, RendererCommandError


def make_device(name='Echo Dot', serial='serial-1', device_type='ECHO', customer='customer-1'):
    return {
        'name': name,
        'deviceOwnerCustomerId': customer,
        'deviceType': device_type,
        'serialNumber': serial,
        'online': True,
    }


class FakeSubsonic:
    """A stand in for the connection to Navidrome."""

    def __init__(self, song=None, album=None, playlist=None):
        self.song = song
        self.album = album
        self.playlist = playlist
        self.reported = []

    def get_song(self, song_id):
        return self.song

    def get_album_songs(self, album_id):
        return self.album or []

    def get_playlist_songs(self, playlist_id):
        return self.playlist or []

    def find_song_by_title(self, title, artist=''):
        return self.song

    def get_cover_art_url(self, cover_id):
        return f'http://navidrome/rest/getCoverArt?id={cover_id}'

    def get_song_uri(self, song_id):
        return f'http://navidrome/rest/stream?id={song_id}'

    def now_playing(self, track_id, device_id='', player=''):
        self.reported.append((track_id, player))


class RendererHostTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.env = {
            'NAVI_ALEXA_RENDERER_STATE_FILE': str(Path(self.temp_dir.name) / 'renderers.json'),
            'NAVI_ALEXA_RENDERER_PORT': '0',
            'NAVI_ALEXA_RENDERER_ADVERTISE_HOST': '127.0.0.1',
            'NAVI_ALEXA_RENDERER_REFRESH_SECONDS': '300',
            'NAVI_ALEXA_SKILL_NAME': 'castnavidrome',
            'NAVI_ALEXA_LOCALE': 'de-DE',
            'NAVI_ALEXA_DOMAIN': 'amazon.com',
        }

        self.host = RendererHost(env=self.env)
        self.host.server.start()
        self.addCleanup(self.host.server.stop)

    def test_every_selected_device_gets_its_own_renderer(self):
        devices = [make_device('Echo Dot', 'serial-1'), make_device('Echo Kitchen', 'serial-2')]

        self.host.sync_renderers(devices)

        renderers = self.host.server.renderers()

        self.assertEqual(len(renderers), 2)
        self.assertEqual({renderer.friendly_name for renderer in renderers},
                         {'Echo Dot', 'Echo Kitchen'})
        self.assertNotEqual(renderers[0].udid, renderers[1].udid)

    def test_the_name_prefix_is_added_when_it_is_configured(self):
        self.env['NAVI_ALEXA_RENDERER_NAME_PREFIX'] = 'castNavidrome'
        host = RendererHost(env=self.env)

        self.assertEqual(host.friendly_name(make_device('Echo Dot', 'serial-1')),
                         'castNavidrome: Echo Dot')

    def test_the_name_prefix_is_optional(self):
        self.env['NAVI_ALEXA_RENDERER_NAME_PREFIX'] = ''
        host = RendererHost(env=self.env)

        self.assertEqual(host.friendly_name(make_device('Echo Dot', 'serial-1')), 'Echo Dot')

    def test_a_device_that_is_gone_removes_its_renderer(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        self.host.sync_renderers([])

        self.assertEqual(self.host.server.renderers(), [])

    def test_the_uuid_of_a_device_stays_the_same_after_a_refresh(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        udid = self.host.server.renderers()[0].udid

        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])

        self.assertEqual(self.host.server.renderers()[0].udid, udid)

    def test_the_registry_is_written_during_the_sync(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])

        self.assertTrue(Path(self.env['NAVI_ALEXA_RENDERER_STATE_FILE']).is_file())

    def test_a_failing_api_keeps_the_last_known_devices(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        self.host.list_devices = lambda: (_ for _ in ()).throw(AlexaRemoteError('Alexa is not reachable.'))

        self.host.refresh()

        self.assertEqual(len(self.host.server.renderers()), 1)

    def test_parallel_discovery_requests_only_refresh_once(self):
        calls = []

        def list_devices():
            calls.append(1)
            time.sleep(0.1)
            return [make_device('Echo Dot', 'serial-1')]

        self.host.list_devices = list_devices

        threads = [threading.Thread(target=self.host._on_discovery_request) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        deadline = time.monotonic() + 5
        while not calls and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.5)

        self.assertEqual(len(calls), 1)

    def test_the_device_description_is_served(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        udid = self.host.server.renderers()[0].udid

        url = f'http://127.0.0.1:{self.host.server.port}/description/{udid}.xml'
        with urllib.request.urlopen(url) as response:
            description = response.read().decode('utf-8')

        self.assertIn('<deviceType>urn:schemas-upnp-org:device:MediaRenderer:1</deviceType>', description)
        self.assertIn('<friendlyName>Echo Dot</friendlyName>', description)
        self.assertIn(f'<UDN>uuid:{udid}</UDN>', description)

    def test_the_announcement_mode_is_read_from_the_environment(self):
        self.env['NAVI_ALEXA_RENDERER_ANNOUNCE'] = 'always'

        host = RendererHost(env=self.env)

        self.assertEqual(host.controller.announce, 'always')

    def test_an_unknown_announcement_mode_falls_back_to_the_default(self):
        self.env['NAVI_ALEXA_RENDERER_ANNOUNCE'] = 'sometimes'

        host = RendererHost(env=self.env)

        self.assertEqual(host.controller.announce, 'explicit')

    def test_the_disable_refresh_setting_is_respected(self):
        self.env['NAVI_ALEXA_RENDERER_DISABLE_REFRESH'] = 'true'

        host = RendererHost(env=self.env)

        self.assertTrue(host.disable_refresh)

        self.env['NAVI_ALEXA_RENDERER_DISABLE_REFRESH'] = 'false'

        host = RendererHost(env=self.env)

        self.assertFalse(host.disable_refresh)


class FakeAlexaClient:
    """A stand in for the client that sends the commands to the Alexa device."""

    def __init__(self):
        self.sent = []

    def send_text_command(self, device, text, locale='en-US'):
        self.sent.append(text)


def make_controller(announce='explicit'):
    controller = AlexaRendererController(
        cookie_file='/does/not/exist',
        skill_name='zero mukke',
        locale='de-DE',
        announce=announce,
    )
    client = FakeAlexaClient()
    controller._client = lambda: client
    renderer = MediaRenderer('uuid:1234', 'Echo Dot', make_device(), controller)

    return controller, client, renderer


class ControllerAnnounceTests(unittest.TestCase):
    def test_a_track_that_a_user_starts_is_announced(self):
        controller, client, renderer = make_controller()

        controller.play(renderer, {'title': 'Himmel', 'artist': 'Falke'})

        self.assertEqual(client.sent, ['frage zero mukke, spiele das Lied Himmel von Falke'])

    def test_a_track_that_follows_on_its_own_is_played_quietly(self):
        controller, client, renderer = make_controller()

        controller.play_track(renderer, {'title': 'Himmel', 'artist': 'Falke'}, quiet=True)

        self.assertEqual(client.sent, ['frage zero mukke, spiele das Lied Himmel von Falke leise'])

    def test_the_announcement_can_be_turned_off(self):
        controller, client, renderer = make_controller(announce='never')

        controller.play(renderer, {'title': 'Himmel', 'artist': 'Falke'})

        self.assertEqual(client.sent, ['frage zero mukke, spiele das Lied Himmel von Falke leise'])

    def test_every_track_can_be_announced(self):
        controller, client, renderer = make_controller(announce='always')

        controller.play_track(renderer, {'title': 'Himmel', 'artist': 'Falke'}, quiet=True)

        self.assertEqual(client.sent, ['frage zero mukke, spiele das Lied Himmel von Falke'])

    def test_an_unknown_announcement_mode_falls_back_to_the_default(self):
        controller, _, _ = make_controller(announce='sometimes')

        self.assertEqual(controller.announce, 'explicit')


class ControllerQueueTests(unittest.TestCase):
    def setUp(self):
        self.subsonic = FakeSubsonic()
        self.controller = AlexaRendererController(
            cookie_file='/does/not/exist',
            subsonic_connection=self.subsonic,
        )
        self.renderer = MediaRenderer('uuid:1234', 'Echo Dot', make_device(), self.controller)

    def test_the_queue_of_a_track_is_the_album_of_the_track(self):
        self.subsonic.song = {'id': '42', 'title': 'Some Song', 'albumId': 'album-1'}
        self.subsonic.album = [{'id': '42', 'title': 'Some Song'}, {'id': '43', 'title': 'Another Song'}]

        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', '')
        queue = self.controller.resolve_queue(self.renderer)

        self.assertEqual([track['title'] for track in queue], ['Some Song', 'Another Song'])
        self.assertEqual(queue[0]['uri'], 'http://navidrome/rest/stream?id=42')

    def test_the_queue_of_a_playlist_is_the_playlist(self):
        self.subsonic.playlist = [{'id': '42', 'title': 'Some Song'}, {'id': '43', 'title': 'Another Song'}]

        self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=playlist-1', '')
        queue = self.controller.resolve_queue(self.renderer)

        self.assertEqual([track['title'] for track in queue], ['Some Song', 'Another Song'])

    def test_the_queue_is_built_from_the_title_when_the_uri_has_no_id(self):
        self.subsonic.song = {'id': '42', 'title': 'Some Song', 'albumId': 'album-1'}
        self.subsonic.album = [{'id': '42', 'title': 'Some Song'}]

        self.renderer.set_av_transport_uri('http://navidrome/rest/stream', '')
        queue = self.controller.resolve_queue(self.renderer)

        self.assertEqual([track['title'] for track in queue], ['Some Song'])

    def test_the_renderer_remembers_the_client(self):
        self.renderer.set_client('Jellybox/1.4.2 (Android)')

        self.assertEqual(self.renderer.client_name, 'Jellybox')


class FakeAlexaClientWithVolume(FakeAlexaClient):
    """A stand in for the client that sends the commands to the Alexa device with volume support."""

    def __init__(self):
        super().__init__()
        self.volumes = {}

    def get_device_volume(self, device):
        return self.volumes.get(device.get('serialNumber'), 7)

    def send_text_command(self, device, text, locale='en-US'):
        self.sent.append(text)


def make_controller_with_volume(announce='explicit'):
    controller = AlexaRendererController(
        cookie_file='/does/not/exist',
        skill_name='zero mukke',
        locale='de-DE',
        announce=announce,
    )
    client = FakeAlexaClientWithVolume()
    controller._client = lambda: client
    renderer = MediaRenderer('uuid:1234', 'Echo Dot', make_device(), controller)

    return controller, client, renderer


class ControllerVolumeTests(unittest.TestCase):
    def setUp(self):
        self.controller = AlexaRendererController(
            cookie_file='/does/not/exist',
            skill_name='zero mukke',
            locale='de-DE',
        )
        self.client = FakeAlexaClient()
        self.controller._client = lambda: self.client
        self.renderer = MediaRenderer('uuid:1234', 'Echo Dot', make_device(), self.controller)

    def test_absolute_volume(self):
        controller, client, renderer = make_controller_with_volume()
        client.volumes['serial-1'] = 5

        controller.set_volume(renderer, volume=8, adjust='absolute')

        self.assertEqual(client.sent, ['lauter'])

    def test_increase_volume_with_current(self):
        controller, client, renderer = make_controller_with_volume()
        client.volumes['serial-1'] = 5

        controller.set_volume(renderer, volume=0, adjust='increase', use_current=True)

        self.assertEqual(client.sent, ['lauter'])

    def test_decrease_volume_with_current(self):
        controller, client, renderer = make_controller_with_volume()
        client.volumes['serial-1'] = 8

        controller.set_volume(renderer, volume=0, adjust='decrease', use_current=True)

        self.assertEqual(client.sent, ['leiser'])

    def test_increase_volume_without_current_fallback(self):
        controller, client, renderer = make_controller_with_volume()

        controller.set_volume(renderer, volume=0, adjust='increase', use_current=False)

        self.assertEqual(client.sent, ['lauter'])

    def test_decrease_volume_without_current_fallback(self):
        controller, client, renderer = make_controller_with_volume()

        controller.set_volume(renderer, volume=0, adjust='decrease', use_current=False)

        self.assertEqual(client.sent, ['leiser'])
