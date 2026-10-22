"""The HTTP server that hosts the UPnP descriptions, controls and events."""

import logging
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .constants import (
    AVTRANSPORT_SERVICE_TYPE,
    CONNECTIONMANAGER_SERVICE_TYPE,
    RENDERINGCONTROL_SERVICE_TYPE,
)
from .description import (
    SERVICES,
    build_device_description,
    build_scpd,
    description_path,
)
from .soap import SoapError, build_soap_fault, build_soap_response, parse_soap_request

logger = logging.getLogger(__name__)

SERVICE_TYPES = {
    'AVTransport': AVTRANSPORT_SERVICE_TYPE,
    'RenderingControl': RENDERINGCONTROL_SERVICE_TYPE,
    'ConnectionManager': CONNECTIONMANAGER_SERVICE_TYPE,
}

# The actions that drive the playback.  Only they change the client that
# the renderer attributes the playback to, the actions that only read the
# state do not.
CLIENT_ACTIONS = {
    'GetTransportInfo',
    'SetAVTransportURI',
    'SetNextAVTransportURI',
    'Play',
    'Pause',
    'Stop',
    'Next',
    'Previous',
}

SERVER_HEADER = 'Linux/5.0 UPnP/1.1 castNavidrome/1.0'


def _action_table(renderer) -> dict:
    """Return the callable of every supported SOAP action of a renderer."""

    return {
        'AVTransport': {
            'Play': lambda request: renderer.play(request.argument('Speed', '1')),
            'Pause': lambda request: renderer.pause(),
            'Stop': lambda request: renderer.stop(),
            'SetAVTransportURI': lambda request: renderer.set_av_transport_uri(
                request.argument('CurrentURI'), request.argument('CurrentURIMetaData')),
            'SetNextAVTransportURI': lambda request: renderer.set_next_av_transport_uri(
                request.argument('NextURI'), request.argument('NextURIMetaData')),
            'GetMediaInfo': lambda request: renderer.get_media_info(),
            'GetTransportInfo': lambda request: renderer.get_transport_info(),
            'GetPositionInfo': lambda request: renderer.get_position_info(),
            'GetDeviceCapabilities': lambda request: renderer.get_device_capabilities(),
            'GetCurrentTransportActions': lambda request: renderer.get_current_transport_actions(),
            'GetTransportSettings': lambda request: renderer.get_transport_settings(),
            'SetPlayMode': lambda request: renderer.set_play_mode(request.argument('NewPlayMode', 'NORMAL')),
            'Seek': lambda request: renderer.seek(request.argument('Unit'), request.argument('Target')),
            'Next': lambda request: renderer.next(),
            'Previous': lambda request: renderer.previous(),
        },
        'RenderingControl': {
            'GetVolume': lambda request: renderer.get_volume(request.argument('Channel', 'Master')),
            'SetVolume': lambda request: renderer.set_volume(
                request.argument('DesiredVolume'), request.argument('Channel', 'Master')),
            'GetMute': lambda request: renderer.get_mute(request.argument('Channel', 'Master')),
            'SetMute': lambda request: renderer.set_mute(
                request.argument('DesiredMute'), request.argument('Channel', 'Master')),
            'GetVolumeDB': lambda request: renderer.get_volume_db(request.argument('Channel', 'Master')),
            'SetVolumeDB': lambda request: renderer.set_volume_db(
                request.argument('DesiredVolume'), request.argument('Channel', 'Master')),
            'GetVolumeRange': lambda request: renderer.get_volume_range(request.argument('Channel', 'Master')),
        },
        'ConnectionManager': {
            'GetProtocolInfo': lambda request: renderer.get_protocol_info(),
            'GetCurrentConnectionIDs': lambda request: renderer.get_current_connection_ids(),
            'GetCurrentConnectionInfo': lambda request: renderer.get_current_connection_info(
                request.argument('ConnectionID', '0')),
            'PrepareForConnection': lambda request: renderer.prepare_for_connection(
                request.argument('RemoteProtocolInfo'), request.argument('PeerConnectionManager'),
                request.argument('PeerConnectionID', '-1'), request.argument('Direction', 'Input')),
            'ConnectionComplete': lambda request: renderer.connection_complete(
                request.argument('ConnectionID', '0')),
        },
    }


class RendererRequestHandler(BaseHTTPRequestHandler):
    """Handles the HTTP requests of the UPnP media renderers."""

    protocol_version = 'HTTP/1.1'
    server_version = SERVER_HEADER
    sys_version = ''

    def log_message(self, format, *args):  # noqa: A002 - signature of the base class
        logger.debug('%s - %s', self.address_string(), format % args)

    #
    # Helpers
    #

    def _send(self, status: int, body: bytes = b'', content_type: str = 'text/xml; charset="utf-8"',
              headers: dict = None) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Server', SERVER_HEADER)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()

        if body and self.command != 'HEAD':
            self.wfile.write(body)

    def _not_found(self, message: str = 'Not found') -> None:
        self._send(404, message.encode('utf-8'), 'text/plain; charset="utf-8"')

    def _read_body(self) -> bytes:
        """Read the body of the request

        A body that is sent with a chunked transfer encoding is read
        chunk by chunk.  Some clients, for example the DLNA library of
        Supersonic, always send their requests that way, because they
        build the body with a stream and do not know its length in
        advance.

        :return: The body of the request
        :rtype: bytes
        """

        encoding = (self.headers.get('Transfer-Encoding') or '').lower()

        if 'chunked' in encoding:
            return self._read_chunked_body()

        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0

        return self.rfile.read(length) if length else b''

    def _read_chunked_body(self) -> bytes:
        """Read a body that is sent with a chunked transfer encoding."""

        chunks = []

        while True:
            line = self.rfile.readline(65536).strip()

            if not line:
                break

            try:
                size = int(line.split(b';', 1)[0], 16)
            except ValueError:
                logger.warning('The chunked request has an invalid chunk size.')
                break

            if size == 0:
                # the last chunk is followed by an optional trailer
                while True:
                    trailer = self.rfile.readline(65536)

                    if trailer in (b'', b'\r\n', b'\n'):
                        break

                break

            chunks.append(self.rfile.read(size))

            # the data of a chunk is followed by a line break
            self.rfile.read(2)

        return b''.join(chunks)

    def _path_parts(self) -> list:
        path = urlparse(self.path).path
        return [part for part in path.split('/') if part]

    #
    # Request handling
    #

    def do_GET(self) -> None:
        parts = self._path_parts()
        server = self.server.renderer_server

        if not parts:
            self._send(200, server.build_index().encode('utf-8'), 'text/html; charset="utf-8"')
            return

        if len(parts) == 2 and parts[0] == 'description':
            renderer = server.get_renderer(parts[1].removesuffix('.xml'))
            if not renderer:
                self._not_found('Unknown renderer')
                return
            self._send(200, build_device_description(
                renderer.udid,
                renderer.friendly_name,
                serial_number=renderer.device.get('serialNumber', ''),
                presentation_url=server.presentation_url,
            ).encode('utf-8'))
            return

        if len(parts) == 3 and parts[0] == 'scpd':
            service_key = parts[1]
            if service_key not in SERVICES:
                self._not_found('Unknown service')
                return
            if not server.get_renderer(parts[2].removesuffix('.xml')):
                self._not_found('Unknown renderer')
                return
            self._send(200, build_scpd(service_key).encode('utf-8'))
            return

        self._not_found()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        parts = self._path_parts()
        server = self.server.renderer_server

        if len(parts) != 3 or parts[0] != 'control':
            self._not_found()
            return

        service_key = parts[1]
        renderer = server.get_renderer(parts[2])
        if not renderer or service_key not in SERVICES:
            self._not_found('Unknown renderer or service')
            return

        body = self._read_body()

        try:
            request = parse_soap_request(body)
        except SoapError as error:
            self._send(500, build_soap_fault(402, str(error)))
            return

        action = _action_table(renderer).get(service_key, {}).get(request.action)
        if action is None:
            self._send(500, build_soap_fault(401, f'Invalid Action: {request.action}'))
            return

        logger.debug('The action %s of the service %s is called for the renderer %s.',
                     request.action, service_key, renderer.friendly_name)

        if request.action in CLIENT_ACTIONS:
            renderer.set_client(self.headers.get('User-Agent', ''))

        try:
            result = action(request) or {}
        except SoapError as error:
            self._send(500, build_soap_fault(error.error_code, str(error)))
            return
        except Exception as error:
            logger.warning('The UPnP action %s failed: %s', request.action, error)
            self._send(500, build_soap_fault(501, str(error)))
            return

        self._send(200, build_soap_response(SERVICE_TYPES[service_key], request.action, result))

    def do_SUBSCRIBE(self) -> None:
        parts = self._path_parts()
        server = self.server.renderer_server

        if len(parts) != 3 or parts[0] != 'event':
            self._not_found()
            return

        service_key = parts[1]
        renderer = server.get_renderer(parts[2])
        if not renderer or service_key not in SERVICES:
            self._not_found('Unknown renderer or service')
            return

        callback = self.headers.get('CALLBACK', '')
        notification_type = self.headers.get('NT', '')
        sid = self.headers.get('SID', '')

        if not notification_type.startswith('upnp:event'):
            self._send(412, b'Unsupported notification type', 'text/plain; charset="utf-8"')
            return

        if sid:
            if not server.renew_subscription(renderer.udid, service_key, sid):
                self._send(412, b'Unknown subscription', 'text/plain; charset="utf-8"')
                return
            timeout = server.subscription_timeout(sid)
            self._send(200, b'', headers={'SID': sid, 'TIMEOUT': f'Second-{timeout}'})
            return

        callback_url = self._parse_callback(callback)
        if not callback_url:
            self._send(412, b'Missing or invalid CALLBACK header', 'text/plain; charset="utf-8"')
            return

        new_sid = server.add_subscription(renderer.udid, service_key, callback_url)
        timeout = server.subscription_timeout(new_sid)

        logger.info('New %s event subscription %s for %s', service_key, new_sid, renderer.friendly_name)

        self._send(200, b'', headers={'SID': new_sid, 'TIMEOUT': f'Second-{timeout}'})

        server.send_initial_event(renderer.udid, service_key, new_sid)

    def do_UNSUBSCRIBE(self) -> None:
        parts = self._path_parts()
        server = self.server.renderer_server

        if len(parts) != 3 or parts[0] != 'event':
            self._not_found()
            return

        sid = self.headers.get('SID', '')
        server.remove_subscription(sid)

        self._send(200, b'')

    @staticmethod
    def _parse_callback(header: str) -> str:
        if not header:
            return ''

        value = header.strip()
        if value.startswith('<'):
            value = value[1:]
        if value.endswith('>'):
            value = value[:-1]

        for candidate in value.split():
            if candidate.startswith('http://') or candidate.startswith('https://'):
                return candidate

        return ''


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler_class, renderer_server):
        self.renderer_server = renderer_server
        super().__init__(address, handler_class)


class RendererServer:
    """Serves the UPnP endpoints of all known media renderers."""

    def __init__(self, port: int = 49443, advertise_host: str = '127.0.0.1', subscription_seconds: int = 1800) -> None:
        self.port = port
        self.advertise_host = advertise_host
        self.subscription_seconds = subscription_seconds

        self._renderers = {}
        self._subscriptions = {}
        self._lock = threading.Lock()
        self._httpd = None
        self._thread = None

    #
    # Renderer management
    #

    def add_renderer(self, renderer) -> None:
        with self._lock:
            self._renderers[renderer.udid] = renderer
        renderer.event_sink = self._send_event

    def remove_renderer(self, udid: str) -> None:
        with self._lock:
            self._renderers.pop(udid, None)
            for service_subscriptions in self._subscriptions.values():
                service_subscriptions.pop(udid, None)

    def get_renderer(self, udid: str):
        with self._lock:
            return self._renderers.get(udid)

    def renderers(self) -> list:
        with self._lock:
            return list(self._renderers.values())

    @property
    def presentation_url(self) -> str:
        return f'http://{self.advertise_host}:{self.port}/'

    def base_url(self) -> str:
        return f'http://{self.advertise_host}:{self.port}'

    def description_url(self, udid: str) -> str:
        return f'{self.base_url()}{description_path(udid)}'

    def build_index(self) -> str:
        rows = []
        for renderer in self.renderers():
            rows.append(
                f'<li><a href="{description_path(renderer.udid)}">{renderer.friendly_name}</a> '
                f'({renderer.udid})</li>'
            )

        return ('<html><head><title>castNavidrome media renderers</title></head><body>'
                '<h1>castNavidrome media renderers</h1><ul>'
                + ''.join(rows)
                + '</ul></body></html>')

    #
    # Eventing
    #

    def add_subscription(self, udid: str, service_key: str, callback_url: str) -> str:
        sid = f'uuid:{uuid.uuid4()}'

        with self._lock:
            self._subscriptions.setdefault(sid, {
                'udid': udid,
                'service': service_key,
                'callback': callback_url,
                'seq': 0,
            })

        return sid

    def renew_subscription(self, udid: str, service_key: str, sid: str) -> bool:
        with self._lock:
            subscription = self._subscriptions.get(sid)
            if not subscription:
                return False
            if subscription['udid'] != udid or subscription['service'] != service_key:
                return False
        return True

    def remove_subscription(self, sid: str) -> None:
        with self._lock:
            self._subscriptions.pop(sid, None)

    def subscription_timeout(self, sid: str) -> int:
        with self._lock:
            if sid in self._subscriptions:
                return self.subscription_seconds
        return self.subscription_seconds

    def send_initial_event(self, udid: str, service_key: str, sid: str) -> None:
        renderer = self.get_renderer(udid)
        if not renderer:
            return

        if service_key == 'AVTransport':
            body = renderer.build_avtransport_event()
        else:
            body = renderer.build_renderingcontrol_event()

        self._deliver(sid, body)

    def _send_event(self, udid: str, service_key: str, body: bytes) -> None:
        with self._lock:
            sids = [sid for sid, subscription in self._subscriptions.items()
                    if subscription['udid'] == udid and subscription['service'] == service_key]

        for sid in sids:
            self._deliver(sid, body)

    def _deliver(self, sid: str, body: bytes) -> None:
        with self._lock:
            subscription = self._subscriptions.get(sid)
            if not subscription:
                return
            subscription['seq'] += 1
            sequence = subscription['seq']
            callback_url = subscription['callback']

        request = Request(callback_url, data=body, method='NOTIFY', headers={
            'CONTENT-TYPE': 'text/xml; charset="utf-8"',
            'NT': 'upnp:event',
            'NTS': 'upnp:propchange',
            'SID': sid,
            'SEQ': str(sequence),
        })

        try:
            with urlopen(request, timeout=5) as response:
                response.read()
        except Exception as error:
            logger.warning('Could not send the UPnP event to %s: %s', callback_url, error)

    #
    # Server lifecycle
    #

    def start(self) -> None:
        self._httpd = _Server(('0.0.0.0', self.port), RendererRequestHandler, self)

        if self._httpd.server_address[1]:
            self.port = self._httpd.server_address[1]

        self._thread = threading.Thread(target=self._httpd.serve_forever, name='upnp-http', daemon=True)
        self._thread.start()
        logger.info('The UPnP renderer server is listening on %s', self.base_url())

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
