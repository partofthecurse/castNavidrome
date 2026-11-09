"""Associate skill device IDs with renderer IDs through recent playback requests."""

import os
import json
import socket
import socketserver
import sqlite3
import stat
import threading
import time
from contextlib import closing

DEFAULT_BRIDGE_PATH = '/var/lib/castnavidrome/renderer-bridge.sqlite3'
PENDING_SECONDS = 30
PLAYBACK_EVENTS = ('started', 'stopped')


class RendererBridge:
    def __init__(self, path=None):
        self.path = path or os.getenv('NAVI_RENDERER_BRIDGE_PATH', DEFAULT_BRIDGE_PATH)

    def _connect(self):
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(self.path, timeout=1)
        connection.execute('CREATE TABLE IF NOT EXISTS pending '
                           '(renderer TEXT PRIMARY KEY, track TEXT NOT NULL, created REAL NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS bindings '
                           '(device TEXT PRIMARY KEY, renderer TEXT UNIQUE NOT NULL)')
        return connection

    def register_start(self, renderer: str, track: str) -> None:
        if not renderer or not track:
            return
        with closing(self._connect()) as connection, connection:
            connection.execute('INSERT OR REPLACE INTO pending VALUES (?, ?, ?)',
                               (renderer, str(track), time.time()))

    def cancel_start(self, renderer: str, track: str) -> None:
        if not renderer or not track:
            return
        with closing(self._connect()) as connection, connection:
            connection.execute('DELETE FROM pending WHERE renderer = ? AND track = ?',
                               (renderer, str(track)))

    def bind_start(self, device: str, track: str) -> bool:
        if not device or device == 'default' or not track:
            return False
        with closing(self._connect()) as connection, connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DELETE FROM pending WHERE created < ?', (time.time() - PENDING_SECONDS,))
            matches = connection.execute('SELECT renderer FROM pending WHERE track = ?', (str(track),)).fetchall()
            connection.execute('DELETE FROM bindings WHERE device = ?', (device,))
            if len(matches) != 1:
                return False
            renderer = matches[0][0]
            connection.execute('DELETE FROM bindings WHERE renderer = ?', (renderer,))
            connection.execute('INSERT INTO bindings VALUES (?, ?)', (device, renderer))
            connection.execute('DELETE FROM pending WHERE renderer = ?', (renderer,))
            return True

    def renderer_for(self, device: str) -> str:
        if not device or device == 'default':
            return ''
        with closing(self._connect()) as connection, connection:
            row = connection.execute('SELECT renderer FROM bindings WHERE device = ?', (device,)).fetchone()
            return row[0] if row else ''

    def request_next(self, device: str, current: str, action: str, next_id: str = '') -> dict:
        renderer = self.renderer_for(device)
        if not renderer or not current or action not in ('peek', 'commit'):
            return {}
        return self._request({'renderer': renderer, 'current': current, 'action': action,
                              'next': next_id})

    def notify_playback(self, device: str, event: str, token: str, offset_ms: int = 0,
                        controlled: bool = True) -> dict:
        """Tell the renderer of a device what the skill learned about the playback.

        The skill is the only component that Alexa informs when the playback
        stops or when the skill is left, for example after "Alexa, stop" or
        when another audio source takes over the Echo.  The renderer forwards
        that change to its DLNA clients.
        """
        renderer = self.renderer_for(device)
        if not renderer or event not in PLAYBACK_EVENTS:
            return {}
        try:
            offset = max(0, int(offset_ms or 0))
        except (TypeError, ValueError):
            offset = 0
        return self._request({'renderer': renderer, 'action': 'event', 'event': event,
                              'current': str(token or ''), 'offset': offset,
                              'controlled': bool(controlled)})

    def _request(self, payload: dict) -> dict:
        request = json.dumps(payload).encode('utf-8') + b'\n'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(self.path + '.sock')
            connection.sendall(request)
            with connection.makefile('rb') as response:
                result = json.loads(response.readline(4097))
        return result if isinstance(result, dict) else {}


class _BridgeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.connection.settimeout(2)
            request = json.loads(self.rfile.readline(4097))
            if not isinstance(request, dict):
                return
            response = self.server.callback(request)
            self.wfile.write(json.dumps(response or {}).encode('utf-8') + b'\n')
        except (ValueError, OSError):
            return


class _UnixBridgeServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class RendererBridgeServer:
    def __init__(self, bridge, callback):
        self.path = bridge.path + '.sock'
        self.callback = callback
        self.server = None
        self.thread = None
        self.socket_inode = None

    def start(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        if os.path.lexists(self.path):
            info = os.lstat(self.path)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise OSError('The renderer bridge socket path is not a trusted socket.')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                try:
                    probe.connect(self.path)
                except (ConnectionRefusedError, FileNotFoundError):
                    pass
                else:
                    raise OSError('The renderer bridge socket is already in use.')
            os.unlink(self.path)
        self.server = _UnixBridgeServer(self.path, _BridgeHandler)
        os.chmod(self.path, 0o600)
        self.socket_inode = os.lstat(self.path).st_ino
        self.server.callback = self.callback
        self.thread = threading.Thread(target=self.server.serve_forever, name='renderer-bridge', daemon=True)
        self.thread.start()

    def stop(self):
        if self.server is None:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server = None
        try:
            info = os.lstat(self.path)
            if stat.S_ISSOCK(info.st_mode) and info.st_ino == self.socket_inode:
                os.unlink(self.path)
        except FileNotFoundError:
            pass