"""A small SSDP implementation used to announce the media renderers."""

import email.utils
import fcntl
import logging
import random
import socket
import struct
import threading
import time

from .constants import (
    AVTRANSPORT_SERVICE_TYPE,
    CONNECTIONMANAGER_SERVICE_TYPE,
    MEDIA_RENDERER_DEVICE_TYPE,
    RENDERINGCONTROL_SERVICE_TYPE,
)

logger = logging.getLogger(__name__)

SSDP_MULTICAST_ADDRESS = '239.255.255.250'
SSDP_MULTICAST_IPV6_ADDRESS = 'ff02::c'
SSDP_SITE_LOCAL_IPV6_ADDRESS = 'ff05::c'
SSDP_MULTICAST_PORT = 1900
SSDP_PORT = 1900
SSDP_ALL = 'ssdp:all'
SSDP_ROOT_DEVICE = 'upnp:rootdevice'
SSDP_MAX_AGE = 1800
SERVER_HEADER = 'Linux/5.0 UPnP/1.1 castNavidrome/1.0'

# How many times a notification is repeated, so that a single lost UDP
# multicast packet does not hide a renderer from the clients.
SSDP_NOTIFY_COUNT = 3
SSDP_NOTIFY_DELAY = 0.4


class SsdpServer:
    """Announces the media renderers via SSDP."""

    def __init__(self, advertise_host: str = '127.0.0.1', http_port: int = 49443,
                 device_type: str = MEDIA_RENDERER_DEVICE_TYPE, port: int = SSDP_PORT) -> None:
        self.advertise_host = advertise_host
        self.http_port = http_port
        self.device_type = device_type
        self.port = port

        # The search targets the renderers answer to.  A client that searches
        # for "ssdp:all" expects one answer per target, and clients like
        # Supersonic only accept the devices that announce their AVTransport
        # service, so the services have to be announced as well.
        self.search_targets = (
            device_type,
            AVTRANSPORT_SERVICE_TYPE,
            RENDERINGCONTROL_SERVICE_TYPE,
            CONNECTIONMANAGER_SERVICE_TYPE,
        )

        self._socket = None
        self._thread = None
        self._running = False
        self._renderers = []
        self._lock = threading.Lock()
        self.on_search = None

    #
    # Renderer management
    #

    def set_renderers(self, renderers: list) -> None:
        with self._lock:
            self._renderers = list(renderers)

    def renderers(self) -> list:
        with self._lock:
            return list(self._renderers)

    #
    # Server lifecycle
    #

    def start(self) -> bool:
        """Bind the SSDP socket and start the responder thread."""

        try:
            self._socket = self._create_socket()
        except OSError as error:
            logger.error('Could not bind the SSDP socket on port %s: %s', self.port, error)
            self._socket = None
            return False

        self._running = True
        self._thread = threading.Thread(target=self._listen, name='upnp-ssdp', daemon=True)
        self._thread.start()
        logger.info('The SSDP responder is listening on port %s.', self.port)

        return True

    def stop(self) -> None:
        self._running = False

        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _create_socket(self) -> socket.socket:
        udp_socket = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Try to bind to IPv6 first, then fallback to IPv4 if needed
        try:
            udp_socket.bind(('', self.port, 0, socket.IPPROTO_IPV6))
            udp_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 4)
            udp_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 1)
        except OSError:
            # Fallback to IPv4
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_socket.bind(('', self.port))
            udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
            udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        # Join both IPv4 and IPv6 multicast groups
        group_v4 = socket.inet_aton(SSDP_MULTICAST_ADDRESS)
        group_v6 = socket.inet_pton(socket.AF_INET6, 'ff02::c')

        joined = False
        for address in self._local_addresses():
            try:
                # Try IPv4 first
                udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                      group_v4 + socket.inet_aton(address))
                joined = True
                break
            except OSError:
                try:
                    # Then try IPv6
                    udp_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP,
                                          socket.inet_pton(socket.AF_INET6, '::' + address))
                    joined = True
                    break
                except OSError as error:
                    logger.debug('Could not join the SSDP multicast group on %s: %s', address, error)

        if not joined:
            # Try both IPv4 and IPv6 fallback
            try:
                udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, group_v4 + b'\x00\x00\x00\x00')
            except OSError as error:
                logger.warning('Could not join the SSDP multicast group (IPv4): %s', error)

        udp_socket.settimeout(1)

        return udp_socket

    @staticmethod
    def _local_addresses() -> list:
        """Return the IPv4 and IPv6 addresses of all local network interfaces."""

        addresses = []

        try:
            for _, name in socket.if_nameindex():
                try:
                    # Try IPv4
                    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    try:
                        packed = fcntl.ioctl(probe.fileno(), 0x8915, struct.pack('256s', name[:15].encode()))
                        address = socket.inet_ntoa(packed[20:24])
                        if not address.startswith('127.') and address not in addresses:
                            addresses.append(address)
                    finally:
                        probe.close()

                    # Try IPv6
                    try:
                        probe6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
                        try:
                            # Get IPv6 address for the interface
                            packed6 = fcntl.ioctl(probe6.fileno(), 0x891b, struct.pack('256s', name[:15].encode()))
                            # Parse IPv6 address
                            import ipaddress
                            addr_str = packed6[:46].split(b'\x00', 1)[0].decode('utf-8', 'ignore')
                            if addr_str and not addr_str.startswith('::1') and ':' in addr_str:
                                if addr_str not in addresses:
                                    addresses.append(addr_str)
                        finally:
                            probe6.close()
                    except (OSError, AttributeError):
                        pass
                except (OSError, AttributeError):
                    pass
        except (OSError, AttributeError):
            pass

        try:
            # Also use getaddrinfo for additional addresses
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                address = info[4][0]
                if not address.startswith('127.') and address not in addresses:
                    addresses.append(address)
        except OSError:
            pass

        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET6):
                address = info[4][0]
                if address and not address.startswith('::1') and ':' in address:
                    if address not in addresses:
                        addresses.append(address)
        except OSError:
            pass

        return addresses

    def _listen(self) -> None:
        while self._running:
            try:
                data, address = self._socket.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                self._handle_message(data.decode('utf-8', 'replace'), address)
            except Exception as error:  # pragma: no cover - defensive
                logger.warning('Could not handle an SSDP message: %s', error)

    #
    # Message handling
    #

    def _handle_message(self, message: str, address) -> None:
        if not message.upper().startswith('M-SEARCH'):
            return

        headers = self._parse_headers(message)
        search_target = headers.get('st', '').strip()
        if not search_target:
            search_target = SSDP_ALL

        matches = [renderer for renderer in self.renderers() if self._matches(search_target, renderer.udid)]
        logger.debug('Received an SSDP search for %s from %s:%s, %s renderer(s) match.',
                     search_target, address[0], address[1], len(matches))
        logger.debug('The SSDP search was: %s', message.replace('\r\n', ' | '))

        try:
            mx = float(headers.get('mx', '1'))
        except (TypeError, ValueError):
            mx = 1.0
        if mx < 0:
            mx = 0.0
        if mx > 5:
            mx = 5.0

        for renderer in matches:
            for target in self._response_targets(search_target):
                if mx:
                    time.sleep(random.uniform(0, mx))
                response = self._build_search_response(target, renderer)
                logger.debug('The SSDP response is: %s', response.decode('utf-8', 'replace').replace('\r\n', ' | '))
                self._sendto(response, address)

        if self.on_search:
            try:
                self.on_search()
            except Exception as error:  # pragma: no cover - defensive
                logger.warning('The SSDP search callback failed: %s', error)

    @staticmethod
    def _parse_headers(message: str) -> dict:
        headers = {}
        for line in message.splitlines()[1:]:
            if ':' not in line:
                continue
            name, value = line.split(':', 1)
            headers[name.strip().lower()] = value.strip()
        return headers

    def _matches(self, search_target: str, udid: str) -> bool:
        target = search_target.lower()

        if target in (SSDP_ALL, SSDP_ROOT_DEVICE):
            return True

        if target == f'uuid:{udid.lower()}':
            return True

        # A client can also search for one of the services of the renderer.
        return target in {search_target.lower() for search_target in self.search_targets}

    def _response_targets(self, search_target: str) -> list:
        """Return the search targets that the renderers answer to.

        A search for "ssdp:all" is answered with one response per search
        target of the renderer, every response with its own search target in
        the ST header and its own USN.  Clients that are looking for the
        AVTransport service only, for example Supersonic, ignore the
        responses for the other targets.

        :param str search_target: The search target of the request
        :return: The search targets of the responses
        :rtype: list
        """

        target = search_target.lower()

        if target == SSDP_ALL:
            return [SSDP_ROOT_DEVICE] + list(self.search_targets)

        if target == SSDP_ROOT_DEVICE:
            return [SSDP_ROOT_DEVICE] + list(self.search_targets)

        return [search_target]

    def _build_search_response(self, search_target: str, renderer) -> bytes:
        location = f'http://{self.advertise_host}:{self.http_port}/description/{renderer.udid}.xml'

        if search_target.lower().startswith('uuid:'):
            usn = f'uuid:{self._udid(renderer.udid)}'
        else:
            usn = f'uuid:{self._udid(renderer.udid)}::{search_target}'

        lines = [
            'HTTP/1.1 200 OK',
            f'CACHE-CONTROL: max-age={SSDP_MAX_AGE}',
            f'DATE: {email.utils.formatdate(usegmt=True)}',
            'EXT:',
            f'LOCATION: {location}',
            'OPT: "http://schemas.upnp.org/upnp/1/0/"; ns=01',
            f'SERVER: {SERVER_HEADER}',
            f'ST: {search_target}',
            f'USN: {usn}',
            '',
            '',
        ]

        return '\r\n'.join(lines).encode('utf-8')

    def _sendto(self, payload: bytes, address) -> None:
        if not self._socket:
            return

        try:
            if self._socket.family == socket.AF_INET6:
                # IPv6 socket
                dest_addr = address
                if address[0] and '.' in address[0] and ':' not in address[0]:
                    # IPv4 address
                    dest_addr = (f'::ffff:{address[0]}', address[1])
                self._socket.sendto(payload, dest_addr)
            else:
                # IPv4 socket
                self._socket.sendto(payload, address)
        except OSError as error:
            logger.debug('Could not send the SSDP response to %s: %s', address, error)

    #
    # Announcements
    #

    def announce(self, count: int = SSDP_NOTIFY_COUNT, delay: float = SSDP_NOTIFY_DELAY) -> None:
        """Send the ssdp:alive notifications for all known renderers.

        Every notification is repeated ``count`` times with ``delay`` seconds
        between the repetitions, so that a single lost UDP multicast packet
        does not hide a renderer from the clients.

        :param int count: The number of times every notification is repeated
        :param float delay: The seconds to wait between two repetitions
        """

        for _ in range(max(1, count)):
            for renderer in self.renderers():
                for target in [SSDP_ROOT_DEVICE] + list(self.search_targets):
                    payload = self._build_notify(renderer, 'ssdp:alive', target)
                    # Send to both IPv4 and IPv6 multicast addresses
                    self._sendto(payload, (SSDP_MULTICAST_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_MULTICAST_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_SITE_LOCAL_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
            time.sleep(delay)

    def announce_byebye(self, count: int = SSDP_NOTIFY_COUNT, delay: float = SSDP_NOTIFY_DELAY) -> None:
        """Send the ssdp:byebye notifications for all known renderers.

        Every notification is repeated ``count`` times with ``delay`` seconds
        between the repetitions, so that the clients reliably remove the
        renderers from their cache.

        :param int count: The number of times every notification is repeated
        :param float delay: The seconds to wait between two repetitions
        """

        for _ in range(max(1, count)):
            for renderer in self.renderers():
                for target in [SSDP_ROOT_DEVICE] + list(self.search_targets):
                    payload = self._build_notify(renderer, 'ssdp:byebye', target)
                    # Send to both IPv4 and IPv6 multicast addresses
                    self._sendto(payload, (SSDP_MULTICAST_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_MULTICAST_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_SITE_LOCAL_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
            time.sleep(delay)

    def _build_notify(self, renderer, notification_subtype: str, notify_type: str) -> bytes:
        location = f'http://{self.advertise_host}:{self.http_port}/description/{renderer.udid}.xml'

        lines = [
            'NOTIFY * HTTP/1.1',
            f'HOST: {SSDP_MULTICAST_ADDRESS}:{SSDP_MULTICAST_PORT}; ipv6:[{SSDP_MULTICAST_IPV6_ADDRESS}]:{SSDP_MULTICAST_PORT}; ipv6site:[{SSDP_SITE_LOCAL_IPV6_ADDRESS}]:{SSDP_MULTICAST_PORT}',
            f'CACHE-CONTROL: max-age={SSDP_MAX_AGE}',
            f'LOCATION: {location}',
            f'NT: {notify_type}',
            f'NTS: {notification_subtype}',
            f'SERVER: {SERVER_HEADER}',
            f'USN: uuid:{self._udid(renderer.udid)}::{notify_type}',
            '',
            '',
        ]

        return '\r\n'.join(lines).encode('utf-8')

    @staticmethod
    def _udid(udid: str) -> str:
        return udid[5:] if udid.startswith('uuid:') else udid
