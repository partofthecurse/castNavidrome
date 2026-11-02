import unittest

from castnavidrome.simple_cookie_proxy import SimpleCookieProxy


class _Response:
    headers = {}
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'ok'


class _Opener:
    def __init__(self):
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return _Response()


class SimpleCookieProxyTests(unittest.TestCase):
    def setUp(self):
        self.proxy = SimpleCookieProxy(domain='amazon.de')
        self.proxy.opener = _Opener()

    def test_empty_path_uses_configured_amazon_domain(self):
        body, _headers, status = self.proxy.forward('', 'GET', {}, b'', b'')

        self.assertEqual(self.proxy.opener.request.full_url, 'https://www.amazon.de/')
        self.assertEqual((body, status), (b'ok', 200))

    def test_does_not_forward_capture_auth_or_browser_cookies(self):
        self.proxy.forward(
            'www.amazon.de/ap/signin',
            'GET',
            {
                'Authorization': 'Basic capture-secret',
                'Cookie': 'local=session',
            },
            b'',
            b'',
        )

        self.assertIsNone(self.proxy.opener.request.get_header('Authorization'))
        self.assertIsNone(self.proxy.opener.request.get_header('Cookie'))

    def test_rejects_non_amazon_hosts(self):
        with self.assertRaises(ValueError):
            self.proxy.forward('attacker.example/path', 'GET', {}, b'', b'')


if __name__ == '__main__':
    unittest.main()