"""Amazon sign-in via the alexapy library.

Mirrors the cookie flow of alexa_media_player: persisted cookies are loaded
and validated first; the full login (email/password/TOTP) only runs when the
cookies are no longer accepted.  Cookies are written to
``NAVI_ALEXA_COOKIE_FILE`` in the SimpleCookie ``name=value`` format that
``AlexaTextCommandClient`` expects, so no custom cookie proxy is needed.
"""

import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import os
import shutil
import struct
import tempfile
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path

from alexapy import AlexaLogin
from alexapy.errors import AlexapyError

logger = logging.getLogger(__name__)

ENV_USER = 'NAVI_AMAZON_USER'
ENV_PASS = 'NAVI_AMAZON_PASS'
ENV_TOTP_SECRET = 'NAVI_AMAZON_TOTP_SECRET'
ENV_DOMAIN = 'NAVI_ALEXA_DOMAIN'
ENV_COOKIE_FILE = 'NAVI_ALEXA_COOKIE_FILE'

DEFAULT_COOKIE_FILE = Path('/run/secrets/alexa.cookies')
DEFAULT_SESSION_FILE = Path('/var/lib/castnavidrome/alexa.cookies')

SECRETS_DIR = Path('/run/secrets')

SESSION_TTL_SECONDS = 12 * 60 * 60
RENEWAL_WINDOW_SECONDS = 300
DEFAULT_AIO_LOGIN_SUBPATH = 'aioamazondevices/login.json'

REQUIRED_COOKIES = ('csrf', 'at-acbde', 'session-id', 'session-token')


def resolve_cookie_file(path=None) -> Path:
    configured = Path(path or os.getenv(ENV_COOKIE_FILE, str(DEFAULT_SESSION_FILE)))
    if not configured.is_absolute():
        configured = Path('/') / configured
    if configured.is_file() or configured == DEFAULT_COOKIE_FILE or not DEFAULT_COOKIE_FILE.is_file():
        return configured

    configured.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f'.{configured.name}.',
        dir=configured.parent,
    )
    try:
        with os.fdopen(descriptor, 'wb') as destination:
            with DEFAULT_COOKIE_FILE.open('rb') as source:
                shutil.copyfileobj(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, configured)
        logger.info('Migrated the mounted Alexa cookie file to %s.', configured)
        return configured
    except OSError as error:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        logger.warning(
            'Could not migrate the mounted Alexa cookie file to %s: %s. Using %s instead.',
            configured,
            error,
            DEFAULT_COOKIE_FILE,
        )
        return DEFAULT_COOKIE_FILE


class AmazonLoginError(RuntimeError):
    """Base error for the Amazon login flow."""


class AmazonCredentialsMissing(AmazonLoginError):
    """Raised when username, password or the TOTP secret are not configured."""


class AmazonCaptchaError(AmazonLoginError):
    """Raised when Amazon shows a CAPTCHA that cannot be solved automatically."""


class AmazonChallengeError(AmazonLoginError):
    """Raised when Amazon asks for an additional verification step."""


class AmazonSession:
    """Holds an authenticated Amazon session backed by alexapy.

    Credentials and the TOTP secret are taken from environment variables or
    Docker secrets.  Session cookies are persisted to a SimpleCookie file so
    that ``AlexaTextCommandClient`` can read them without any custom proxy.
    """

    def __init__(self, domain=None, session_file=None, timeout=30, opener=None) -> None:
        raw_domain = domain or os.getenv(ENV_DOMAIN, 'amazon.com')
        self.domain = raw_domain.split('amazon.')[-1] if 'amazon.' in raw_domain else raw_domain
        self.alexa_url = f'amazon.{self.domain}'
        self.session_file = resolve_cookie_file(session_file)
        self.timeout = timeout
        self.cookies = {}
        self.expires_at = 0.0
        self._alexa_login = None
        self._login_email = self.user()

    #
    # Credentials (env var first, then Docker secret file, never logged)
    #

    def _credential(self, name: str):
        value = os.getenv(name)
        if value:
            return value
        for candidate in (SECRETS_DIR / name, SECRETS_DIR / name.lower()):
            if candidate.is_file():
                return candidate.read_text(encoding='utf-8').strip()
        return None

    def user(self) -> str:
        return self._credential(ENV_USER) or ''

    def password(self) -> str:
        return self._credential(ENV_PASS) or ''

    def totp_secret(self) -> str:
        return self._credential(ENV_TOTP_SECRET) or ''

    #
    # Persistence (SimpleCookie name=value lines)
    #

    def save(self) -> None:
        """Persist cookies as SimpleCookie name=value lines."""
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [f'{name}={value}' for name, value in self.cookies.items()]
        try:
            self.session_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            logger.info('Cookies written to %s.', self.session_file)
        except OSError as error:
            logger.error('Could not write cookies to %s: %s', self.session_file, error)
            raise
        try:
            os.chmod(self.session_file, 0o600)
        except OSError:
            pass

    def load(self) -> bool:
        """Load cookies from the SimpleCookie file.  Returns True when usable."""
        if not self.session_file.is_file():
            return False
        try:
            cookies = {}
            for line in self.session_file.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    name, value = line.split('=', 1)
                    cookies[name.strip()] = value.strip()
        except (ValueError, OSError):
            return False
        if not cookies:
            return False
        # Need at least the csrf cookie for the Alexa Remote API.
        if not any(name.lower() == 'csrf' for name in cookies):
            return False
        self.cookies = cookies
        self.expires_at = time.time() + SESSION_TTL_SECONDS
        return True

    def clear(self) -> None:
        """Drop the in-memory and persisted session."""
        self.cookies = {}
        self.expires_at = 0.0
        try:
            if self.session_file.is_file():
                self.session_file.unlink()
        except OSError:
            pass

    #
    # alexapy-backed login
    #

    async def _async_login(self) -> None:
        """Run one alexapy login cycle (load cookies, login, persist)."""
        # alexapy schreibt seine Cookiefile in ein beschreibbares Temp-Verzeichnis,
        # da /run/secrets/ oft read-only ist oder kein atomares rename erlaubt.
        cookie_dir = Path(tempfile.gettempdir()) / f'castnavidrome-alexa-{self._login_email}'
        cookie_dir.mkdir(parents=True, exist_ok=True)
        (cookie_dir / '.storage').mkdir(parents=True, exist_ok=True)

        output_path = lambda fname: str(cookie_dir / fname)
        login = AlexaLogin(
            url=self.alexa_url,
            email=self.user(),
            password=self.password(),
            outputpath=output_path,
            otp_secret=self.totp_secret(),
        )
        self._alexa_login = login

        try:
            try:
                cookies = self.cookies
                if not cookies and self.load():
                    cookies = self.cookies
                if not cookies:
                    cookies = await login.load_cookie()

                cookie_login_ok = False
                if cookies:
                    cookie_login_ok = await login.test_loggedin(
                        cookies=cookies,
                        rebuild_session=False,
                    )
                if not cookie_login_ok:
                    if not self.user() or not self.password():
                        raise AmazonCredentialsMissing(
                            f'Set {ENV_USER} and {ENV_PASS} (env var or Docker secret) '
                            'to log in to Amazon.'
                        )
                    await login.login()
                    if not await login.test_loggedin():
                        raise AmazonLoginError('Alexa credentials did not establish an authenticated session.')
            except AlexapyError as error:
                message = str(error)
                if 'captcha' in message.lower():
                    raise AmazonCaptchaError(
                        'Amazon shows a CAPTCHA that cannot be solved automatically. '
                        'Disable NAVI_AMAZON_USER and provide cookies manually.'
                    ) from None
                if 'challenge' in message.lower() or 'verification' in message.lower():
                    raise AmazonChallengeError(
                        'Amazon requests an additional verification step. '
                        'Provide cookies manually via NAVI_ALEXA_COOKIE_FILE.'
                    ) from None
                raise AmazonLoginError(f'Alexa login failed: {error}') from None

            session = login.session
            if session is None:
                raise AmazonLoginError('Alexa login succeeded but no session was created.')

            # alexapy exposes the authenticated cookies through its aiohttp jar.
            extracted = {}

            try:
                await login.save_cookiefile()
            except Exception as error:
                logger.warning('Could not save alexapy cookiefile: %s', error)

            try:
                for cookie in session.cookie_jar:
                    extracted[cookie.key] = cookie.value
            except Exception as error:
                logger.warning('Could not read alexapy cookie jar: %s', error)

            if not extracted:
                raise AmazonLoginError('Alexa login succeeded but no session cookies were extracted.')

            self.cookies = extracted
            self.expires_at = time.time() + SESSION_TTL_SECONDS
            if not self.csrf:
                raise AmazonLoginError('Alexa login succeeded but the session has no csrf cookie.')

            self.save()
            logger.info('Amazon session for %s established via alexapy and stored.', self.domain)
        finally:
            try:
                await login.close()
            except Exception as error:
                logger.debug('Could not close alexapy session: %s', error)

    def login(self) -> None:
        """Sign in with username, password and TOTP via alexapy."""
        try:
            asyncio.run(self._async_login())
        except RuntimeError as error:
            if 'event loop' in str(error).lower():
                raise AmazonLoginError(
                    'alexapy requires an async event loop; call login() from a sync context.'
                ) from None
            raise

    #
    # Session management
    #

    @property
    def csrf(self):
        return next((value for name, value in self.cookies.items() if name.lower() == 'csrf'), None)

    def ensure_session(self) -> None:
        """Load a valid session or sign in, refreshing before expiry."""
        if self.cookies and time.time() < self.expires_at - RENEWAL_WINDOW_SECONDS:
            return
        if not self.cookies:
            self.load()
        self.login()

    def request(self, url: str, data: bytes = None, headers: dict = None,
                attempts: int = 0) -> bytes:
        """Perform an authenticated request with automatic re-login on 401/403."""
        self.ensure_session()
        import urllib.error
        import urllib.request
        request_headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0 Safari/537.36'),
            'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        if headers:
            request_headers.update(headers)
        request = urllib.request.Request(url, data=data, headers=request_headers,
                                         method='POST' if data is not None else 'GET')
        try:
            import http.cookiejar
            jar = http.cookiejar.CookieJar()
            for name, value in self.cookies.items():
                jar.set_cookie(http.cookiejar.Cookie(
                    version=0, name=name, value=value, port=None, port_specified=False,
                    domain='.amazon.' + self.domain, domain_specified=True,
                    domain_initial_dot=False, path='/', path_specified=True,
                    secure=True, expires=None, discard=False, comment=None,
                    comment_url=None, rest={'HttpOnly': None}, rfc2109=False,
                ))
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            with opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code in (401, 403) and attempts < 1:
                logger.warning('Amazon session expired (HTTP %s), re-logging in.', error.code)
                self.login()
                return self.request(url, data=data, headers=headers, attempts=attempts + 1)
            raise AmazonLoginError(f'Amazon returned HTTP {error.code}.') from None
        except urllib.error.URLError as error:
            raise AmazonLoginError(f'Could not reach Amazon: {error}') from None


class AioAmazonSession:
    """Authenticate with aioamazondevices and persist reusable login state."""

    def __init__(self, domain=None, cookie_file=None, login_data_file=None) -> None:
        self.credentials = AmazonSession(domain=domain, session_file=cookie_file)
        self.cookie_file = self.credentials.session_file
        self.login_data_file = Path(
            login_data_file or self.cookie_file.parent / DEFAULT_AIO_LOGIN_SUBPATH
        )
        self._worker_lock = threading.Lock()
        self._worker_loop = None
        self._worker_thread = None
        self._closed = False
        self._operation_lock = None
        self._shared_context = None
        self._shared_api = None
        self._shared_devices = None

    @staticmethod
    def _totp_code(secret: str, timestamp: float = None) -> str:
        value = ''.join((secret or '').split())
        key = base64.b32decode(value + '=' * (-len(value) % 8), casefold=True)
        counter = int((time.time() if timestamp is None else timestamp) // 30)
        digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
        offset = digest[-1] & 15
        code = (int.from_bytes(digest[offset:offset + 4], 'big') & 0x7fffffff) % 1000000
        return f'{code:06d}'

    def _load_login_data(self) -> dict:
        try:
            data = json.loads(self.login_data_file.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict) or not data.get('refresh_token'):
            return {}

        return data

    def _save_login_data(self, data: dict) -> None:
        destination = self.login_data_file
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        contents = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f'.{destination.name}.', dir=destination.parent, text=True,
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(contents)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, destination)
            os.chmod(destination, 0o600)
        except Exception:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
            raise

    @property
    def is_configured(self) -> bool:
        return bool(self.credentials.user() and self.credentials.password() and self.credentials.totp_secret())

    @staticmethod
    def _device_record(device, customer_id: str) -> dict:
        return {
            'name': device.account_name,
            'deviceOwnerCustomerId': device.device_owner_customer_id or customer_id or '',
            'deviceType': device.device_type,
            'deviceFamily': device.device_family,
            'serialNumber': device.serial_number,
            'online': device.online,
        }

    def _run(self, coroutine):
        try:
            return asyncio.run(coroutine)
        except RuntimeError as error:
            if 'event loop' in str(error).lower():
                raise AmazonLoginError('aioamazondevices calls must run outside an active event loop.') from None
            raise

    @asynccontextmanager
    async def _connected_api(self):
        try:
            import aiohttp
            from aioamazondevices.api import AmazonEchoApi
            from aioamazondevices.exceptions import CannotAuthenticate
            from aioamazondevices.structures import AmazonSaveDataConfig
        except ImportError as error:
            raise AmazonLoginError('aioamazondevices is not installed.') from error

        logging.getLogger('aioamazondevices').setLevel(logging.WARNING)
        login_data = self._load_login_data()
        self.login_data_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        async with aiohttp.ClientSession() as client_session:
            api = AmazonEchoApi(
                client_session,
                self.credentials.user(),
                self.credentials.password(),
                save_data=AmazonSaveDataConfig(self.login_data_file.parent),
                login_data=login_data or None,
            )

            try:
                if not login_data:
                    await api.login.login_mode_interactive(
                        self._totp_code(self.credentials.totp_secret())
                    )
                try:
                    devices = await api.get_devices_data()
                except CannotAuthenticate:
                    await api.login.login_mode_interactive(
                        self._totp_code(self.credentials.totp_secret())
                    )
                    devices = await api.get_devices_data()

                yield api, devices
            finally:
                stored_data = api._session_state_data.login_stored_data
                if stored_data:
                    self._save_login_data(stored_data)

    def ensure_session(self) -> bool:
        """Refresh or establish the Aio session; return False if not configured."""
        if not self.is_configured:
            return False

        self._run(self._async_ensure_session())
        return True

    async def _async_ensure_session(self) -> None:
        async with self._connected_api() as (_, devices):
            logger.info('AioAmazon login available for %s Alexa device(s).', len(devices))

    def list_devices(self) -> list:
        if not self.is_configured:
            raise AmazonCredentialsMissing('AioAmazon credentials are not configured.')
        return self._run_shared(self._async_list_devices)

    async def _async_list_devices(self) -> list:
        async with self._get_operation_lock():
            try:
                already_connected = self._shared_api is not None
                api, devices = await self._shared_connection()
                if already_connected:
                    devices = await api.get_devices_data()
                    self._shared_devices = devices
                customer_id = api._session_state_data.account_customer_id
                return [self._device_record(device, customer_id) for device in devices.values()]
            except Exception:
                await self._disconnect_shared()
                raise

    def send_text_command(self, device: dict, text: str, locale: str = 'en-US') -> None:
        if not self.is_configured:
            raise AmazonCredentialsMissing('AioAmazon credentials are not configured.')
        self._run_shared(self._async_send_text_command, device, text, locale)

    async def _async_send_text_command(self, device: dict, text: str, locale: str) -> None:
        async with self._get_operation_lock():
            try:
                api, devices = await self._shared_connection()
                serial = device.get('serialNumber') or ''
                target = devices.get(serial)
                if target is None:
                    devices = await api.get_devices_data()
                    self._shared_devices = devices
                    target = devices.get(serial)
                if target is None:
                    raise AmazonLoginError('The Alexa device of this renderer is unknown.')

                api._session_state_data._language = locale
                await api.call_alexa_text_command(target, text)
                pending = list(api._sequence_handler._tasks)
                if pending:
                    await asyncio.gather(*pending)
            except Exception:
                await self._disconnect_shared()
                raise

    def _run_shared(self, method, *args):
        with self._worker_lock:
            if self._closed:
                raise AmazonLoginError('The Amazon session has been closed.')
            if self._worker_loop is None:
                self._worker_loop = asyncio.new_event_loop()
                self._worker_thread = threading.Thread(
                    target=self._worker_loop.run_forever, name='alexa-command-session', daemon=True,
                )
                self._worker_thread.start()
            future = asyncio.run_coroutine_threadsafe(method(*args), self._worker_loop)
        return future.result()

    def _get_operation_lock(self):
        if self._operation_lock is None:
            self._operation_lock = asyncio.Lock()
        return self._operation_lock

    async def _shared_connection(self):
        if self._shared_api is None:
            context = self._connected_api()
            api, devices = await context.__aenter__()
            self._shared_context = context
            self._shared_api = api
            self._shared_devices = devices
        return self._shared_api, self._shared_devices

    async def _disconnect_shared(self):
        context = self._shared_context
        self._shared_context = None
        self._shared_api = None
        self._shared_devices = None
        if context is not None:
            await context.__aexit__(None, None, None)

    async def _close_shared(self):
        async with self._get_operation_lock():
            await self._disconnect_shared()

    def close(self) -> None:
        with self._worker_lock:
            if self._closed:
                return
            self._closed = True
            loop = self._worker_loop
            thread = self._worker_thread
            if loop is None:
                return
            future = asyncio.run_coroutine_threadsafe(self._close_shared(), loop)
        try:
            future.result()
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join()
            loop.close()
