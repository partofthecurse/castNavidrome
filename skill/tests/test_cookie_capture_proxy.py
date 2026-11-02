import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from castnavidrome.cookie_capture_proxy import AlexaCookieCaptureProxy, _RoutedAlexaProxy


class CookieCaptureProxyTests(unittest.TestCase):
    def test_validation_discovers_missing_csrf_before_rejecting_session(self):
        manager = AlexaCookieCaptureProxy()
        manager._login = MagicMock()
        manager._login.get_csrf = AsyncMock(return_value=True)
        manager._login.test_loggedin = AsyncMock(return_value=True)
        cookies = {
            'session-id': 'session-value',
            'csrf': 'csrf-value',
        }
        manager._read_cookies = AsyncMock(side_effect=[{'session-id': 'session-value'}, cookies, cookies])

        result = asyncio.run(manager._validated_cookies())

        self.assertEqual(result, cookies)
        manager._login.get_csrf.assert_awaited_once_with()
        manager._login.test_loggedin.assert_awaited_once_with(
            cookies=cookies,
            rebuild_session=False,
        )

    def test_auto_save_persists_validated_cookies_without_manual_post(self):
        manager = AlexaCookieCaptureProxy()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._cookie_file = Path(temp_dir) / 'alexa.cookies'
            manager._validated_cookies = AsyncMock(return_value={
                'csrf': 'csrf-value',
                'session-id': 'session-id-value',
            })

            count = asyncio.run(manager._save_after_browser_login())

            self.assertEqual(count, 2)
            self.assertEqual(
                manager._cookie_file.read_text(encoding='utf-8'),
                'csrf=csrf-value\nsession-id=session-id-value\n',
            )

    def test_cookie_writer_updates_a_mounted_file_in_place(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cookie_file = Path(temp_dir) / 'alexa.cookies'
            cookie_file.write_text('csrf=old\n', encoding='utf-8')

            with patch.object(Path, 'is_mount', return_value=True):
                count = AlexaCookieCaptureProxy._write_cookie_file(
                    cookie_file,
                    {'csrf': 'new'},
                )

            self.assertEqual(count, 1)
            self.assertEqual(cookie_file.read_text(encoding='utf-8'), 'csrf=new\n')
            self.assertEqual(list(Path(temp_dir).glob('.alexa.cookies.*')), [])

    def test_successful_browser_login_triggers_automatic_cookie_save(self):
        proxy = object.__new__(_RoutedAlexaProxy)
        proxy._on_login_success = AsyncMock()
        response = SimpleNamespace(url='https://www.amazon.com/ap/maplanding')

        async def run_callback():
            with patch(
                'castnavidrome.cookie_capture_proxy.AlexaProxy.test_amazon_url',
                new=AsyncMock(return_value='login complete'),
            ):
                return await proxy.test_amazon_url(response, {}, {})

        result = asyncio.run(run_callback())

        self.assertEqual(result, 'login complete')
        proxy._on_login_success.assert_awaited_once()

    def test_autofill_uses_a_fresh_totp_for_each_form(self):
        proxy = object.__new__(_RoutedAlexaProxy)
        proxy._login = MagicMock()
        proxy._login._debug = False
        proxy._login.get_totp_token.side_effect = ['fresh-code-1', 'fresh-code-2']
        form = '<input name="otpCode">'

        first = proxy.autofill({'otpCode': 'stale-code'}, form)
        second = proxy.autofill({'otpCode': 'stale-code'}, form)

        self.assertIn('value="fresh-code-1"', first)
        self.assertIn('value="fresh-code-2"', second)
        self.assertNotIn('stale-code', first + second)

    def test_start_builds_stable_public_url_and_close_releases_resources(self):
        login = MagicMock()
        login.session = None
        login.close = AsyncMock()

        proxy = MagicMock()
        proxy.start_proxy = AsyncMock()
        proxy.stop_proxy = AsyncMock()
        proxy.session.is_closed = True

        manager = AlexaCookieCaptureProxy(port=3456)
        with patch('castnavidrome.cookie_capture_proxy.AlexaLogin', return_value=login):
            with patch('castnavidrome.cookie_capture_proxy._RoutedAlexaProxy', return_value=proxy) as proxy_factory:
                public_url = manager.ensure_started('https://castnavidrome.example.test/')
                self.assertTrue(public_url.startswith(
                    'https://castnavidrome.example.test/api/alexa/cookie/proxy/'
                ))
                self.assertEqual(manager.ensure_started('https://ignored.example.test'), public_url)
                proxy_factory.assert_called_once()
                proxy.start_proxy.assert_awaited_once()

                manager.close()

        proxy.stop_proxy.assert_awaited_once()
        login.close.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()