import logging
import unittest

from castnavidrome.utils import HealthCheckLogFilter, SUCCESS_MATCH, get_resolved_slot_value


class HealthCheckLogFilterTests(unittest.TestCase):
    def setUp(self):
        self.log_filter = HealthCheckLogFilter()

    def record(self, address='127.0.0.1', path='/health', status='200', method='GET'):
        return logging.LogRecord('werkzeug', logging.INFO, '', 0,
                                 f'{address} - - [date] "%s" %s %s\n',
                                 (f'{method} {path} HTTP/1.1', status, '-'), None)

    def test_suppresses_successful_local_health_checks(self):
        self.assertFalse(self.log_filter.filter(self.record()))

    def test_preserves_other_requests_and_errors(self):
        for record in (self.record(path='/'), self.record(status='503'),
                       self.record(method='POST'), self.record(address='192.0.2.1')):
            self.assertTrue(self.log_filter.filter(record))


class FakeStatus:
    def __init__(self, code):
        self.code = code


class FakeAuthorityValue:
    def __init__(self, name):
        self.value = type('Value', (), {'name': name})()


class FakeAuthority:
    def __init__(self, code, names):
        self.status = FakeStatus(code)
        self.values = [FakeAuthorityValue(name) for name in names]


class FakeResolutions:
    def __init__(self, authorities):
        self.resolutions_per_authority = authorities


class FakeSlot:
    def __init__(self, value, authorities=None):
        self.value = value
        self.resolutions = FakeResolutions(authorities) if authorities else None


class FakeIntent:
    def __init__(self, slots):
        self.slots = slots


class FakeRequest:
    def __init__(self, slots):
        self.intent = FakeIntent(slots)


class FakeEnvelope:
    def __init__(self, slots):
        self.request = FakeRequest(slots)


class FakeHandlerInput:
    def __init__(self, slots):
        self.request_envelope = FakeEnvelope(slots)


class ResolvedSlotValueTests(unittest.TestCase):
    def test_a_missing_slot_returns_none(self):
        handler_input = FakeHandlerInput({})

        self.assertIsNone(get_resolved_slot_value(handler_input, 'artist'))

    def test_a_slot_without_a_resolution_returns_the_raw_value(self):
        handler_input = FakeHandlerInput({'artist': FakeSlot('Pink Floyd')})

        self.assertEqual(get_resolved_slot_value(handler_input, 'artist'), 'Pink Floyd')

    def test_a_resolved_slot_returns_the_canonical_name(self):
        # Ported from jfagn/asknavidrome (MIT)
        authority = FakeAuthority(SUCCESS_MATCH, ['Play-Rewind'])
        handler_input = FakeHandlerInput({'playlist': FakeSlot('play rewind', [authority])})

        self.assertEqual(get_resolved_slot_value(handler_input, 'playlist'), 'Play-Rewind')

    def test_a_failed_resolution_returns_the_raw_value(self):
        authority = FakeAuthority('ER_SUCCESS_NO_MATCH', ['Play-Rewind'])
        handler_input = FakeHandlerInput({'playlist': FakeSlot('play rewind', [authority])})

        self.assertEqual(get_resolved_slot_value(handler_input, 'playlist'), 'play rewind')

    def test_the_first_successful_authority_is_used(self):
        first = FakeAuthority('ER_SUCCESS_NO_MATCH', ['Wrong'])
        second = FakeAuthority(SUCCESS_MATCH, ['Right'])
        handler_input = FakeHandlerInput({'playlist': FakeSlot('raw', [first, second])})

        self.assertEqual(get_resolved_slot_value(handler_input, 'playlist'), 'Right')
