import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from castnavidrome.amazon_login import (
    AmazonSession,
    AmazonLoginError,
    AmazonCredentialsMissing,
    AmazonCaptchaError,
    AmazonChallengeError,
    resolve_cookie_file,
)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.env_clear = patch.dict(os.environ, {}, clear=True)
        self.env_clear.start()
        self.addCleanup(self.env_clear.stop)

    def test_env_var_takes_precedence_over_secret_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / 'run' / 'secrets'
            secrets.mkdir(parents=True)
            (secrets / 'NAVI_AMAZON_USER').write_text('from-secret', encoding='utf-8')
            with patch('castnavidrome.amazon_login.SECRETS_DIR', secrets):
                with patch.dict(os.environ, {'NAVI_AMAZON_USER': 'from-env'}):
                    session = AmazonSession()
                    self.assertEqual(session.user(), 'from-env')

    def test_secret_file_is_read_when_env_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = Path(tmp) / 'run' / 'secrets'
            secrets.mkdir(parents=True)
            (secrets / 'NAVI_AMAZON_USER').write_text('from-secret', encoding='utf-8')
            with patch('castnavidrome.amazon_login.SECRETS_DIR', secrets):
                session = AmazonSession()
                self.assertEqual(session.user(), 'from-secret')

    def test_missing_credential_is_none(self):
        session = AmazonSession()
        self.assertEqual(session.user(), '')
        self.assertEqual(session.password(), '')
        self.assertEqual(session.totp_secret(), '')


class SessionPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.session_file = Path(self.temp_dir.name) / 'session.txt'

    def test_existing_configured_cookie_file_is_preferred(self):
        configured = self.session_file
        configured.write_text('csrf=configured\n', encoding='utf-8')
        fallback = Path(self.temp_dir.name) / 'mounted.cookies'
        fallback.write_text('csrf=fallback\n', encoding='utf-8')

        with patch('castnavidrome.amazon_login.DEFAULT_COOKIE_FILE', fallback):
            self.assertEqual(resolve_cookie_file(configured), configured)

    def test_missing_configured_cookie_file_migrates_existing_mounted_cookies(self):
        configured = self.session_file
        fallback = Path(self.temp_dir.name) / 'mounted.cookies'
        fallback.write_text('csrf=fallback\n', encoding='utf-8')

        with patch('castnavidrome.amazon_login.DEFAULT_COOKIE_FILE', fallback):
            self.assertEqual(resolve_cookie_file(configured), configured)

        self.assertEqual(configured.read_text(encoding='utf-8'), 'csrf=fallback\n')

    def test_relative_cookie_path_is_resolved_from_container_root(self):
        mounted = Path(self.temp_dir.name) / 'mounted.cookies'
        mounted.write_text('csrf=fallback\n', encoding='utf-8')
        relative = Path(self.temp_dir.name).relative_to('/') / 'alexa.cookies'

        with patch('castnavidrome.amazon_login.DEFAULT_COOKIE_FILE', mounted):
            resolved = resolve_cookie_file(relative)

        self.assertEqual(resolved, Path('/') / relative)
        self.assertEqual(resolved.read_text(encoding='utf-8'), 'csrf=fallback\n')

    def test_save_and_load_round_trip(self):
        session = AmazonSession(session_file=self.session_file)
        session.cookies = {'csrf': 'csrf-value', 'session-id': 'id-value'}
        session.expires_at = time.time() + 1000
        session.save()
        self.assertTrue(self.session_file.is_file())

        loaded = AmazonSession(session_file=self.session_file)
        self.assertTrue(loaded.load())
        self.assertEqual(loaded.cookies, {'csrf': 'csrf-value', 'session-id': 'id-value'})
        self.assertEqual(loaded.csrf, 'csrf-value')

    def test_load_returns_false_when_file_missing(self):
        loaded = AmazonSession(session_file=self.session_file)
        self.assertFalse(loaded.load())

    def test_load_returns_false_for_empty_file(self):
        self.session_file.write_text('', encoding='utf-8')
        loaded = AmazonSession(session_file=self.session_file)
        self.assertFalse(loaded.load())

    def test_load_returns_false_without_csrf(self):
        self.session_file.write_text('session-id=value\n', encoding='utf-8')
        loaded = AmazonSession(session_file=self.session_file)
        self.assertFalse(loaded.load())

    def test_clear_removes_file(self):
        session = AmazonSession(session_file=self.session_file)
        session.cookies = {'csrf': 'x'}
        session.save()
        self.assertTrue(self.session_file.is_file())
        session.clear()
        self.assertFalse(self.session_file.is_file())
        self.assertEqual(session.cookies, {})
        self.assertEqual(session.expires_at, 0.0)


class EnsureSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.session_file = Path(self.temp_dir.name) / 'session.txt'
        self.env_patch = patch.dict(os.environ, {
            'NAVI_AMAZON_USER': 'user',
            'NAVI_AMAZON_PASS': 'pass',
            'NAVI_AMAZON_TOTP_SECRET': 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ',
        }, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.session = AmazonSession(session_file=self.session_file, domain='amazon.com')

    def _mock_alexa_login(self, cookies=None, session_cookies=None):
        """Mock alexapy.AlexaLogin for a successful login cycle."""
        mock_login = MagicMock()
        mock_load = AsyncMock(return_value=cookies or {})
        mock_login.load_cookie = mock_load
        mock_login.login = AsyncMock()
        mock_login.get_csrf = AsyncMock(return_value=True)
        mock_login.test_loggedin = AsyncMock(return_value=True)
        mock_login.save_cookiefile = AsyncMock()
        mock_session = MagicMock()
        mock_jar = MagicMock()
        jar_cookies = []
        for name, value in (session_cookies or {'csrf': 'csrf-value', 'session-id': 'id-value'}).items():
            c = MagicMock()
            c.key = name
            c.value = value
            jar_cookies.append(c)
        mock_jar.__iter__.return_value = iter(jar_cookies)
        mock_session.cookie_jar = mock_jar
        mock_login.session = mock_session
        return mock_login

    def test_ensure_session_returns_early_when_valid(self):
        self.session.cookies = {'csrf': 'x'}
        self.session.expires_at = time.time() + 1000
        with patch('castnavidrome.amazon_login.AlexaLogin') as mock_alexa:
            self.session.ensure_session()
            mock_alexa.assert_not_called()

    def test_ensure_session_loads_from_file_when_valid(self):
        self.session_file.write_text('csrf=x\n', encoding='utf-8')
        mock_login = self._mock_alexa_login()
        with patch('castnavidrome.amazon_login.AlexaLogin', return_value=mock_login) as mock_alexa:
            self.session.ensure_session()
            mock_alexa.assert_called_once()
        mock_login.test_loggedin.assert_awaited_once_with(
            cookies={'csrf': 'x'},
            rebuild_session=False,
        )
        self.assertEqual(self.session.cookies, {'csrf': 'csrf-value', 'session-id': 'id-value'})

    def test_login_invokes_alexa_login(self):
        mock_login = self._mock_alexa_login()
        self.session_file.write_text('csrf=captured-csrf\nsession-id=captured-id\n', encoding='utf-8')
        with patch('castnavidrome.amazon_login.AlexaLogin', return_value=mock_login):
            self.session.login()
        mock_login.test_loggedin.assert_awaited_once_with(
            cookies={'csrf': 'captured-csrf', 'session-id': 'captured-id'},
            rebuild_session=False,
        )
        mock_login.login.assert_not_awaited()
        mock_login.save_cookiefile.assert_called_once()
        self.assertEqual(self.session.cookies, {'csrf': 'csrf-value', 'session-id': 'id-value'})
        self.assertEqual(self.session.csrf, 'csrf-value')

    def test_login_uses_full_amazon_domain_for_alexapy(self):
        mock_login = self._mock_alexa_login()
        session = AmazonSession(domain='amazon.de', session_file=self.session_file)
        session.cookies = {'csrf': 'csrf-value'}
        with patch('castnavidrome.amazon_login.AlexaLogin', return_value=mock_login) as mock_alexa:
            session.login()
        self.assertEqual(mock_alexa.call_args.kwargs['url'], 'amazon.de')

    def test_valid_cookie_login_does_not_require_credentials(self):
        mock_login = self._mock_alexa_login()
        session = AmazonSession(session_file=self.session_file)
        session.cookies = {'csrf': 'csrf-value'}
        with patch.dict(os.environ, {}, clear=True):
            with patch('castnavidrome.amazon_login.AlexaLogin', return_value=mock_login):
                session.login()
        mock_login.test_loggedin.assert_awaited_once()
        mock_login.login.assert_not_awaited()

    def test_invalid_cookie_falls_back_to_credentials(self):
        mock_login = self._mock_alexa_login()
        mock_login.test_loggedin = AsyncMock(side_effect=[False, True])
        self.session.cookies = {'csrf': 'stale-csrf'}
        with patch('castnavidrome.amazon_login.AlexaLogin', return_value=mock_login):
            self.session.login()
        self.assertEqual(mock_login.test_loggedin.await_count, 2)
        self.assertEqual(
            mock_login.test_loggedin.await_args_list[1].kwargs,
            {},
        )
        mock_login.login.assert_awaited_once_with()

    def test_credentials_login_fetches_csrf_and_verifies_session(self):
        mock_login = self._mock_alexa_login()
        with patch('castnavidrome.amazon_login.AlexaLogin', return_value=mock_login):
            self.session.login()

        mock_login.login.assert_awaited_once_with()
        mock_login.test_loggedin.assert_awaited_once_with()

    def test_login_without_credentials_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            session = AmazonSession(session_file=self.session_file, domain='amazon.com')
            with self.assertRaises(AmazonCredentialsMissing):
                session.login()

    def test_captcha_is_propagated(self):
        mock_login = self._mock_alexa_login()
        mock_login.login = AsyncMock(side_effect=AmazonCaptchaError('captcha'))
        with patch('castnavidrome.amazon_login.AlexaLogin', return_value=mock_login):
            with self.assertRaises(AmazonCaptchaError):
                self.session.login()

    def test_request_reuses_valid_session_without_login(self):
        self.session.cookies = {'csrf': 'x'}
        self.session.expires_at = time.time() + 1000
        with patch('castnavidrome.amazon_login.AlexaLogin') as mock_alexa:
            self.session.request('https://example.com')
            mock_alexa.assert_not_called()
        self.assertEqual(self.session.cookies['csrf'], 'x')


if __name__ == '__main__':
    unittest.main()
