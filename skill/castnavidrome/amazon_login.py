"""Amazon sign-in with username, password and TOTP/2FA.

Replaces the manual cookie copy flow.  Credentials and the TOTP secret are
read only from environment variables or Docker secrets and are never logged.
The TOTP implementation uses the standard library only (no pyotp dependency).
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import time
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

logger = logging.getLogger(__name__)

ENV_USER = 'NAVI_AMAZON_USER'
ENV_PASS = 'NAVI_AMAZON_PASS'
ENV_TOTP_SECRET = 'NAVI_AMAZON_TOTP_SECRET'
ENV_DOMAIN = 'NAVI_ALEXA_DOMAIN'
ENV_SESSION_FILE = 'NAVI_AMAZON_SESSION_FILE'

SECRETS_DIR = Path('/run/secrets')
DEFAULT_SESSION_FILE = Path('/var/lib/castnavidrome/amazon_session.json')

# Re-login before the session cookie expires.
SESSION_TTL_SECONDS = 12 * 60 * 60
# How many times a request may trigger a re-login before giving up.
RELOGIN_ATTEMPTS = 1

# Time step (seconds) and code length for the standard TOTP algorithm (RFC 6238).
TOTP_STEP = 30
TOTP_DIGITS = 6

# Amazon sign-in endpoints, parameterised by the Alexa domain.
SIGNIN_HOST = 'www.amazon.{domain}'
SIGNIN_PATH = '/ap/signin'


class AmazonLoginError(RuntimeError):
    """Base error for the Amazon login flow."""


class AmazonCredentialsMissing(AmazonLoginError):
    """Raised when username, password or the TOTP secret are not configured."""


class AmazonCaptchaError(AmazonLoginError):
    """Raised when Amazon shows a CAPTCHA that cannot be solved automatically."""


class AmazonChallengeError(AmazonLoginError):
    """Raised when Amazon asks for an additional verification step."""


class AmazonSession:
    """Holds an authenticated Amazon session and refreshes it automatically.

    Credentials and the TOTP secret are taken from environment variables or
    Docker secrets.  Session cookies are persisted to a JSON file so that the
    container can restart without a new sign-in.  On 401/403 responses the
    session is re-established once and the request is retried.
    """

    def __init__(self, domain=None, session_file=None, timeout=30, opener=None) -> None:
        raw_domain = domain or os.getenv(ENV_DOMAIN, 'amazon.com')
        # Accept both 'com'/'de' and 'amazon.com'/'amazon.de' forms.
        self.domain = raw_domain.split('amazon.')[-1] if 'amazon.' in raw_domain else raw_domain
        self.session_file = Path(session_file or os.getenv(ENV_SESSION_FILE,
                                                          str(DEFAULT_SESSION_FILE)))
        self.timeout = timeout
        self.jar = CookieJar()
        self.opener = opener or build_opener(HTTPCookieProcessor(self.jar))
        self.cookies = {}
        self.expires_at = 0.0

    #
    # Credentials (env var first, then Docker secret file, never logged)
    #

    def _credential(self, name: str):
        """Return a secret from an env var or a Docker secret file.

        Environment variables take precedence over mounted secret files.
        """
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
    # TOTP (RFC 6238, standard library only)
    #

    @staticmethod
    def totp_code(secret: str) -> str:
        """Return the current 6-digit TOTP code for a base32 secret."""
        try:
            key = base64.b32decode(secret.upper().replace(' ', ''), casefold=True)
        except Exception as error:
            raise AmazonLoginError('The TOTP secret is not valid base32.') from error
        counter = struct.pack('>q', int(time.time()) // TOTP_STEP)
        digest = hmac.new(key, counter, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        binary = (digest[offset] & 0x7F) << 24 | (digest[offset + 1] & 0xFF) << 16 | \
                 (digest[offset + 2] & 0xFF) << 8 | (digest[offset + 3] & 0xFF)
        return f'{binary % (10 ** TOTP_DIGITS):0{TOTP_DIGITS}d}'

    #
    # Persistence
    #

    def save(self) -> None:
        """Persist cookies and the expiry to the session file."""
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'domain': self.domain,
            'cookies': dict(self.cookies),
            'expires_at': self.expires_at,
        }
        tmp = self.session_file.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        tmp.replace(self.session_file)
        try:
            os.chmod(self.session_file, 0o600)
        except OSError:
            pass

    def load(self) -> bool:
        """Load cookies from the session file.  Returns True when usable."""
        if not self.session_file.is_file():
            return False
        try:
            data = json.loads(self.session_file.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return False
        if data.get('domain') != self.domain:
            return False
        cookies = data.get('cookies') or {}
        if not cookies:
            return False
        if data.get('expires_at', 0) <= time.time():
            return False
        self.cookies = cookies
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        for name, value in cookies.items():
            self.jar.set_cookie(Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain='.amazon.' + self.domain, domain_specified=True, domain_initial_dot=False,
                path='/', path_specified=True, secure=True, expires=None, discard=False,
                comment=None, comment_url=None, rest={'HttpOnly': None}, rfc2109=False,
            ))
        self.expires_at = float(data.get('expires_at', 0))
        return True

    def clear(self) -> None:
        """Drop the in-memory and persisted session."""
        self.cookies = {}
        self.expires_at = 0.0
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        try:
            if self.session_file.is_file():
                self.session_file.unlink()
        except OSError:
            pass

    #
    # Low-level requests
    #

    @property
    def csrf(self):
        return self.cookies.get('csrf')

    def _sync_cookies(self) -> None:
        """Refresh the cookie dict from the cookie jar."""
        self.cookies = {}
        for cookie in self.jar:
            self.cookies[cookie.name] = cookie.value

    @staticmethod
    def _is_captcha(body: bytes, url: str = '') -> bool:
        text = (url + ' ' + (body.decode('utf-8', 'ignore') or '')).lower()
        return ('captcha' in text or 'enter the characters' in text or
                'api.captcha-amazon' in text or 'captcha.amazon' in text)

    @staticmethod
    def _is_challenge(body: bytes) -> bool:
        text = body.decode('utf-8', 'ignore') or ''
        low = text.lower()
        return any(marker in low for marker in (
            'additional verification', 'verify your identity', 'otp', 'two-step',
            'two-step verification', 'security code',
        )) and 'sign-in' in low

    @staticmethod
    def _extract(html, pattern: str):
        if isinstance(html, bytes):
            html = html.decode('utf-8', 'ignore')
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        return match.group(1) if match else None

    def _raw_request(self, url: str, data: bytes = None, headers: dict = None) -> bytes:
        """Perform one HTTP request and sync cookies.

        Raises AmazonCaptchaError on CAPTCHA pages and AmazonLoginError on
        connection problems.
        """
        request_headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0 Safari/537.36'),
            'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
            'Accept-Language': 'de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        if headers:
            request_headers.update(headers)
        request = Request(url, data=data, headers=request_headers,
                          method='POST' if data is not None else 'GET')
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read()
        except HTTPError as error:
            body = b''
            try:
                body = error.read()
            except Exception:
                pass
            if self._is_captcha(body, url):
                raise AmazonCaptchaError(
                    'Amazon shows a CAPTCHA page that cannot be solved automatically. '
                    'Disable NAVI_AMAZON_USER and use NAVI_ALEXA_COOKIE_FILE instead.'
                ) from None
            logger.error('Amazon returned HTTP %s for %s.', error.code, url)
            raise AmazonLoginError(f'Amazon returned HTTP {error.code}.') from None
        except URLError as error:
            raise AmazonLoginError(f'Could not reach Amazon: {error}') from None

        if self._is_captcha(body, url):
            raise AmazonCaptchaError(
                'Amazon shows a CAPTCHA page that cannot be solved automatically. '
                'Disable NAVI_AMAZON_USER and use NAVI_ALEXA_COOKIE_FILE instead.'
            ) from None
        self._sync_cookies()
        return body

    def request(self, url: str, data: bytes = None, headers: dict = None,
                attempts: int = 0) -> bytes:
        """Perform an authenticated request with automatic re-login on 401/403."""
        self.ensure_session()
        try:
            return self._raw_request(url, data, headers)
        except HTTPError as error:
            if error.code in (401, 403) and attempts < RELOGIN_ATTEMPTS:
                logger.warning('Amazon session expired (HTTP %s), re-logging in.', error.code)
                self.login()
                return self.request(url, data=data, headers=headers, attempts=attempts + 1)
            logger.error('Amazon returned HTTP %s for %s.', error.code, url)
            raise AmazonLoginError(f'Amazon returned HTTP {error.code}.') from None

    #
    # Sign-in flow
    #

    def ensure_session(self) -> None:
        """Load a valid session or sign in."""
        if self.cookies and time.time() < self.expires_at:
            return
        if self.load():
            return
        self.login()

    def login(self) -> None:
        """Sign in with username, password and TOTP.

        The flow is best-effort: Amazon's markup changes frequently.  When a
        CAPTCHA or an unsupported additional verification step is encountered,
        a clear error is raised so the caller can fall back to the cookie file.
        """
        user = self.user()
        password = self.password()
        if not user or not password:
            raise AmazonCredentialsMissing(
                f'Set {ENV_USER} and {ENV_PASS} (env var or Docker secret) to log in to Amazon.'
            )

        domain = self.domain
        signin = f'https://{SIGNIN_HOST.format(domain=domain)}{SIGNIN_PATH}'
        params = {
            'openid.mode': 'checkid_setup',
            'openid.return_to': f'https://www.amazon.{domain}/',
            'openid.assoc_handle': 'deflex',
            'openid.ns': 'http://specs.openid.net/auth/2.0',
            'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select',
            'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select',
        }
        html = self._raw_request(signin + '?' + urlencode(params))

        app_action_key = self._extract(html, r'name="appActionKey"\s*value="([^"]+)"')
        workflow_state = self._extract(html, r'name="workflowState"\s*value="([^"]+)"')
        openid = {}
        for key in ('openid.claimed_id', 'openid.identity', 'openid.ns.pape',
                    'openid.pape.max_auth_age'):
            value = self._extract(html, rf'name="{key}"\s*value="([^"]*)"')
            if value:
                openid[key] = value

        # Step 1: submit the email address.
        form = {
            'email': user,
            'appActionKey': app_action_key or '',
            'workflowState': workflow_state or '',
        }
        form.update(openid)
        body = self._raw_request(signin, data=urlencode(form).encode('utf-8'),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})

        low = body.decode('utf-8', 'ignore') or ''
        if 'password' not in low.lower() and 'continue' not in low.lower():
            if self._is_challenge(body):
                raise AmazonChallengeError(
                    'Amazon requests an additional verification step (e.g. SMS or e-mail code) '
                    'that cannot be solved automatically. Use NAVI_ALEXA_COOKIE_FILE instead.'
                )

        # Step 2: submit the password.
        password_fields = {}
        for name in ('password', 'appActionKey', 'workflowState'):
            value = self._extract(low, rf'name="{name}"\s*value="([^"]*)"')
            if value is not None:
                password_fields[name] = value if name != 'password' else password
        if 'password' not in password_fields:
            password_fields['password'] = password
        password_fields.update({k: v for k, v in openid.items() if k not in password_fields})
        body = self._raw_request(signin, data=urlencode(password_fields).encode('utf-8'),
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})

        low = body.decode('utf-8', 'ignore') or ''
        if 'totp' in low.lower() or 'verification code' in low.lower():
            # Step 3: submit the TOTP code when Amazon asks for it.
            if not self.totp_secret():
                raise AmazonCredentialsMissing(
                    f'Amazon requires TOTP/2FA. Set {ENV_TOTP_SECRET} (env var or Docker secret).'
                )
            code = self.totp_code(self.totp_secret())
            logger.info('Generated Amazon 2FA code: %s', code)
            totp_fields = {}
            for name in ('totpCode', 'appActionKey', 'workflowState'):
                value = self._extract(low, rf'name="{name}"\s*value="([^"]*)"')
                if value is not None:
                    totp_fields[name] = value if name != 'totpCode' else code
            totp_fields.setdefault('totpCode', code)
            self._raw_request(signin, data=urlencode(totp_fields).encode('utf-8'),
                              headers={'Content-Type': 'application/x-www-form-urlencoded'})

        self._sync_cookies()
        if not self.cookies:
            raise AmazonLoginError('Amazon sign-in succeeded but no session cookies were set.')

        self.expires_at = time.time() + SESSION_TTL_SECONDS
        self.save()
        logger.info('Amazon session for %s established and stored.', self.domain)
