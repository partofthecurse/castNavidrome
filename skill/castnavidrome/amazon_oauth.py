"""OAuth 2.0 (Login with Amazon) sign-in for castNavidrome.

Replaces the screen-scraped ``/ap/signin`` username/password/TOTP flow with the
official OAuth 2.0 Authorization Code flow, analogous to Home Assistant Skills.
The end user signs in and consents in the browser; castNavidrome exchanges the
returned authorization code for an access token and a refresh token.  Tokens are
persisted to a JSON file and refreshed automatically before they expire.  The
access token is sent as a ``Bearer`` token when the Alexa Remote API is called.

Register a "Login with Amazon" security profile in the Amazon developer console.
Required environment variables:

* NAVI_AMAZON_CLIENT_ID      - OAuth client ID
* NAVI_AMAZON_CLIENT_SECRET  - OAuth client secret
* NAVI_AMAZON_REDIRECT_URI   - redirect URI, e.g. https://host/api/alexa/amazon/callback
* NAVI_ALEXA_DOMAIN          - amazon.com / amazon.de (default: amazon.com)
* NAVI_AMAZON_TOKEN_FILE     - where tokens are persisted
* NAVI_AMAZON_SCOPES         - OAuth scopes (default: alexa::devices:all)

Client IDs and secrets are never logged.  Token files are written with mode 0600.
"""

import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .amazon_login import AmazonLoginError

logger = logging.getLogger(__name__)

ENV_CLIENT_ID = 'NAVI_AMAZON_CLIENT_ID'
ENV_CLIENT_SECRET = 'NAVI_AMAZON_CLIENT_SECRET'
ENV_REDIRECT_URI = 'NAVI_AMAZON_REDIRECT_URI'
ENV_DOMAIN = 'NAVI_ALEXA_DOMAIN'
ENV_TOKEN_FILE = 'NAVI_AMAZON_TOKEN_FILE'
ENV_SCOPES = 'NAVI_AMAZON_SCOPES'

SECRETS_DIR = Path('/run/secrets')
DEFAULT_TOKEN_FILE = Path('/var/lib/castnavidrome/amazon_oauth_token.json')

# Safety margin before the access token is considered expired.
TOKEN_LEEWAY_SECONDS = 60

DEFAULT_SCOPES = 'alexa::devices:all'

# Login with Amazon endpoints.
AUTHORIZE_HOST = 'www.amazon.{domain}'
AUTHORIZE_PATH = '/ap/oa'
TOKEN_HOST = 'api.amazon.com'
TOKEN_PATH = '/auth/o2/token'

# Alexa Remote API endpoints, parameterised by domain.
# For Europe (amazon.de/etc.): api.eu.amazonalexa.com
# For North America (amazon.com): api.amazon.com
ALEXA_API_HOST_MAP = {
    'com': 'api.amazon.com',
    'de': 'api.eu.amazonalexa.com',
}


class AmazonOAuthError(AmazonLoginError):
    """Base error for the OAuth login flow."""


class AmazonOAuthCredentialsMissing(AmazonOAuthError):
    """Raised when no OAuth client credentials or tokens are configured."""


class AmazonOAuthSession:
    """Holds OAuth access/refresh tokens and refreshes them automatically.

    The object is compatible with :class:`castnavidrome.alexa_remote.AlexaTextCommandClient`,
    which expects ``cookies``, ``csrf`` and ``request(url, data, headers)``.
    """

    def __init__(self, domain=None, token_file=None, timeout=30, opener=None) -> None:
        raw_domain = domain or os.getenv(ENV_DOMAIN, 'amazon.com')
        # Accept both 'com'/'de' and 'amazon.com'/'amazon.de' forms.
        self.domain = raw_domain.split('amazon.')[-1] if 'amazon.' in raw_domain else raw_domain
        self.token_file = Path(token_file or os.getenv(ENV_TOKEN_FILE,
                                                       str(DEFAULT_TOKEN_FILE)))
        self.timeout = timeout
        self.opener = opener or build_opener()
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0.0
        self._client_id = None
        self._client_secret = None
        self._redirect_uri = None
        self._load()

    #
    # Credentials (env var first, then Docker secret file, never logged)
    #

    def _credential(self, name: str):
        """Return a secret from an env var or a Docker secret file."""
        value = os.getenv(name)
        if value:
            return value
        for candidate in (SECRETS_DIR / name, SECRETS_DIR / name.lower()):
            if candidate.is_file():
                return candidate.read_text(encoding='utf-8').strip()
        return None

    def client_id(self) -> str:
        if self._client_id:
            return self._client_id
        return self._credential(ENV_CLIENT_ID) or ''

    def client_secret(self) -> str:
        if self._client_secret:
            return self._client_secret
        return self._credential(ENV_CLIENT_SECRET) or ''

    def redirect_uri(self) -> str:
        if self._redirect_uri:
            return self._redirect_uri
        return os.getenv(ENV_REDIRECT_URI) or ''

    def scopes(self) -> str:
        return os.getenv(ENV_SCOPES, DEFAULT_SCOPES)

    #
    # Persistence
    #

    def _load(self) -> None:
        if not self.token_file.is_file():
            return
        try:
            data = json.loads(self.token_file.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return
        if data.get('domain') != self.domain:
            return
        self.access_token = data.get('access_token') or None
        self.refresh_token = data.get('refresh_token') or None
        self.expires_at = float(data.get('expires_at', 0))

    def save(self) -> None:
        """Persist the tokens to the token file."""
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'domain': self.domain,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_at': self.expires_at,
        }
        tmp = self.token_file.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        tmp.replace(self.token_file)
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass

    def clear(self) -> None:
        """Drop the in-memory and persisted tokens."""
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0.0
        try:
            if self.token_file.is_file():
                self.token_file.unlink()
        except OSError:
            pass

    #
    # Token state
    #

    @property
    def cookies(self):
        return {}

    @property
    def csrf(self):
        return None

    def is_valid(self) -> bool:
        """True when a non-expired access token is available."""
        return bool(self.access_token) and time.time() < self.expires_at - TOKEN_LEEWAY_SECONDS

    def ensure_session(self) -> None:
        """Ensure a valid access token, refreshing if necessary."""
        if self.is_valid():
            return
        if self.refresh_token:
            self.refresh_access_token()
            return
        raise AmazonOAuthCredentialsMissing(
            'No Amazon OAuth tokens yet. Open /api/alexa/amazon/login to start the authorization flow.'
        )

    #
    # OAuth flow
    #

    def authorization_url(self, client_id=None, redirect_uri=None, scope=None, state=None):
        """Return the Login with Amazon authorization URL and a CSRF state."""
        client_id = client_id or self.client_id()
        redirect_uri = redirect_uri or self.redirect_uri()
        if not client_id or not redirect_uri:
            raise AmazonOAuthCredentialsMissing(
                'Set NAVI_AMAZON_CLIENT_ID and NAVI_AMAZON_REDIRECT_URI to start the OAuth flow.'
            )
        state = state or secrets.token_urlsafe(32)
        params = {
            'client_id': client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'state': state,
        }
        effective_scope = scope if scope is not None else self.scopes()
        if effective_scope:
            params['scope'] = effective_scope
        url = f'https://{AUTHORIZE_HOST.format(domain=self.domain)}{AUTHORIZE_PATH}?' + urlencode(params)
        return url, state

    def exchange_code_for_tokens(self, code, client_id=None, client_secret=None,
                                 redirect_uri=None) -> None:
        """Exchange an authorization code for access and refresh tokens."""
        client_id = client_id or self.client_id()
        client_secret = client_secret or self.client_secret()
        redirect_uri = redirect_uri or self.redirect_uri()
        if not client_id or not client_secret or not redirect_uri:
            raise AmazonOAuthCredentialsMissing(
                'NAVI_AMAZON_CLIENT_ID, NAVI_AMAZON_CLIENT_SECRET and NAVI_AMAZON_REDIRECT_URI are required.'
            )
        body = urlencode({
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
        }).encode('utf-8')
        data = self._token_request(body)
        self._apply_token_response(data)
        self.save()
        logger.info('Amazon OAuth tokens obtained and stored for %s.', self.domain)

    def refresh_access_token(self) -> None:
        """Refresh the access token with the refresh token."""
        if not self.refresh_token:
            raise AmazonOAuthCredentialsMissing('No refresh token available to refresh the access token.')
        body = urlencode({
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id(),
            'client_secret': self.client_secret(),
        }).encode('utf-8')
        data = self._token_request(body)
        self._apply_token_response(data)
        self.save()
        logger.info('Amazon OAuth access token refreshed for %s.', self.domain)

    def _token_request(self, body: bytes) -> dict:
        url = f'https://{TOKEN_HOST}{TOKEN_PATH}'
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=utf-8',
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0 Safari/537.36'),
        }
        try:
            raw = self._raw_request(url, data=body, headers=headers)
        except HTTPError as error:
            body_text = b''
            try:
                body_text = error.read()
            except Exception:
                pass
            logger.error('Amazon OAuth token request failed: HTTP %s %s.', error.code, body_text)
            raise AmazonOAuthError(f'Amazon OAuth token request failed (HTTP {error.code}).') from None
        try:
            return json.loads(raw.decode('utf-8', 'ignore') or '{}')
        except ValueError as error:
            raise AmazonOAuthError('Amazon OAuth token response is not valid JSON.') from None

    def _raw_request(self, url: str, data: bytes = None, headers: dict = None) -> bytes:
        request_headers = {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/124.0 Safari/537.36'),
            'Accept': 'application/json',
        }
        if headers:
            request_headers.update(headers)
        request = Request(url, data=data, headers=request_headers,
                          method='POST' if data is not None else 'GET')
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError:
            raise
        except URLError as error:
            raise AmazonOAuthError(f'Could not reach Amazon OAuth: {error}') from None

    def _apply_token_response(self, data: dict) -> None:
        access_token = data.get('access_token')
        if not access_token:
            raise AmazonOAuthError('Amazon OAuth did not return an access token.')
        self.access_token = access_token
        if data.get('refresh_token'):
            self.refresh_token = data['refresh_token']
        expires_in = data.get('expires_in')
        if expires_in is not None:
            try:
                self.expires_at = time.time() + float(expires_in) - TOKEN_LEEWAY_SECONDS
            except (TypeError, ValueError):
                self.expires_at = time.time() + 3600 - TOKEN_LEEWAY_SECONDS
        else:
            self.expires_at = time.time() + 3600 - TOKEN_LEEWAY_SECONDS

    #
    # Authenticated requests (Bearer token)
    #

    def request(self, url: str, data: bytes = None, headers: dict = None,
                attempts: int = 0) -> bytes:
        """Perform an authenticated request with a Bearer token and auto-refresh."""
        self.ensure_session()
        request_headers = dict(headers or {})
        request_headers['Authorization'] = f'Bearer {self.access_token}'
        try:
            return self._raw_request(url, data=data, headers=request_headers)
        except HTTPError as error:
            if error.code == 401 and attempts == 0 and self.refresh_token:
                logger.warning('Amazon OAuth access token expired, refreshing.')
                self.refresh_access_token()
                request_headers['Authorization'] = f'Bearer {self.access_token}'
                return self.request(url, data=data, headers=headers, attempts=attempts + 1)
            body_text = b''
            try:
                body_text = error.read()
            except Exception:
                pass
            body_preview = body_text.decode('utf-8', 'ignore')[:500] if body_text else ''
            if body_preview:
                logger.error('Amazon OAuth request failed: HTTP %s for %s. Body: %s', error.code, url, body_preview)
            else:
                logger.error('Amazon OAuth request failed: HTTP %s for %s.', error.code, url)
            if 500 <= error.code < 600:
                raise AmazonOAuthError(
                    f'Amazon server returned HTTP {error.code} for {url}. '
                    'This is an Amazon-side error (Alexa API temporarily unavailable or changed). '
                    'Please try again later.'
                ) from None
            raise AmazonOAuthError(f'Amazon OAuth request failed (HTTP {error.code}).') from None
        except URLError as error:
            raise AmazonOAuthError(f'Could not reach Amazon: {error}') from None
