import socket
import unittest

from castnavidrome.upnp.renderer import MediaRenderer
from castnavidrome.upnp.server import RendererServer


class FakeController:
    def __init__(self):
        self.calls = []

    def play(self, renderer, track=None):
        self.calls.append(('play', track))

    def pause(self, renderer):
        self.calls.append(('pause',))

    def stop(self, renderer):
        self.calls.append(('stop',))

    def next(self, renderer):
        self.calls.append(('next',))

    def previous(self, renderer):
        self.calls.append(('previous',))

    def set_volume(self, renderer, volume=0):
        self.calls.append(('set_volume', volume))

    def resolve_track(self, renderer):
        return {}

    def resolve_queue(self, renderer):
        return []

    def report_now_playing(self, renderer, track=None):
        self.calls.append(('report_now_playing', track))


BODY = (
    '<?xml version="1.0"?>'
    '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
    '<s:Body><u:GetTransportInfo xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
    '<InstanceID>0</InstanceID>'
    '</u:GetTransportInfo></s:Body></s:Envelope>'
)


def build_request(body: str, chunked: bool) -> bytes:
    payload = body.encode('utf-8')

    headers = [
        'POST /control/AVTransport/1234 HTTP/1.1',
        'Host: 127.0.0.1',
        'SOAPAction: "urn:schemas-upnp-org:service:AVTransport:1#GetTransportInfo"',
        'Content-Type: text/xml',
    ]

    if chunked:
        headers.append('Transfer-Encoding: chunked')
        payload = (f'{len(payload):x}\r\n'.encode('utf-8') + payload
                   + b'\r\n0\r\n\r\n')
    else:
        headers.append(f'Content-Length: {len(payload)}')

    return ('\r\n'.join(headers) + '\r\n\r\n').encode('utf-8') + payload


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.controller = FakeController()
        self.renderer = MediaRenderer('uuid:1234', 'Echo Dot', {'name': 'Echo Dot', 'online': True},
                                       self.controller)
        self.server = RendererServer(port=0, advertise_host='127.0.0.1')
        self.server.add_renderer(self.renderer)
        self.server.start()
        self.addCleanup(self.server.stop)

    def _post(self, chunked: bool) -> bytes:
        with socket.create_connection(('127.0.0.1', self.server.port), timeout=5) as connection:
            connection.sendall(build_request(BODY, chunked))

            data = b''

            while b'</s:Envelope>' not in data:
                part = connection.recv(65536)

                if not part:
                    break

                data += part

        return data

    def test_a_request_with_a_content_length_is_handled(self):
        response = self._post(chunked=False)

        self.assertIn(b'200 OK', response.split(b'\r\n')[0])
        self.assertIn(b'GetTransportInfoResponse', response)

    def test_a_chunked_request_is_handled(self):
        # Some DLNA clients, for example the one of Supersonic, always send
        # their requests with a chunked transfer encoding, because they
        # build the body with a stream and do not know its length.
        response = self._post(chunked=True)

        self.assertIn(b'200 OK', response.split(b'\r\n')[0])
        self.assertIn(b'GetTransportInfoResponse', response)

    def test_the_client_of_the_request_is_remembered(self):
        self._post(chunked=True)

        self.assertEqual(self.renderer.client_name, 'DLNA client')


if __name__ == '__main__':
    unittest.main()
