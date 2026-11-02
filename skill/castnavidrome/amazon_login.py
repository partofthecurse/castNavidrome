"""Amazon sign-in via the alexapy library.

Mirrors the cookie flow of alexa_media_player: persisted cookies are loaded
and validated first; the full login (email/password/TOTP) only runs when the
cookies are no longer accepted.  Cookies are written to
``NAVI_ALEXA_COOKIE_FILE`` in the SimpleCookie ``name=value`` format that
``AlexaTextCommandClient`` expects, so no custom cookie proxy is needed.
"""

import asyncio
import logging
import os
import shutil
import tempfile
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
