"""Long-lived alexapy browser proxy for Amazon sign-in capture."""

import asyncio
import logging
import os
import secrets
import tempfile
import threading
from pathlib import Path
from yarl import URL

from alexapy import AlexaLogin, AlexaProxy

from .amazon_login import DEFAULT_COOKIE_FILE, AmazonSession

logger = logging.getLogger(__name__)

DEFAULT_PROXY_PORT = 3456


class _RoutedAlexaProxy(AlexaProxy):
    """Serve alexapy's public URL through a separately routed local port."""

    def __init__(self, login, public_url, port, on_login_success=None):
        self._public_url = URL(public_url)
        super().__init__(login, public_url)
        self._port = port
        self._on_login_success = on_login_success

    def access_url(self):
        return self._public_url

    def autofill(self, items, html):
        fresh_items = dict(items)
        fresh_items['otpCode'] = self._login.get_totp_token()
        return super().autofill(fresh_items, html)

    async def test_amazon_url(self, resp, data, query):
        result = await super().test_amazon_url(resp, data, query)
        if URL(str(resp.url)).path in ('/ap/maplanding', '/spa/index.html'):
            if self._on_login_success is not None:
                await self._on_login_success()
        return result

    async def start_proxy(self, host=None, ssl_context=None):
        public_url = self._proxy_url
        await super().start_proxy(host='0.0.0.0', ssl_context=ssl_context)
        self._proxy_url = public_url


class AlexaCookieCaptureProxy:
    """Manage one alexapy proxy and its event loop for the process lifetime."""

    def __init__(self, port=None):
        self.port = int(port or os.getenv('NAVI_ALEXA_CAPTURE_PROXY_PORT', DEFAULT_PROXY_PORT))
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._loop = None
        self._thread = None
        self._login = None
        self._proxy = None
        self._public_url = None
        self._cookie_file = None

    def ensure_started(self, public_origin):
        with self._lock:
            if self._proxy is not None:
                return self._public_url

            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout=10):
                raise RuntimeError('Alexa capture proxy event loop did not start.')

            route_token = secrets.token_urlsafe(24)
            self._public_url = (
                f'{public_origin.rstrip("/")}/api/alexa/cookie/proxy/{route_token}'
            )
            future = asyncio.run_coroutine_threadsafe(
                self._start_proxy(self._public_url), self._loop
            )
            try:
                future.result(timeout=30)
            except Exception:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)
                self._thread = None
                self._loop = None
                self._public_url = None
                raise
            return self._public_url

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    async def _start_proxy(self, public_url):
        session = AmazonSession()
        self._cookie_file = session.session_file
        cookie_dir = Path(tempfile.gettempdir()) / 'castnavidrome-alexa-capture'
        cookie_dir.mkdir(parents=True, exist_ok=True)
        (cookie_dir / '.storage').mkdir(parents=True, exist_ok=True)

        login = AlexaLogin(
            url=session.alexa_url,
            email=session.user(),
            password=session.password(),
            outputpath=lambda filename: str(cookie_dir / filename),
            otp_secret=session.totp_secret(),
        )
        proxy = _RoutedAlexaProxy(
            login,
            public_url,
            self.port,
            on_login_success=self._save_after_browser_login,
        )
        await proxy.start_proxy()
        self._login = login
        self._proxy = proxy

    async def _read_cookies(self):
        cookies = {}
        if self._proxy is not None:
            cookies.update(dict(self._proxy.session.cookies.items()))
        if self._login is not None and self._login.session is not None:
            for cookie in self._login.session.cookie_jar:
                cookies[cookie.key] = cookie.value
        return cookies

    async def _stop_proxy(self):
        try:
            if self._proxy is not None:
                await self._proxy.stop_proxy()
        finally:
            if self._proxy is not None and not self._proxy.session.is_closed:
                await self._proxy.session.aclose()
            if self._login is not None:
                await self._login.close()

    def close(self):
        with self._lock:
            if self._loop is None:
                return
            future = asyncio.run_coroutine_threadsafe(self._stop_proxy(), self._loop)
            future.result(timeout=15)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning('Alexa capture proxy event loop did not stop cleanly.')
                return
            self._loop.close()
            self._loop = None
            self._thread = None
            self._login = None
            self._proxy = None
            self._public_url = None

    def cookies(self):
        if self._loop is None:
            return {}
        future = asyncio.run_coroutine_threadsafe(self._read_cookies(), self._loop)
        return future.result(timeout=10)

    def has_csrf(self):
        return any(name.lower() == 'csrf' for name in self.cookies())

    async def _validated_cookies(self):
        cookies = await self._read_cookies()
        if not any(name.lower() == 'csrf' for name in cookies):
            if not await self._login.get_csrf():
                return {}
            cookies = await self._read_cookies()
        if not any(name.lower() == 'csrf' for name in cookies):
            return {}
        if not await self._login.test_loggedin(
            cookies=cookies,
            rebuild_session=False,
        ):
            return {}
        return await self._read_cookies()

    async def _save_after_browser_login(self):
        if self._cookie_file is None:
            return 0
        try:
            cookies = await self._validated_cookies()
            if not cookies:
                logger.warning('Amazon browser login completed, but its session did not validate.')
                return 0
            count = self._write_cookie_file(self._cookie_file, cookies)
            logger.info('Saved %s validated Alexa cookies after browser login.', count)
            return count
        except Exception:
            logger.exception('Could not automatically save cookies after Amazon browser login.')
            return 0

    @staticmethod
    def _write_cookie_file(path, cookies):
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        contents = ''.join(f'{name}={value}\n' for name, value in cookies.items())
        if destination.is_file():
            try:
                if destination.read_text(encoding='utf-8') == contents:
                    os.chmod(destination, 0o600)
                    return len(cookies)
            except OSError:
                pass

        if destination.is_mount() or destination == DEFAULT_COOKIE_FILE:
            with destination.open('w', encoding='utf-8') as output:
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(destination, 0o600)
            return len(cookies)

        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f'.{destination.name}.',
            dir=destination.parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, destination)
        except Exception:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
            raise
        return len(cookies)

    def save_to_file(self, path):
        if self._loop is None:
            return 0
        future = asyncio.run_coroutine_threadsafe(self._validated_cookies(), self._loop)
        cookies = future.result(timeout=30)
        if not cookies:
            return 0
        count = self._write_cookie_file(path, cookies)
        logger.info('Validated %s Alexa cookie(s) and saved them to %s.', count, path)
        return count