import asyncio
import os
import signal
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
            'NAVI_RENDERER_BRIDGE_PATH': str(Path(self.temp_dir.name) / 'bridge.sqlite3'),
            'NAVI_ALEXA_RENDERER_PORT': '0',
            'NAVI_ALEXA_RENDERER_ADVERTISE_HOST': '127.0.0.1',
            'NAVI_ALEXA_RENDERER_REFRESH_SECONDS': '300',
            'NAVI_ALEXA_SKILL_NAME': 'castnavidrome',
            'NAVI_ALEXA_LOCALE': 'de-DE',
            'NAVI_ALEXA_DOMAIN': 'amazon.com',
            'NAVI_ALEXA_RENDERER_DEFAULT_VOLUME': '1',
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

    def test_default_volume_is_set_once_using_alexa_scale(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        self.host.aioamazon_session = MagicMock(is_configured=True)
        self.host.controller.aioamazon_session = self.host.aioamazon_session
        self.host.controller.set_volume = MagicMock()

        self.host._apply_default_volume()

        renderer = self.host.server.renderers()[0]
        self.assertEqual(renderer.volume, 10)
        self.host.controller.set_volume.assert_called_once_with(renderer, volume=10)

    def test_default_volume_must_be_in_alexa_range(self):
        self.env['NAVI_ALEXA_RENDERER_DEFAULT_VOLUME'] = '11'
        with self.assertRaisesRegex(ValueError, 'from 0 to 10'):
            RendererHost(env=self.env)

    def test_a_device_that_is_gone_removes_its_renderer(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        self.host.sync_renderers([])

        self.assertEqual(self.host.server.renderers(), [])

    def test_the_uuid_of_a_device_stays_the_same_after_a_refresh(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        udid = self.host.server.renderers()[0].udid

        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])

        self.assertEqual(self.host.server.renderers()[0].udid, udid)

    def test_voice_bridge_advances_only_the_bound_renderer(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1'), make_device('Echo Kitchen', 'serial-2')])
        renderer = next(item for item in self.host.server.renderers() if item.device['serialNumber'] == 'serial-1')
        renderer.track = {'id': '42', 'title': 'Current', 'duration': 0}
        renderer.queue = [dict(renderer.track), {'id': '43', 'title': 'Next', 'duration': 0}]
        renderer.queue_index = 0
        renderer.transport_state = 'PLAYING'
        self.host.controller.bridge.register_start(renderer.udid, '42')
        self.host.controller.bridge.bind_start('skill-device-1', '42')
        self.host.bridge_server.start()
        self.addCleanup(self.host.bridge_server.stop)
        bridge = self.host.controller.bridge
        self.assertEqual(bridge.request_next('skill-device-1', '42', 'peek'), {'id': '43'})
        self.assertEqual(bridge.request_next('skill-device-1', '42', 'commit', '43'), {'ok': True})
        self.assertEqual(renderer.track['id'], '43')
        self.assertEqual(bridge.request_next('skill-device-1', '42', 'commit', '43'), {'ok': False})
        self.assertEqual(bridge.request_next('other-device', '42', 'peek'), {})

    def test_the_registry_is_written_during_the_sync(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])

        self.assertTrue(Path(self.env['NAVI_ALEXA_RENDERER_STATE_FILE']).is_file())

    def test_a_failing_api_keeps_the_last_known_devices(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1')])
        self.host.list_devices = lambda: (_ for _ in ()).throw(AlexaRemoteError('Alexa is not reachable.'))

        self.host.refresh()

        self.assertEqual(len(self.host.server.renderers()), 1)

    def test_parallel_discovery_requests_only_refresh_once(self):
        self.host.disable_refresh = False
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

    def test_ssdp_search_does_not_refresh_in_start_only_mode(self):
        self.host.disable_refresh = True

        with patch('castnavidrome.renderer_host.threading.Thread') as thread_factory:
            self.host._on_discovery_request()

        thread_factory.assert_not_called()

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

    def test_cookie_file_change_requests_container_restart(self):
        cookie_file = Path(self.temp_dir.name) / 'alexa.cookies'
        cookie_file.write_text('csrf=old\n', encoding='utf-8')
        self.env['NAVI_ALEXA_COOKIE_FILE'] = str(cookie_file)
        host = RendererHost(env=self.env)

        cookie_file.write_text('csrf=new\n', encoding='utf-8')
        changed_mtime = host._cookie_file_mtime + 2
        os.utime(cookie_file, (changed_mtime, changed_mtime))

        with patch('castnavidrome.renderer_host.os.kill') as kill_process:
            host._maybe_restart_on_cookie_change()

        kill_process.assert_called_once_with(os.getpid(), signal.SIGTERM)

    def test_missing_configured_cookie_path_uses_mounted_cookie_file(self):
        configured = Path(self.temp_dir.name) / 'missing.cookies'
        mounted = Path(self.temp_dir.name) / 'mounted.cookies'
        mounted.write_text('csrf=mounted\n', encoding='utf-8')
        self.env['NAVI_ALEXA_COOKIE_FILE'] = str(configured)

        with patch('castnavidrome.amazon_login.DEFAULT_COOKIE_FILE', mounted):
            host = RendererHost(env=self.env)

        self.assertEqual(host.cookie_file, str(configured))
        self.assertEqual(host.amazon_session.session_file, configured)
        self.assertEqual(host.controller.cookie_file, str(configured))
        self.assertEqual(configured.read_text(encoding='utf-8'), 'csrf=mounted\n')

    def test_cookie_watcher_runs_when_device_refresh_is_disabled(self):
        self.env['NAVI_ALEXA_RENDERER_DISABLE_REFRESH'] = 'true'
        host = RendererHost(env=self.env)

        with patch.object(host._stop_event, 'wait', side_effect=[False, True]):
            with patch.object(host, '_maybe_restart_on_cookie_change') as check_cookie:
                host._cookie_watch_loop()

        check_cookie.assert_called_once()

    def test_echo_status_is_routed_to_matching_renderer(self):
        self.host.sync_renderers([make_device('Echo Dot', 'serial-1'), make_device('Echo Kitchen', 'serial-2')])
        renderers = self.host.server.renderers()
        for renderer in renderers:
            renderer.transport_state = 'PLAYING'
            renderer.started_at = 100
            renderer.track['id'] = '42'
            renderer.track['title'] = 'Some Song'
            renderer.sync_echo_state = MagicMock()

        states = {
            'serial-1': SimpleNamespace(player_state='PAUSED', media_position=10,
                                        media_length=100, now_playing_title='Some Song'),
            'serial-2': SimpleNamespace(player_state='PAUSED', media_position=20,
                                        media_length=100, now_playing_title='Other Song'),
        }

        class MediaHandler:
            sync_media_state = AsyncMock()

            @property
            async def media_states(self):
                return states

        @asynccontextmanager
        async def connected_api():
            yield SimpleNamespace(_media_handler=MediaHandler()), {}

        async def stop_polling(_):
            self.host._stop_event.set()

        with patch.object(self.host.aioamazon_session, '_connected_api', connected_api):
            with patch('castnavidrome.renderer_host.asyncio.sleep', side_effect=stop_polling):
                asyncio.run(self.host._poll_echo_states())

        by_serial = {renderer.device['serialNumber']: renderer for renderer in renderers}
        by_serial['serial-1'].sync_echo_state.assert_called_once_with('PAUSED', 10, 100, 100, title_matches=True)
        by_serial['serial-2'].sync_echo_state.assert_not_called()


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
    def test_a_stale_offline_flag_does_not_block_a_control_command(self):
        controller, client, renderer = make_controller()
        renderer.device['online'] = False

        controller.pause(renderer)

        self.assertEqual(client.sent, ['frage zero mukke, pausiere'])

    def test_aioamazondevices_handles_text_commands_when_configured(self):
        controller, legacy_client, renderer = make_controller()
        aio_client = MagicMock()
        aio_client.is_configured = True
        controller.aioamazon_session = aio_client

        controller.volume_up(renderer)

        aio_client.send_text_command.assert_called_once_with(
            renderer.device,
            'lauter',
            locale='de-DE',
        )
        self.assertEqual(legacy_client.sent, [])

    def test_a_track_that_a_user_starts_is_announced(self):
        controller, client, renderer = make_controller()

        controller.play(renderer, {'title': 'Himmel', 'artist': 'Falke'})

        self.assertEqual(client.sent, ['frage zero mukke, spiele das Lied Himmel von Falke'])

    def test_renderer_track_registers_the_pending_device_match(self):
        controller, client, renderer = make_controller()
        controller.bridge = MagicMock()
        controller.play(renderer, {'id': 'song-1', 'title': 'Himmel', 'artist': 'Falke'})
        controller.bridge.register_start.assert_called_once_with(renderer.udid, 'song-1')
        self.assertEqual(len(client.sent), 1)

    def test_failed_track_command_removes_pending_device_match(self):
        controller, _, renderer = make_controller()
        controller.bridge = MagicMock()
        controller._send = MagicMock(side_effect=RendererCommandError('offline'))
        with self.assertRaises(RendererCommandError):
            controller.play(renderer, {'id': 'song-1', 'title': 'Himmel', 'artist': 'Falke'})
        controller.bridge.cancel_start.assert_called_once_with(renderer.udid, 'song-1')

    def test_a_track_that_follows_on_its_own_is_played_quietly(self):
        controller, client, renderer = make_controller()

        controller.play_track(renderer, {'title': 'Himmel', 'artist': 'Falke'}, quiet=True)

        self.assertEqual(client.sent, ['frage zero mukke, spiele das Lied Himmel von Falke leise'])

    def test_next_track_without_artist_does_not_resume_the_old_track(self):
        controller, client, renderer = make_controller()
        with self.assertRaises(RendererCommandError):
            controller.play_track(renderer, {'title': 'Himmel'})
        self.assertEqual(client.sent, [])

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

    def test_loading_a_song_queue_resolves_the_song_only_once(self):
        self.subsonic.song = {'id': '42', 'title': 'Some Song', 'albumId': 'album-1'}
        self.subsonic.album = [self.subsonic.song]
        with patch.object(self.subsonic, 'get_song', wraps=self.subsonic.get_song) as get_song:
            self.renderer.set_av_transport_uri('http://navidrome/rest/stream?id=42', '')
        get_song.assert_called_once_with('42')

    def test_client_next_track_is_resolved_without_changing_current_track(self):
        self.subsonic.song = {'id': '99', 'title': 'Playlist Song', 'artist': 'Artist', 'duration': 90}
        self.renderer.current_uri = 'http://navidrome/rest/stream?id=42'
        self.renderer.track['title'] = 'Current song'
        resolved = self.controller.resolve_next_track(
            self.renderer, 'http://navidrome/rest/stream?id=99', {})
        self.assertEqual(resolved['id'], '99')
        self.assertEqual(resolved['title'], 'Playlist Song')
        self.assertEqual(self.renderer.track['title'], 'Current song')
        self.assertEqual(self.renderer.current_uri, 'http://navidrome/rest/stream?id=42')

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
        controller, _, renderer = make_controller_with_volume()
        controller.aioamazon_session = MagicMock(is_configured=True)

        controller.set_volume(renderer, volume=80, adjust='absolute')

        controller.aioamazon_session.set_device_volume.assert_called_once_with(renderer.device, 80)

    def test_absolute_volume_requires_aioamazon_credentials(self):
        controller, _, renderer = make_controller_with_volume()
        with self.assertRaises(RendererCommandError):
            controller.set_volume(renderer, volume=80, adjust='absolute')

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


class VoiceStateBridgeTests(unittest.TestCase):
    def test_the_host_forwards_the_echo_states_to_the_renderer(self):
        with tempfile.TemporaryDirectory() as directory:
            host = RendererHost(env={'NAVI_RENDERER_BRIDGE_PATH': str(Path(directory) / 'bridge.sqlite3'),
                                     'NAVI_ALEXA_RENDERER_ADVERTISE_HOST': '127.0.0.1'})
            renderer = MediaRenderer('renderer-1', 'Echo', command_handler=host.controller)
            renderer.track = {'id': 'track-1', 'title': 'First', 'duration': 0}
            renderer.transport_state = 'PLAYING'
            renderer.started_at = time.time() - 10
            host.server.add_renderer(renderer)
            handle = host._handle_voice_queue

            self.assertEqual(handle({'renderer': 'renderer-1', 'current': 'track-1', 'action': 'state',
                                     'state': 'PAUSED', 'offset': 10000}), {'ok': True})
            self.assertEqual(renderer.transport_state, 'PAUSED_PLAYBACK')
            self.assertEqual(handle({'renderer': 'renderer-1', 'current': 'track-1', 'action': 'state',
                                     'state': 'RELEASED', 'offset': 0}), {'ok': True})
            self.assertEqual(renderer.transport_state, 'STOPPED')
            self.assertEqual(handle({'renderer': 'renderer-2', 'current': 'track-1', 'action': 'state',
                                     'state': 'STOPPED'}), {})
            self.assertEqual(handle({'renderer': 'renderer-1', 'current': 'track-1', 'action': 'state',
                                     'state': 'BOGUS'}), {'ok': False})
