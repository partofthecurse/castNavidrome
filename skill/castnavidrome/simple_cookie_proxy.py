"""Einfacher Cookie-Capture-Proxy für den Amazon-Login.

Leitet Anfragen an Amazon weiter und erfasst Session-Cookies in einer
CookieJar. Nach erfolgreichem Login im Browser können die Cookies in
NAVI_ALEXA_COOKIE_FILE (SimpleCookie-Format) geschrieben werden, sodass
alexapy sie für den automatischen Betrieb (und Erneuerung) verwenden kann.
"""

import http.cookiejar
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

DEFAULT_DOMAIN = 'amazon.com'

class SimpleCookieProxy:
    """Einfacher Forward-Proxy mit Cookie-Erfassung."""

    def __init__(self, domain=None) -> None:
        self.domain = domain or os.getenv('NAVI_ALEXA_DOMAIN', DEFAULT_DOMAIN)
        self.amazon_domain = (self.domain if self.domain.startswith('amazon.')
                              else f'amazon.{self.domain}')
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def cookies(self) -> dict:
        """Gibt alle erfassten Cookies als name=value-Dict zurück."""
        return {c.name: c.value for c in self.jar}

    def has_csrf(self) -> bool:
        return any(c.name.lower() == 'csrf' for c in self.jar)

    def _is_allowed_host(self, host: str) -> bool:
        host = host.lower().rstrip('.')
        allowed_domains = (self.amazon_domain.lower(), 'amazon.com')
        return any(host == domain or host.endswith(f'.{domain}') for domain in allowed_domains)

    def save_to_file(self, path: str) -> int:
        """Schreibt Cookies als SimpleCookie-Name=Value-Zeilen in eine Datei."""
        cookies = self.cookies()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        lines = [f'{name}={value}' for name, value in cookies.items()]
        Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8')
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        logger.info('%s Cookie(s) nach %s geschrieben.', len(cookies), path)
        return len(cookies)

    def forward(self, path: str, method: str, headers: dict, body: bytes,
                query_string: bytes):
        """Leitet eine Anfrage an Amazon weiter und gibt die Antwort zurück.

        Gibt (body, headers_dict, status_code) zurück.
        """
        p = path.lstrip('/')
        if not p:
            p = f'www.{self.amazon_domain}/'

        if '/' in p:
            host_part = p.split('/', 1)[0]
        else:
            host_part = p
            p = p + '/'

        if '.' not in host_part:
            p = f'www.{self.amazon_domain}/{p}'
        else:
            parsed_host = urlsplit(f'//{host_part}')
            if (parsed_host.hostname is None or parsed_host.username or parsed_host.password or
                    parsed_host.port not in (None, 443) or not self._is_allowed_host(parsed_host.hostname)):
                raise ValueError('Cookie proxy only allows Amazon hosts for the configured domain.')

        url = f'https://{p}'
        if query_string:
            url += '?' + query_string.decode('utf-8', 'ignore')

        fwd_headers = {}
        for key, value in headers.items():
            if key.lower() in ('host', 'authorization', 'proxy-authorization', 'cookie',
                               'connection', 'content-length',
                               'content-encoding', 'transfer-encoding'):
                continue
            fwd_headers[key] = value

        try:
            req = urllib.request.Request(
                url, data=body if body else None,
                headers=fwd_headers, method=method
            )
            try:
                with self.opener.open(req, timeout=30) as response:
                    return (
                        response.read(),
                        dict(response.headers.items()),
                        response.status,
                    )
            except urllib.error.HTTPError as error:
                return (
                    error.read() if hasattr(error, 'read') else b'',
                    dict(error.headers.items()) if hasattr(error, 'headers') else [],
                    error.code,
                )
        except urllib.error.URLError as error:
            logger.warning('Proxy upstream error for %s: %s', url, error)
            return (b'', {}, 502)
