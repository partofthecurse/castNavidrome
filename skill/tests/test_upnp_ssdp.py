import socket
import unittest
from unittest.mock import MagicMock

from castnavidrome.upnp.constants import (
    AVTRANSPORT_SERVICE_TYPE,
    CONNECTIONMANAGER_SERVICE_TYPE,
    MEDIA_RENDERER_DEVICE_TYPE,
    RENDERINGCONTROL_SERVICE_TYPE,
)
from castnavidrome.upnp.ssdp import SsdpServer, SSDP_SEARCH_TARGET


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

        self.server._handle_message(message, ('192.168.178.50', 49152))

        responses = [call.args[0].decode('utf-8') for call in self.server._sendto.call_args_list]
        targets = [self._header(response, 'ST') for response in responses]
        usns = [self._header(response, 'USN') for response in responses]

        return targets, usns, responses

    @staticmethod
    def _header(response, name):
        for line in response.split('\r\n'):
            if line.upper().startswith(name.upper() + ':'):
                return line.split(':', 1)[1].strip()
        return ''

    def test_the_search_for_all_answers_with_every_search_target(self):
        targets, usns, _ = self._search('ssdp:all')

        self.assertEqual(targets, [
            SSDP_SEARCH_TARGET,
            MEDIA_RENDERER_DEVICE_TYPE,
            AVTRANSPORT_SERVICE_TYPE,
            RENDERINGCONTROL_SERVICE_TYPE,
            CONNECTIONMANAGER_SERVICE_TYPE,
        ])
        self.assertEqual(usns[2], 'uuid:1234::' + AVTRANSPORT_SERVICE_TYPE)

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

    def test_the_search_for_the_root_device_answers_with_every_target(self):
        targets, _, _ = self._search('upnp:rootdevice')

        self.assertIn('upnp:rootdevice', targets)
        self.assertIn(AVTRANSPORT_SERVICE_TYPE, targets)

    def test_every_response_has_a_location(self):
        _, _, responses = self._search('ssdp:all')

        for response in responses:
            self.assertIn('LOCATION: http://192.168.178.128:49443/description/1234.xml', response)
            self.assertIn('HTTP/1.1 200 OK', response)

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
