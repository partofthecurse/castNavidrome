import unittest

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
