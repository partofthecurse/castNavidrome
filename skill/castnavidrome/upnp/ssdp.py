"""A small SSDP implementation used to announce the media renderers."""

import email.utils
import fcntl
import logging
import os
import random
import selectors
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
SSDP_SEARCH_TARGET = 'ssdp:all'
SSDP_MAX_AGE = 1800
SERVER_HEADER = 'Linux/5.0 UPnP/1.1 castNavidrome/1.0'

# How many times a notification is repeated, so that a single lost UDP
# multicast packet does not hide a renderer from the clients.
SSDP_NOTIFY_COUNT = 3
SSDP_NOTIFY_DELAY = 0.4


class SsdpServer:
    """Announces the media renderers via SSDP."""

    def __init__(self, advertise_host: str = '127.0.0.1', http_port: int = 49443,
                 device_type: str = MEDIA_RENDERER_DEVICE_TYPE, port: int = SSDP_PORT,
                 mx: float = 0.0, notify_count: int = None, notify_delay: float = None) -> None:
        self.advertise_host = advertise_host
        self.http_port = http_port
        self.device_type = device_type
        self.port = port
        self.mx = max(0.0, float(mx))

        if notify_count is None:
            try:
                notify_count = int(os.environ.get('NAVI_ALEXA_RENDERER_NOTIFY_COUNT', str(SSDP_NOTIFY_COUNT)))
            except (TypeError, ValueError):
                notify_count = SSDP_NOTIFY_COUNT
        if notify_delay is None:
            try:
                notify_delay = float(os.environ.get('NAVI_ALEXA_RENDERER_NOTIFY_DELAY', str(SSDP_NOTIFY_DELAY)))
            except (TypeError, ValueError):
                notify_delay = SSDP_NOTIFY_DELAY

        self.notify_count = max(0, int(notify_count))
        self.notify_delay = max(0.0, float(notify_delay))

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

        self._sockets = []
        self._selector = selectors.DefaultSelector()
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
        """Bind the SSDP sockets and start the responder thread."""

        try:
            self._sockets = self._create_sockets()
        except OSError as error:
            logger.error('Could not bind the SSDP sockets on port %s: %s', self.port, error)
            self._sockets = []
            return False

        for sock in self._sockets:
            self._selector.register(sock, selectors.EVENT_READ)

        self._running = True
        self._thread = threading.Thread(target=self._listen, name='upnp-ssdp', daemon=True)
        self._thread.start()
        logger.info('The SSDP responder is listening on port %s (%d socket(s)).', self.port, len(self._sockets))

        return True

    def stop(self) -> None:
        self._running = False

        for sock in self._sockets:
            try:
                self._selector.unregister(sock)
            except (OSError, KeyError, ValueError):
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._sockets = []

    def _create_sockets(self) -> list:
        """Create IPv4 and IPv6 SSDP sockets and join the multicast groups.

        SSDP uses IPv4 multicast on 239.255.255.250 and IPv6 multicast on
        ff02::c / ff05::c.  An IPv6 socket does not receive IPv4 multicast, so
        one socket per protocol family is required.
        """
        sockets = []

        # --- IPv4 socket (239.255.255.250) ---
        try:
            v4 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            v4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            v4.bind(('', self.port))
            v4.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
            v4.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            group_v4 = socket.inet_aton(SSDP_MULTICAST_ADDRESS)
            joined = False
            for address in self._local_addresses():
                if '.' not in address:
                    continue
                try:
                    v4.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                  group_v4 + socket.inet_aton(address))
                    joined = True
                    break
                except OSError:
                    pass
            if not joined:
                try:
                    v4.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                  group_v4 + b'\x00\x00\x00\x00')
                except OSError as error:
                    logger.warning('Could not join the IPv4 SSDP multicast group: %s', error)
            sockets.append(v4)
            logger.info('IPv4 SSDP socket listening on port %s (multicast %s).', self.port, SSDP_MULTICAST_ADDRESS)
        except OSError as error:
            logger.warning('Could not create the IPv4 SSDP socket on port %s: %s', self.port, error)

        # --- IPv6 socket (ff02::c, ff05::c) ---
        try:
            v6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # IPv6-only so that the IPv4 socket can bind to port 1900 as well.
            v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            v6.bind(('', self.port, 0, socket.IPPROTO_IPV6))
            v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, 4)
            v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 1)
            joined = False
            for _, name in socket.if_nameindex():
                try:
                    index = socket.if_nametoindex(name)
                except OSError:
                    continue
                for group in (SSDP_MULTICAST_IPV6_ADDRESS, SSDP_SITE_LOCAL_IPV6_ADDRESS):
                    group_bin = socket.inet_pton(socket.AF_INET6, group)
                    mreq = group_bin + struct.pack('@I', index)
                    try:
                        v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, mreq)
                        joined = True
                    except OSError:
                        pass
            if not joined:
                logger.warning('Could not join any IPv6 SSDP multicast group.')
            sockets.append(v6)
            logger.info('IPv6 SSDP socket listening on port %s.', self.port)
        except OSError as error:
            logger.warning('Could not create the IPv6 SSDP socket on port %s: %s', self.port, error)

        if not sockets:
            raise OSError('Could not create any SSDP socket')

        return sockets

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
                events = self._selector.select(timeout=1.0)
            except OSError:
                break
            if not self._running:
                break

            for key, _mask in events:
                sock = key.fileobj
                try:
                    data, address = sock.recvfrom(2048)
                except OSError:
                    continue

                try:
                    self._handle_message(data.decode('utf-8', 'replace'), address)
                except Exception as error:  # pragma: no cover - defensive
                    logger.warning('Could not handle an SSDP message: %s', error)

    #
    # Message handling
    #

    def _handle_message(self, message: str, address) -> None:
        headers = self._parse_headers(message)
        search_target = headers.get('st', '').strip()
        if not search_target:
            search_target = SSDP_ALL

        matches = [renderer for renderer in self.renderers() if self._matches(search_target, renderer.udid)]
        logger.debug('Received an SSDP search for %s from %s:%s, %s renderer(s) match.',
                     search_target, address[0], address[1], len(matches))
        logger.debug('The SSDP search was: %s', message.replace('\\r\\n', ' | '))

        # Send responses with a random delay up to the configured MX value
        # so that bursts of M-SEARCH answers are spread out.  A value of
        # zero (the default) keeps the previous immediate behaviour.
        replies = []
        for renderer in matches:
            for target in self._response_targets(search_target):
                delay = random.uniform(0.0, self.mx) if self.mx > 0 else 0.0
                replies.append((delay, renderer, target))

        replies.sort(key=lambda item: item[0])
        last = 0.0
        for delay, renderer, target in replies:
            if delay > last:
                time.sleep(delay - last)
            last = delay
            response = self._build_search_response(target, renderer)
            logger.debug('The SSDP response is: %s', response.decode('utf-8', 'replace').replace('\\r\\n', ' | '))
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

        if target in (SSDP_ALL, SSDP_SEARCH_TARGET):
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
            return [SSDP_SEARCH_TARGET] + list(self.search_targets)

        if target == SSDP_SEARCH_TARGET:
            return [SSDP_SEARCH_TARGET] + list(self.search_targets)

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
        if not self._sockets:
            return

        host = address[0]
        if '.' in host:
            candidates = [sock for sock in self._sockets if sock.family == socket.AF_INET]
        else:
            candidates = [sock for sock in self._sockets if sock.family == socket.AF_INET6]

        if not candidates:
            return

        try:
            candidates[0].sendto(payload, address)
        except OSError as error:
            logger.debug('Could not send the SSDP response to %s: %s', address, error)

    #
    # Announcements
    #

    def announce(self, count: int = None, delay: float = None) -> None:
        """Send the ssdp:alive notifications for all known renderers."""

        if not self._sockets:
            return

        if count is None:
            count = getattr(self, 'notify_count', SSDP_NOTIFY_COUNT)
        if delay is None:
            delay = getattr(self, 'notify_delay', SSDP_NOTIFY_DELAY)

        count = max(0, int(count))
        delay = max(0.0, float(delay))

        if count == 0:
            return

        for _ in range(count):
            for renderer in self.renderers():
                for target in [SSDP_SEARCH_TARGET] + list(self.search_targets):
                    payload = self._build_notify(renderer, 'ssdp:alive', target)
                    self._sendto(payload, (SSDP_MULTICAST_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_MULTICAST_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_SITE_LOCAL_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
            if delay > 0:
                time.sleep(delay)

    def announce_byebye(self, count: int = None, delay: float = None) -> None:
        """Send the ssdp:byebye notifications for all known renderers."""

        if not self._sockets:
            return

        if count is None:
            count = getattr(self, 'notify_count', SSDP_NOTIFY_COUNT)
        if delay is None:
            delay = getattr(self, 'notify_delay', SSDP_NOTIFY_DELAY)

        count = max(0, int(count))
        delay = max(0.0, float(delay))

        if count == 0:
            return

        for _ in range(count):
            for renderer in self.renderers():
                for target in [SSDP_SEARCH_TARGET] + list(self.search_targets):
                    payload = self._build_notify(renderer, 'ssdp:byebye', target)
                    self._sendto(payload, (SSDP_MULTICAST_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_MULTICAST_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
                    self._sendto(payload, (SSDP_SITE_LOCAL_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
            if delay > 0:
                time.sleep(delay)

    def announce_byebye_for(self, renderer) -> None:
        """Sendet ssdp:byebye für einen einzelnen Renderer.

        Damit entfernen Clients den Renderer sofort aus ihrem Cache,
        anstatt bis zum Ablauf von CACHE-CONTROL max-age zu warten.
        """
        if not self.is_healthy():
            return

        for target in [SSDP_SEARCH_TARGET] + list(self.search_targets):
            payload = self._build_notify(renderer, 'ssdp:byebye', target)
            self._sendto(payload, (SSDP_MULTICAST_ADDRESS, SSDP_MULTICAST_PORT))
            self._sendto(payload, (SSDP_MULTICAST_IPV6_ADDRESS, SSDP_MULTICAST_PORT))
            self._sendto(payload, (SSDP_SITE_LOCAL_IPV6_ADDRESS, SSDP_MULTICAST_PORT))

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

    def is_healthy(self) -> bool:
        """Return True when the SSDP sockets are bound and the listener is alive."""
        return bool(self._sockets) and self._thread is not None and self._thread.is_alive()

    @staticmethod
    def _udid(udid: str) -> str:
        return udid[5:] if udid.startswith('uuid:') else udid
