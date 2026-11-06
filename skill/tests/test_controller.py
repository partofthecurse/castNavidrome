"""Tests for the playback controller of the skill.

The module checks that the cover art of the current track is attached
to the playback directive, including when display capabilities are absent.
"""

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from castnavidrome import controller
from castnavidrome.cover_art import DEFAULT_ART_URL
from castnavidrome.track import Track
from castnavidrome.media_queue import MediaQueue


class FakeSupportedInterfaces:
    """Stand-in for the supported interfaces of an Alexa device."""

    def __init__(self, display):
        self.display = display


class FakeDevice:
    """Stand-in for an Alexa device with ``supported_interfaces``."""

    def __init__(self, supported_interfaces):
        self.supported_interfaces = supported_interfaces


class FakeSystem:
    """Stand-in for the system object of a request."""

    def __init__(self, device):
        self.device = device


class FakeContext:
    """Stand-in for the request context."""

    def __init__(self, system):
        self.system = system


class FakeRequestEnvelope:
    """Stand-in for the request envelope."""

    def __init__(self, context):
        self.context = context


class FakeResponseBuilder:
    """Records the calls of the Alexa response builder."""

    def __init__(self):
        self.directives = []
        self.card = None
        self.should_end_session = None
        self.output_speech = None
        self.response = None

    def add_directive(self, directive):
        self.directives.append(directive)
        return self

    def set_card(self, card):
        self.card = card
        return self

    def set_should_end_session(self, value):
        self.should_end_session = value
        return self

    def speak(self, text):
        self.output_speech = text
        return self


class FakeHandlerInput:
    """Stand-in for the Alexa HandlerInput."""

    def __init__(self, device):
        self.request_envelope = FakeRequestEnvelope(
            FakeContext(FakeSystem(device))
        )
        self.response_builder = FakeResponseBuilder()


def make_handler_input(with_screen: bool) -> FakeHandlerInput:
    """Build a fake handler input, optionally with a screen-capable device."""

    display = object() if with_screen else None
    supported = FakeSupportedInterfaces(display)
    device = FakeDevice(supported)
    return FakeHandlerInput(device)


class DeviceHasScreenTests(unittest.TestCase):
    """Tests for ``device_has_screen``."""

    def test_returns_true_when_display_interface_is_present(self):
        handler_input = make_handler_input(with_screen=True)
        self.assertTrue(controller.device_has_screen(handler_input))

    def test_returns_false_when_display_interface_is_none(self):
        handler_input = make_handler_input(with_screen=False)
        self.assertFalse(controller.device_has_screen(handler_input))

    def test_returns_false_when_device_has_no_supported_interfaces(self):
        device = FakeDevice(None)
        handler_input = FakeHandlerInput(device)
        self.assertFalse(controller.device_has_screen(handler_input))

    def test_returns_false_when_there_is_no_device(self):
        system = FakeSystem(None)
        context = FakeContext(system)
        request_envelope = FakeRequestEnvelope(context)
        handler_input = FakeHandlerInput.__new__(FakeHandlerInput)
        handler_input.request_envelope = request_envelope
        handler_input.response_builder = FakeResponseBuilder()
        self.assertFalse(controller.device_has_screen(handler_input))

    def test_returns_false_when_there_is_no_context(self):
        handler_input = FakeHandlerInput.__new__(FakeHandlerInput)
        handler_input.response_builder = FakeResponseBuilder()

        class NoContext:
            pass

        handler_input.request_envelope = NoContext()
        self.assertFalse(controller.device_has_screen(handler_input))


class StartPlaybackTests(unittest.TestCase):
    """Tests for ``start_playback``."""

    def setUp(self):
        self.track = Track(
            id='track-1',
            title='Song title',
            artist='Artist name',
            album='Album name',
            cover_art='cover-1',
        )
        self.base_url_patch = mock.patch.object(
            controller, 'NAVI_BASE_URL', 'https://skill.example.test'
        )
        self.base_url_patch.start()

    def tearDown(self):
        self.base_url_patch.stop()

    def _play(self, with_screen: bool):
        handler_input = make_handler_input(with_screen)
        controller.start_playback(
            'play',
            'Now playing',
            {'title': 'castNavidrome', 'text': 'Now playing'},
            self.track,
            handler_input,
        )
        return handler_input

    def test_attaches_cover_art_when_device_has_a_screen(self):
        handler_input = self._play(with_screen=True)
        self.assertEqual(len(handler_input.response_builder.directives), 1)
        directive = handler_input.response_builder.directives[0]
        metadata = directive.audio_item.metadata
        self.assertIsNotNone(metadata.art)
        self.assertIsNotNone(metadata.background_image)
        self.assertEqual(
            metadata.art.sources[0].url,
            'https://skill.example.test/cover/cover-1',
        )
        self.assertEqual(
            metadata.background_image.sources[0].url,
            'https://skill.example.test/cover/cover-1',
        )

    def test_attaches_cover_art_when_display_interface_is_missing(self):
        handler_input = self._play(with_screen=False)
        directive = handler_input.response_builder.directives[0]
        metadata = directive.audio_item.metadata
        self.assertEqual(metadata.art.sources[0].url, 'https://skill.example.test/cover/cover-1')
        self.assertEqual(metadata.background_image.sources[0].url, 'https://skill.example.test/cover/cover-1')
        self.assertEqual(metadata.title, 'Song title')
        self.assertEqual(metadata.subtitle, 'Artist name')

    def test_shows_default_logo_when_there_is_no_cover(self):
        track_no_cover = Track(id='track-2', title='Song', artist='Artist')
        handler_input = make_handler_input(with_screen=True)
        controller.start_playback('play', None, None, track_no_cover, handler_input)
        directive = handler_input.response_builder.directives[0]
        metadata = directive.audio_item.metadata
        self.assertEqual(metadata.art.sources[0].url, DEFAULT_ART_URL)
        self.assertEqual(metadata.background_image.sources[0].url, DEFAULT_ART_URL)

    def test_end_session_is_set(self):
        handler_input = self._play(with_screen=True)
        self.assertTrue(handler_input.response_builder.should_end_session)


class RendererNextTests(unittest.TestCase):
    def setUp(self):
        self.queue = MediaQueue()
        self.queue.set_current_track(Track(id='track-1', title='First'))
        self.queue.set_renderer_controlled(True)
        self.api = mock.Mock()
        self.api.get_song_details.return_value = {'song': {'id': 'track-2', 'title': 'Next', 'artist': 'Artist'}}
        self.api.get_song_uri.return_value = 'https://example.test/stream'
        self.bridge = mock.Mock()

    def test_committed_renderer_track_becomes_the_skill_current_track(self):
        self.bridge.request_next.side_effect = [{'id': 'track-2'}, {'ok': True}]
        track = controller.get_renderer_next(self.bridge, 'device-1', self.api, self.queue)
        self.assertEqual(track.id, 'track-2')
        self.assertEqual(self.queue.get_current_track().id, 'track-2')
        self.assertTrue(self.queue.is_transitioning())
        self.assertEqual(self.bridge.request_next.call_args_list, [
            mock.call('device-1', 'track-1', 'peek'),
            mock.call('device-1', 'track-1', 'commit', 'track-2'),
        ])

    def test_failed_or_stale_commit_does_not_change_skill_queue(self):
        self.bridge.request_next.side_effect = [{'id': 'track-2'}, {'ok': False}]
        self.assertIsNone(controller.get_renderer_next(self.bridge, 'device-1', self.api, self.queue))
        self.assertEqual(self.queue.get_current_track().id, 'track-1')

    def test_missing_track_details_does_not_commit(self):
        self.bridge.request_next.return_value = {'id': 'track-2'}
        self.api.get_song_details.return_value = {'song': {}}
        self.assertIsNone(controller.get_renderer_next(self.bridge, 'device-1', self.api, self.queue))
        self.assertEqual(self.bridge.request_next.call_count, 1)

    def test_skill_owned_queue_does_not_contact_renderer(self):
        self.queue.set_renderer_controlled(False)
        self.assertIsNone(controller.get_renderer_next(self.bridge, 'device-1', self.api, self.queue))
        self.bridge.request_next.assert_not_called()


class NextIntentBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        environment = {
            'NAVI_SKILL_ID': 'test', 'NAVI_URL': 'https://navidrome.example.test',
            'NAVI_BASE_URL': 'https://skill.example.test', 'NAVI_USER': 'test',
            'NAVI_PASS': 'test', 'NAVI_ALEXA_API_KEY': 'test',
            'NAVI_ALEXA_SKILL_NAME': 'test', 'TS_AUTHKEY': 'test',
        }
        with mock.patch.dict(os.environ, environment):
            with mock.patch('castnavidrome.subsonic_api.SubsonicConnection'):
                with mock.patch('castnavidrome.ask_sdk_compat.install_certificate_chain_workaround'):
                    cls.app = importlib.import_module('app')

    def setUp(self):
        self.queue = MediaQueue()
        self.queue.set_current_track(Track(id='track-1', title='First'))
        self.queue.set_renderer_controlled(True)
        self.input = make_handler_input(with_screen=False)
        self.bridge = mock.Mock()
        self.bridge.request_next.side_effect = [{'id': 'track-2'}, {'ok': True}]
        self.api = mock.Mock()
        self.api.get_song_details.return_value = {'song': {'id': 'track-2', 'title': 'Next', 'artist': 'Artist'}}
        self.api.get_song_uri.return_value = 'https://example.test/stream'
        self.patches = [mock.patch.object(self.app.state, 'get_device_id', return_value='device-1'),
                        mock.patch.object(self.app.state, 'get_play_queue', return_value=self.queue),
                        mock.patch.object(self.app, 'renderer_bridge', self.bridge),
                        mock.patch.object(self.app, 'connection', self.api)]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_next_intent_plays_the_renderer_track(self):
        self.app.NextPlaybackHandler().handle(self.input)
        self.assertEqual(self.input.response_builder.directives[0].audio_item.stream.token, 'track-2')
        self.assertEqual(self.queue.get_current_track().id, 'track-2')

    def test_next_during_transition_is_buffered_then_uses_renderer(self):
        self.queue.set_transitioning(True)
        self.app.NextPlaybackHandler().handle(self.input)
        self.assertEqual(self.input.response_builder.directives, [])
        self.bridge.request_next.assert_not_called()
        self.app.PlaybackStartedHandler().handle(self.input)
        self.assertEqual(self.input.response_builder.directives[0].audio_item.stream.token, 'track-2')

    def test_next_intent_through_real_renderer_bridge(self):
        from castnavidrome.renderer_host import RendererHost
        from castnavidrome.upnp.renderer import MediaRenderer

        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'bridge.sqlite3')
            host = RendererHost(env={'NAVI_RENDERER_BRIDGE_PATH': path,
                                     'NAVI_ALEXA_RENDERER_ADVERTISE_HOST': '127.0.0.1'})
            renderer = MediaRenderer('renderer-1', 'Echo', command_handler=host.controller)
            renderer.track = {'id': 'track-1', 'title': 'First', 'duration': 0}
            renderer.queue = [dict(renderer.track), {'id': 'track-2', 'title': 'Next', 'duration': 0}]
            renderer.queue_index = 0
            renderer.transport_state = 'PLAYING'
            host.server.add_renderer(renderer)
            bridge = host.controller.bridge
            bridge.register_start(renderer.udid, 'track-1')
            self.assertTrue(bridge.bind_start('device-1', 'track-1'))
            host.bridge_server.start()
            try:
                with mock.patch.object(self.app, 'renderer_bridge', bridge):
                    self.app.NextPlaybackHandler().handle(self.input)
                self.assertEqual(self.input.response_builder.directives[0].audio_item.stream.token, 'track-2')
                self.assertEqual(renderer.track['id'], 'track-2')
                self.assertEqual(self.queue.get_current_track().id, 'track-2')
            finally:
                host.bridge_server.stop()
                renderer._cancel_advance()

    def test_old_stopped_event_does_not_change_the_new_track(self):
        self.queue.set_current_track(Track(id='track-2', title='Next', offset=0))
        self.queue.set_playback_active(True)
        self.input.request_envelope.request = SimpleNamespace(token='track-1', offset_in_milliseconds=15000)
        self.app.PlaybackStoppedHandler().handle(self.input)
        self.assertTrue(self.queue.is_playback_active())
        self.assertEqual(self.queue.get_current_track().offset, 0)

    def test_old_started_event_does_not_complete_the_new_transition(self):
        self.queue.set_current_track(Track(id='track-2', title='Next'))
        self.queue.set_transitioning(True)
        self.input.request_envelope.request = SimpleNamespace(token='track-1')
        self.app.PlaybackStartedHandler().handle(self.input)
        self.assertTrue(self.queue.is_transitioning())

    def test_old_finished_event_scrobbles_the_old_track_without_changing_queue(self):
        self.queue.set_current_track(Track(id='track-2', title='Next'))
        self.input.request_envelope.request = SimpleNamespace(token='track-1')
        self.app.PlaybackFinishedHandler().handle(self.input)
        self.assertEqual(self.api.scrobble.call_args.args[0], 'track-1')
        self.assertEqual(self.queue.get_current_track().id, 'track-2')


if __name__ == '__main__':
    unittest.main()
