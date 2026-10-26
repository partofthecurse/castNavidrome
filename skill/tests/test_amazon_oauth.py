import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from castnavidrome.amazon_oauth import (
    AmazonOAuthSession,
    AmazonOAuthError,
    AmazonOAuthCredentialsMissing,
)


TOKEN_RESPONSE = b'{"access_token": "access-token", ' \
                 b'"refresh_token": "refresh-token", "expires_in": 3600}'


def make_session(token_file=None, domain='amazon.com'):
    return AmazonOAuthSession(domain=domain, token_file=token_file)


class AuthorizationUrlTests(unittest.TestCase):
    def test_authorization_url_contains_all_parameters(self):
        session = make_session()
        url, state = session.authorization_url(
            client_id='client-id',
            redirect_uri='https://example.test/callback',
        )
        self.assertIn('https://www.amazon.com/ap/oa', url)
        self.assertIn('client_id=client-id', url)
        self.assertIn('response_type=code', url)
        self.assertIn('redirect_uri=https%3A%2F%2Fexample.test%2Fcallback', url)
        self.assertIn('scope=profile', url)
        self.assertIn(f'state={state}', url)
        self.assertEqual(len(state), 43)  # token_urlsafe(32) -> 43 chars

    def test_authorization_url_uses_custom_scope(self):
        session = make_session()
        url, _ = session.authorization_url(
            client_id='client-id',
            redirect_uri='https://example.test/callback',
            scope='alexa::devices:all alexa::skills:flash_briefing',
        )
        self.assertIn('scope=alexa%3A%3Adevices%3Aall+alexa%3A%3Askills%3Aflash_briefing', url)

    def test_missing_credentials_raise(self):
        session = make_session()
        with patch.object(session, 'client_id', return_value=''):
            with self.assertRaises(AmazonOAuthCredentialsMissing):
                session.authorization_url()


class TokenExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.token_file = Path(self.temp_dir.name) / 'oauth_token.json'

    def test_exchange_code_stores_tokens(self):
        session = make_session(token_file=self.token_file)
        session._raw_request = MagicMock(return_value=TOKEN_RESPONSE)
        session.exchange_code_for_tokens(
            code='the-code',
            client_id='client-id',
            client_secret='client-secret',
            redirect_uri='https://example.test/callback',
        )
        self.assertEqual(session.access_token, 'access-token')
        self.assertEqual(session.refresh_token, 'refresh-token')
        self.assertTrue(session.is_valid())
        self.assertTrue(self.token_file.is_file())

    def test_exchange_code_persists_and_loads(self):
        session = make_session(token_file=self.token_file)
        session._raw_request = MagicMock(return_value=TOKEN_RESPONSE)
        session.exchange_code_for_tokens(
            code='the-code', client_id='cid', client_secret='secret',
            redirect_uri='https://example.test/callback',
        )
        loaded = AmazonOAuthSession(domain='amazon.com', token_file=self.token_file)
        self.assertEqual(loaded.access_token, 'access-token')
        self.assertEqual(loaded.refresh_token, 'refresh-token')
        self.assertTrue(loaded.is_valid())

    def test_exchange_code_without_access_token_raises(self):
        session = make_session(token_file=self.token_file)
        session._raw_request = MagicMock(return_value=b'{}')
        with self.assertRaises(AmazonOAuthError):
            session.exchange_code_for_tokens(
                code='the-code', client_id='cid', client_secret='secret',
                redirect_uri='https://example.test/callback',
            )

    def test_refresh_access_token(self):
        session = make_session(token_file=self.token_file)
        session.refresh_token = 'refresh-token'
        session._raw_request = MagicMock(return_value=b'{"access_token": "new-access", "expires_in": 3600}')
        session.refresh_access_token()
        self.assertEqual(session.access_token, 'new-access')
        self.assertTrue(session.is_valid())

    def test_refresh_without_token_raises(self):
        session = make_session()
        with self.assertRaises(AmazonOAuthCredentialsMissing):
            session.refresh_access_token()


class SessionStateTests(unittest.TestCase):
    def test_is_valid_false_without_tokens(self):
        self.assertFalse(make_session().is_valid())

    def test_ensure_session_raises_without_tokens(self):
        session = make_session()
        with self.assertRaises(AmazonOAuthCredentialsMissing):
            session.ensure_session()

    def test_ensure_session_passes_with_valid_token(self):
        session = make_session()
        session.access_token = 'access-token'
        session.expires_at = time.time() + 1000
        self.assertIsNone(session.ensure_session())


class BearerRequestTests(unittest.TestCase):
    def setUp(self):
        self.session = make_session()
        self.session.access_token = 'access-token'
        self.session.expires_at = time.time() + 1000

    def test_request_sends_bearer_header(self):
        self.session._raw_request = MagicMock(return_value=b'ok')
        self.session.request('https://alexa.amazon.com/api/devices-v2/device?cached=false')
        _, kwargs = self.session._raw_request.call_args
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer access-token')

    def test_request_refreshes_on_401(self):
        self.session.refresh_token = 'refresh-token'
        first = HTTPError('https://alexa.amazon.com', 401, 'Unauthorized', {}, None)
        self.session._raw_request = MagicMock(side_effect=[first, b'ok'])
        with patch.object(self.session, 'refresh_access_token') as refresh:
            self.session.request('https://alexa.amazon.com/api/x')
        refresh.assert_called_once()
        self.assertEqual(self.session._raw_request.call_count, 2)


if __name__ == '__main__':
    unittest.main()
