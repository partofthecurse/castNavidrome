import unittest
from unittest.mock import MagicMock

from castnavidrome.upnp.constants import (
    AVTRANSPORT_SERVICE_TYPE,
    CONNECTIONMANAGER_SERVICE_TYPE,
    MEDIA_RENDERER_DEVICE_TYPE,
    RENDERINGCONTROL_SERVICE_TYPE,
)
from castnavidrome.upnp.ssdp import SsdpServer


class FakeRenderer:
    def __init__(self, udid='1234'):
        self.udid = udid
        self.friendly_name = 'castNavidrome: Test'


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
        self.server._socket = MagicMock()

    def _search(self, search_target):
        message = (f'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
                   f'MAN: "ssdp:discover"\r\nMX: 2\r\nST: {search_target}\r\n\r\n')

        self.server._handle_message(message, ('192.168.178.50', 49152))

        responses = [call.args[0].decode('utf-8') for call in self.server._socket.sendto.call_args_list]
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
            MEDIA_RENDERER_DEVICE_TYPE,
            AVTRANSPORT_SERVICE_TYPE,
            RENDERINGCONTROL_SERVICE_TYPE,
            CONNECTIONMANAGER_SERVICE_TYPE,
        ])
        self.assertEqual(usns[1], 'uuid:1234::' + AVTRANSPORT_SERVICE_TYPE)

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


if __name__ == '__main__':
    unittest.main()
