import tempfile
import unittest
from pathlib import Path
from unittest import mock

from castnavidrome.state import (
    DEFAULT_DEVICE_ID,
    get_background_process,
    get_device_id,
    get_known_device_ids,
    get_play_queue,
    set_background_process,
    stop_background_process,
)
from castnavidrome.track import Track
from castnavidrome.renderer_bridge import RendererBridge, RendererBridgeServer


class RendererBridgeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bridge = RendererBridge(str(Path(self.directory.name) / 'bridge.sqlite3'))

    def test_unique_recent_track_associates_device_and_renderer(self):
        self.bridge.register_start('renderer-1', 'song-1')
        self.assertTrue(self.bridge.bind_start('device-1', 'song-1'))
        self.assertEqual(self.bridge.renderer_for('device-1'), 'renderer-1')

    def test_same_track_on_two_renderers_is_not_guessed(self):
        self.bridge.register_start('renderer-1', 'song-1')
        self.bridge.register_start('renderer-2', 'song-1')
        self.assertFalse(self.bridge.bind_start('device-1', 'song-1'))
        self.assertEqual(self.bridge.renderer_for('device-1'), '')

    def test_old_start_does_not_bind(self):
        with mock.patch('castnavidrome.renderer_bridge.time.time', return_value=100):
            self.bridge.register_start('renderer-1', 'song-1')
        with mock.patch('castnavidrome.renderer_bridge.time.time', return_value=131):
            self.assertFalse(self.bridge.bind_start('device-1', 'song-1'))

    def test_unmatched_start_clears_previous_binding(self):
        self.bridge.register_start('renderer-1', 'song-1')
        self.bridge.bind_start('device-1', 'song-1')
        self.assertFalse(self.bridge.bind_start('device-1', 'different-song'))
        self.assertEqual(self.bridge.renderer_for('device-1'), '')

    def test_bridge_routes_only_an_associated_device(self):
        self.bridge.register_start('renderer-1', 'song-1')
        self.bridge.bind_start('device-1', 'song-1')
        received = []
        server = RendererBridgeServer(self.bridge, lambda request: received.append(request) or {'id': 'song-2'})
        server.start()
        self.addCleanup(server.stop)
        self.assertEqual(self.bridge.request_next('device-1', 'song-1', 'peek'), {'id': 'song-2'})
        self.assertEqual(received[0]['renderer'], 'renderer-1')
        self.assertEqual(self.bridge.request_next('device-2', 'song-1', 'peek'), {})
        self.assertEqual(len(received), 1)

    def test_second_server_does_not_replace_a_live_socket(self):
        first = RendererBridgeServer(self.bridge, lambda request: {'id': 'song-2'})
        first.start()
        self.addCleanup(first.stop)
        second = RendererBridgeServer(self.bridge, lambda request: {})
        with self.assertRaises(OSError):
            second.start()
        self.bridge.register_start('renderer-1', 'song-1')
        self.bridge.bind_start('device-1', 'song-1')
        self.assertEqual(self.bridge.request_next('device-1', 'song-1', 'peek'), {'id': 'song-2'})


class FakeDevice:
    def __init__(self, device_id):
        self.device_id = device_id


class FakeSystem:
    def __init__(self, device):
        self.device = device


class FakeContext:
    def __init__(self, device):
        self.system = FakeSystem(device)


class FakeEnvelope:
    def __init__(self, device):
        self.context = FakeContext(device)


class FakeHandlerInput:
    def __init__(self, device):
        self.request_envelope = FakeEnvelope(device)


class StateTests(unittest.TestCase):
    def test_renderer_control_flag_is_shared_and_cleared_with_queue(self):
        queue = get_play_queue('renderer-controlled-device')
        queue.set_renderer_controlled(True)
        self.assertTrue(queue.is_renderer_controlled())
        queue.clear()
        self.assertFalse(queue.is_renderer_controlled())

    def test_every_device_has_its_own_queue(self):
        # Ported from bickns/asknavidrome (MIT)
        first = get_play_queue('device-one')
        second = get_play_queue('device-two')

        self.assertIsNot(first, second)

    def test_a_device_always_gets_the_same_queue(self):
        first = get_play_queue('device-three')
        second = get_play_queue('device-three')

        self.assertIs(first, second)

    def test_the_queues_are_independent(self):
        first = get_play_queue('device-four')
        second = get_play_queue('device-five')

        first.add_track(Track(id='track-1'))

        self.assertEqual(len(first.get_current_queue()), 1)
        self.assertEqual(len(second.get_current_queue()), 0)

    def test_the_known_devices_are_listed(self):
        get_play_queue('device-six')

        self.assertIn('device-six', get_known_device_ids())

    def test_a_device_without_a_process_has_none(self):
        self.assertIsNone(get_background_process('device-without-process'))

    def test_the_background_process_is_stored(self):
        set_background_process('device-seven', 'a process')

        self.assertEqual(get_background_process('device-seven'), 'a process')

    def test_stopping_a_process_clears_it(self):
        class FakeProcess:
            def __init__(self):
                self.terminated = False
                self.joined = False

            def terminate(self):
                self.terminated = True

            def join(self):
                self.joined = True

        process = FakeProcess()
        set_background_process('device-eight', process)

        stop_background_process('device-eight')

        self.assertTrue(process.terminated)
        self.assertTrue(process.joined)
        self.assertIsNone(get_background_process('device-eight'))

    def test_stopping_without_a_process_is_safe(self):
        stop_background_process('device-nine')

        self.assertIsNone(get_background_process('device-nine'))

    def test_the_default_device_is_used_as_a_fallback(self):
        self.assertEqual(DEFAULT_DEVICE_ID, 'default')

    def test_the_device_of_the_request_is_used(self):
        handler_input = FakeHandlerInput(FakeDevice('amzn1.ask.device.1234'))

        self.assertEqual(get_device_id(handler_input), 'amzn1.ask.device.1234')

    def test_a_request_without_a_device_uses_the_default(self):
        handler_input = FakeHandlerInput(None)

        self.assertEqual(get_device_id(handler_input), DEFAULT_DEVICE_ID)

    def test_a_request_without_a_device_id_uses_the_default(self):
        handler_input = FakeHandlerInput(FakeDevice(''))

        self.assertEqual(get_device_id(handler_input), DEFAULT_DEVICE_ID)

    def test_a_request_without_a_context_uses_the_default(self):
        class BrokenHandlerInput:
            pass

        self.assertEqual(get_device_id(BrokenHandlerInput()), DEFAULT_DEVICE_ID)


if __name__ == '__main__':
    unittest.main()
