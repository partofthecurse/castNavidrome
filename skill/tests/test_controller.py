"""Tests for the playback controller of the skill.

The module checks that the cover art of the current track is only attached
to the playback directive when the device has a screen (for example an Echo
Show), so that the album cover is shown on Echo Show devices.
"""

import unittest
from unittest import mock

from castnavidrome import controller
from castnavidrome.cover_art import DEFAULT_ART_URL
from castnavidrome.track import Track


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

    def test_omits_cover_art_when_device_has_no_screen(self):
        handler_input = self._play(with_screen=False)
        directive = handler_input.response_builder.directives[0]
        metadata = directive.audio_item.metadata
        self.assertIsNone(metadata.art)
        self.assertIsNone(metadata.background_image)
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


if __name__ == '__main__':
    unittest.main()
