import socket
import threading
import unittest
from unittest.mock import MagicMock, patch

from castnavidrome.upnp.constants import (
    AVTRANSPORT_SERVICE_TYPE,
    CONNECTIONMANAGER_SERVICE_TYPE,
    MEDIA_RENDERER_DEVICE_TYPE,
    RENDERINGCONTROL_SERVICE_TYPE,
)
from castnavidrome.upnp.ssdp import (
    SsdpServer,
    SSDP_SEARCH_TARGET,
    SSDP_MAX_BURST,
)


class FakeRenderer:
    def __init__(self, udid='1234'):
        self.udid = udid
        self.friendly_name = 'castNavidrome: Test'


class SsdpMulticastMembershipTests(unittest.TestCase):
    def test_ssdp_group_is_joined_on_every_ipv4_interface(self):
        class FakeSocket:
            def __init__(self):
                self.memberships = []
                self.outgoing_interface = None

            def setsockopt(self, _level, option, value):
                if option == socket.IP_ADD_MEMBERSHIP:
                    self.memberships.append(value)
                elif option == socket.IP_MULTICAST_IF:
                    self.outgoing_interface = value

        fake_socket = FakeSocket()

        self.assertTrue(SsdpServer._join_ipv4_multicast(
            fake_socket,
            ['10.0.0.2', '192.168.1.2', 'fe80::1'],
        ))
        self.assertEqual(len(fake_socket.memberships), 2)

    def test_ssdp_announcement_uses_the_advertised_local_interface(self):
        class FakeSocket:
            def __init__(self):
                self.outgoing_interface = None

            def setsockopt(self, _level, _option, value):
                self.outgoing_interface = value

        fake_socket = FakeSocket()

        self.assertTrue(SsdpServer._set_ipv4_multicast_interface(
            fake_socket,
            '192.168.1.20',
            ['10.0.0.2', '192.168.1.20'],
        ))
        self.assertEqual(fake_socket.outgoing_interface, socket.inet_aton('192.168.1.20'))


class SsdpSearchTests(unittest.TestCase):
    """The search behaviour of the SSDP responder.

    Supersonic and other clients search with "ssdp:all" and only accept the
    devices that answer with the search target of their service, so the
    services of the renderer have to be announced as well.
    """

    def setUp(self):
        self.server = SsdpServer(advertise_host='192.168.178.128', http_port=49443)
        self.renderer = FakeRenderer()
        self.server.set_renderers([self.renderer])
        self.server._sendto = MagicMock()

    def _search(self, search_target):
        message = (f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
                   f'MAN: "ssdp:discover"\r\nMX: 2\r\nST: {search_target}\r\n\r\n')

        # The handler spawns a daemon thread that sends the answers with a
        # random delay of up to MX seconds.  Wait for the thread to finish
        # so that the mocked _sendto calls are visible.
        with patch('castnavidrome.upnp.ssdp.time.sleep'):
            self.server._handle_message(message, ('192.168.178.50', 49152))

        thread = threading.enumerate()
        for t in thread:
            if t.name == 'upnp-ssdp-response' and t.is_alive():
                t.join(timeout=5)

        responses = [call.args[0].decode('utf-8') for call in self.server._sendto.call_args_list]
        # Each answer is sent twice, so the targets and usns lists contain
        # duplicates.  Deduplicate them while keeping the order.
        targets = []
        usns = []
        for response in responses:
            target = self._header(response, 'ST')
            usn = self._header(response, 'USN')
            if target not in targets:
                targets.append(target)
            if usn not in usns:
                usns.append(usn)

        return targets, usns, responses

    @staticmethod
    def _header(response, name):
        for line in response.split('\r\n'):
            if line.upper().startswith(name.upper() + ':'):
                return line.split(':', 1)[1].strip()
        return ''

    def test_the_search_for_all_answers_with_one_response_per_renderer(self):
        """A search for "ssdp:all" gets one answer per renderer, not per service."""

        targets, usns, _ = self._search('ssdp:all')

        self.assertEqual(targets, [SSDP_SEARCH_TARGET])
        self.assertEqual(usns, ['uuid:1234::ssdp:all'])

    def test_the_search_for_the_av_transport_service_is_answered(self):
        targets, usns, _ = self._search(AVTRANSPORT_SERVICE_TYPE)

        self.assertEqual(targets, [AVTRANSPORT_SERVICE_TYPE])
        self.assertEqual(usns, ['uuid:1234::' + AVTRANSPORT_SERVICE_TYPE])

    def test_the_search_for_the_device_type_is_answered(self):
        targets, _, _ = self._search(MEDIA_RENDERER_DEVICE_TYPE)

        self.assertEqual(targets, [MEDIA_RENDERER_DEVICE_TYPE])

    def test_the_search_for_an_unknown_service_is_ignored(self):
        targets, _, _ = self._search('urn:schemas-upnp-org:service:Unknown:1')

        self.assertEqual(targets, [])

    def test_the_search_for_the_root_device_answers_with_the_requested_target(self):
        targets, _, _ = self._search('upnp:rootdevice')

        self.assertEqual(targets, ['upnp:rootdevice'])

    def test_every_response_has_a_location(self):
        _, _, responses = self._search('ssdp:all')

        for response in responses:
            self.assertIn('LOCATION: http://192.168.178.128:49443/description/1234.xml', response)
            self.assertIn('HTTP/1.1 200 OK', response)

    def test_every_answer_is_sent_twice(self):
        """Each answer is repeated to survive a lost UDP packet."""

        _, _, responses = self._search('ssdp:all')

        # One renderer, one answer, sent twice.
        self.assertEqual(len(responses), 2)

    def test_every_response_is_sent_to_the_source_address(self):
        self._search('ssdp:all')

        for call in self.server._sendto.call_args_list:
            self.assertEqual(call.args[1], ('192.168.178.50', 49152))

    def test_notify_messages_are_ignored(self):
        """The renderer only answers M-SEARCH requests, never NOTIFY."""

        notify = (
            'NOTIFY * HTTP/1.1\r\n'
            'HOST: 239.255.255.250:1900\r\n'
            'NT: upnp:rootdevice\r\n'
            'NTS: ssdp:alive\r\n'
            'LOCATION: http://192.168.178.50:49443/description/1234.xml\r\n\r\n'
        )

        self.server._sendto = MagicMock()
        self.server._handle_message(notify, ('192.168.178.50', 1900))

        self.assertEqual(self.server._sendto.call_args_list, [])

    def test_http_responses_are_ignored(self):
        """HTTP responses from other devices are not answered either."""

        response = (
            'HTTP/1.1 200 OK\r\n'
            'ST: upnp:rootdevice\r\n'
            'LOCATION: http://192.168.178.50:49443/description/1234.xml\r\n\r\n'
        )

        self.server._sendto = MagicMock()
        self.server._handle_message(response, ('192.168.178.50', 49152))

        self.assertEqual(self.server._sendto.call_args_list, [])

    def test_packets_from_the_own_address_are_ignored(self):
        """The renderer ignores its own multicast announcements.

        The multicast loopback makes the renderer's own NOTIFY packets come
        back on the same sockets.  Answering them would start an endless
        M-SEARCH -> response -> M-SEARCH loop.
        """

        self.server._sendto = MagicMock()
        self.server._is_own_address = lambda host: host == '192.168.178.128'

        message = (f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
                   f'MAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n')

        self.server._handle_message(message, ('192.168.178.128', 49152))

        self.assertEqual(self.server._sendto.call_args_list, [])

    def test_loopback_address_is_own_address(self):
        self.assertTrue(self.server._is_own_address('127.0.0.1'))
        self.assertTrue(self.server._is_own_address('::1'))
        self.assertTrue(self.server._is_own_address('localhost'))

    def test_advertised_address_is_own_address(self):
        self.assertTrue(self.server._is_own_address('192.168.178.128'))

    def test_search_without_man_header_is_answered(self):
        """A search without a MAN header is still answered."""

        message = (
            'M-SEARCH * HTTP/1.1\r\n'
            'HOST: 239.255.255.250:1900\r\n'
            'MX: 2\r\n'
            'ST: ssdp:all\r\n\r\n'
        )

        with patch('castnavidrome.upnp.ssdp.time.sleep'):
            self.server._handle_message(message, ('192.168.178.50', 49152))

        for t in threading.enumerate():
            if t.name == 'upnp-ssdp-response' and t.is_alive():
                t.join(timeout=5)

        self.assertNotEqual(self.server._sendto.call_args_list, [])

    def test_missing_mx_uses_default_delay_and_is_answered(self):
        """A missing MX header defaults to 1-2 seconds and never raises."""

        message = (
            'M-SEARCH * HTTP/1.1\r\n'
            'HOST: 239.255.255.250:1900\r\n'
            'ST: ssdp:all\r\n\r\n'
        )

        with patch('castnavidrome.upnp.ssdp.time.sleep'):
            self.server._handle_message(message, ('192.168.178.50', 49152))

        for t in threading.enumerate():
            if t.name == 'upnp-ssdp-response' and t.is_alive():
                t.join(timeout=5)

        self.assertNotEqual(self.server._sendto.call_args_list, [])

    def test_av_transport_version_2_is_answered_with_requested_st(self):
        """AVTransport:2 is matched and answered with the requested ST."""

        targets, usns, _ = self._search(
            'urn:schemas-upnp-org:service:AVTransport:2'
        )

        self.assertEqual(targets, ['urn:schemas-upnp-org:service:AVTransport:2'])
        self.assertEqual(
            usns, ['uuid:1234::urn:schemas-upnp-org:service:AVTransport:2']
        )

    def test_av_transport_version_3_is_answered_with_requested_st(self):
        """AVTransport:3 is matched and answered with the requested ST."""

        targets, usns, _ = self._search(
            'urn:schemas-upnp-org:service:AVTransport:3'
        )

        self.assertEqual(targets, ['urn:schemas-upnp-org:service:AVTransport:3'])
        self.assertEqual(
            usns, ['uuid:1234::urn:schemas-upnp-org:service:AVTransport:3']
        )

    def test_rate_limit_is_a_noop_when_no_packets_were_sent(self):
        """The first packet is not delayed."""

        from unittest.mock import patch

        sleeps = []

        with patch('castnavidrome.upnp.ssdp.time.sleep', side_effect=lambda s: sleeps.append(s)):
            self.server._wait_for_rate_limit()

        self.assertEqual(sleeps, [])

    def test_rate_limit_sleeps_when_the_burst_is_full(self):
        """Once the burst cap is reached, the next packet is delayed."""

        from unittest.mock import patch

        sleeps = []

        # Fill the burst with SSDP_MAX_BURST packets, then verify that the
        # next packet has to wait until the oldest one leaves the window.
        times = [0.0] * (SSDP_MAX_BURST + 1) + [1.0, 1.0]

        with patch('castnavidrome.upnp.ssdp.time.monotonic', side_effect=times), \
             patch('castnavidrome.upnp.ssdp.time.sleep', side_effect=lambda s: sleeps.append(s)):
            for _ in range(SSDP_MAX_BURST):
                self.server._wait_for_rate_limit()
            self.server._wait_for_rate_limit()

        self.assertGreater(len(sleeps), 0)
        self.assertGreaterEqual(min(sleeps), 0.0)


class SsdpAnnounceTests(unittest.TestCase):
    """The announce behaviour of the SSDP server.

    Notifications are sent over unreliable UDP multicast, so every
    notification is repeated several times to survive a lost packet.
    """

    def setUp(self):
        self.server = SsdpServer(advertise_host='192.168.178.128', http_port=49443)
        self.renderer = FakeRenderer()
        self.server.set_renderers([self.renderer])
        self.server._sockets = [MagicMock()]
        self.server._sendto = MagicMock()

    def _notify_payloads(self, count=1, delay=0):
        self.server.announce(count=count, delay=delay)
        return [call.args[0].decode('utf-8') for call in self.server._sendto.call_args_list]

    def test_announce_repeats_every_notification(self):
        payloads = self._notify_payloads(count=3, delay=0)

        alive = [p for p in payloads if 'NTS: ssdp:alive' in p]
        targets = [SSDP_SEARCH_TARGET, MEDIA_RENDERER_DEVICE_TYPE, AVTRANSPORT_SERVICE_TYPE,
               RENDERINGCONTROL_SERVICE_TYPE, CONNECTIONMANAGER_SERVICE_TYPE]
        self.assertEqual(len(alive), 3 * len(targets) * 3)

    def test_every_notification_carries_the_location(self):
        payloads = self._notify_payloads(count=1, delay=0)

        for payload in payloads:
            self.assertIn('LOCATION: http://192.168.178.128:49443/description/1234.xml', payload)
            self.assertIn('NOTIFY * HTTP/1.1', payload)
            self.assertIn('HOST: 239.255.255.250:1900', payload)


if __name__ == '__main__':
    unittest.main()
