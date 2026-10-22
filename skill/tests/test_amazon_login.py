import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from castnavidrome.amazon_login import (
    AmazonSession,
    AmazonLoginError,
    AmazonCredentialsMissing,
    AmazonCaptchaError,
    AmazonChallengeError,
)


class TotpTests(unittest.TestCase):
    def test_totp_is_six_digits(self):
        code = AmazonSession.totp_code('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ')
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_totp_stable_within_one_window(self):
        with patch('castnavidrome.amazon_login.time.time', return_value=1000.0):
            first = AmazonSession.totp_code('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ')
            second = AmazonSession.totp_code('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ')
        self.assertEqual(first, second)

    def test_totp_changes_between_windows(self):
        with patch('castnavidrome.amazon_login.time.time', return_value=0.0):
            first = AmazonSession.totp_code('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ')
        with patch('castnavidrome.amazon_login.time.time', return_value=31.0):
            second = AmazonSession.totp_code('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ')
        # Different windows very likely produce different codes.
        self.assertNotEqual(first, second)

    def test_totp_rejects_invalid_secret(self):
        with self.assertRaises(AmazonLoginError):
            AmazonSession.totp_code('not-valid-base32!!!')


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
        self.session_file = Path(self.temp_dir.name) / 'session.json'

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

    def test_load_returns_false_for_wrong_domain(self):
        session = AmazonSession(domain='amazon.de', session_file=self.session_file)
        session.cookies = {'csrf': 'x'}
        session.expires_at = time.time() + 1000
        session.save()

        other = AmazonSession(domain='amazon.com', session_file=self.session_file)
        self.assertFalse(other.load())

    def test_load_returns_false_for_expired_session(self):
        session = AmazonSession(session_file=self.session_file)
        session.cookies = {'csrf': 'x'}
        session.expires_at = time.time() - 1000
        session.save()

        loaded = AmazonSession(session_file=self.session_file)
        self.assertFalse(loaded.load())

    def test_load_returns_false_when_file_missing(self):
        loaded = AmazonSession(session_file=self.session_file)
        self.assertFalse(loaded.load())


class CaptchaDetectionTests(unittest.TestCase):
    def test_is_captcha_detects_body_and_url(self):
        self.assertTrue(AmazonSession._is_captcha(b'<html>captcha</html>'))
        self.assertTrue(AmazonSession._is_captcha(b'', url='https://api.captcha-amazon.com/x'))
        self.assertFalse(AmazonSession._is_captcha(b'<html>ok</html>'))


class LoginTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.session_file = Path(self.temp_dir.name) / 'session.json'
        self.session = AmazonSession(session_file=self.session_file, domain='amazon.com')
        self.env_patch = patch.dict(os.environ, {
            'NAVI_AMAZON_USER': 'user',
            'NAVI_AMAZON_PASS': 'pass',
            'NAVI_AMAZON_TOTP_SECRET': 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ',
        }, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_login_without_credentials_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            session = AmazonSession(session_file=self.session_file, domain='amazon.com')
            with self.assertRaises(AmazonCredentialsMissing):
                session.login()

    def test_login_without_totp_secret_when_required(self):
        with patch.dict(os.environ, {'NAVI_AMAZON_TOTP_SECRET': ''}, clear=False):
            with patch.object(self.session, '_raw_request', return_value=b'<html>totp verification code</html>'):
                with self.assertRaises(AmazonCredentialsMissing):
                    self.session.login()

    def test_captcha_is_propagated(self):
        self.session._raw_request = MagicMock(side_effect=AmazonCaptchaError('captcha'))
        with self.assertRaises(AmazonCaptchaError):
            self.session.login()

    def test_request_reuses_valid_session_without_login(self):
        self.session.cookies = {'csrf': 'x'}
        self.session.expires_at = time.time() + 1000
        self.session._raw_request = MagicMock(return_value=b'body')
        self.session.request('https://example.com')
        self.session._raw_request.assert_called_once()
        self.assertEqual(self.session.cookies['csrf'], 'x')


if __name__ == '__main__':
    unittest.main()
