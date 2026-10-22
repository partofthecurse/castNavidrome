import unittest
from unittest.mock import MagicMock, patch

from castnavidrome import ask_sdk_compat


class CertificateChainWorkaroundTests(unittest.TestCase):
    """The verification of the certificate chain must not fail the request.

    Amazon delivers a certificate chain with an empty or broken certificate
    block from time to time.  The Alexa SDK does not catch the error of
    asn1crypto in that case and answers the request with a HTTP 500, so the
    Alexa device reports an error instead of playing the music.
    """

    def setUp(self):
        self.verifier = MagicMock()
        self.verifier.VerificationException = ValueError

        self.patchers = [
            patch('ask_sdk_webservice_support.verifier.RequestVerifier._validate_cert_chain'),
            patch('ask_sdk_webservice_support.verifier.RequestVerifier._retrieve_and_validate_certificate_chain'),
        ]
        self.original_validate = self.patchers[0].start()
        self.original_retrieve = self.patchers[1].start()
        self.addCleanup(patch.stopall)

        ask_sdk_compat.install_certificate_chain_workaround()

    def _chain(self, *blocks):
        return b''.join(
            b'-----BEGIN CERTIFICATE-----\n' + block + b'\n-----END CERTIFICATE-----\n'
            for block in blocks
        )

    def test_an_empty_certificate_is_skipped(self):
        from asn1crypto import pem

        chain = self._chain(b'MIIB', b'')
        blocks = [der for _, _, der in pem.unarmor(chain, multiple=True)]

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[1], b'')

    def test_the_validation_does_not_raise_for_an_empty_block(self):
        from ask_sdk_webservice_support import verifier

        chain = self._chain(b'MIIB', b'')

        # The patched method must not raise a KeyError for the empty block.
        try:
            verifier.RequestVerifier._validate_cert_chain(MagicMock(), chain)
        except Exception as error:
            self.assertNotIsInstance(error, KeyError)

    def test_the_chain_is_downloaded_again_when_the_validation_fails(self):
        from ask_sdk_webservice_support import verifier

        self.original_retrieve.side_effect = [ValueError('broken chain'), 'the chain']

        result = verifier.RequestVerifier._retrieve_and_validate_certificate_chain(MagicMock(), 'https://x/c.pem')

        self.assertEqual(result, 'the chain')
        self.assertEqual(self.original_retrieve.call_count, 2)

    def test_the_error_is_raised_when_all_attempts_fail(self):
        from ask_sdk_webservice_support import verifier

        self.original_retrieve.side_effect = ValueError('broken chain')

        with self.assertRaises(ValueError):
            verifier.RequestVerifier._retrieve_and_validate_certificate_chain(MagicMock(), 'https://x/c.pem')

        self.assertEqual(self.original_retrieve.call_count, ask_sdk_compat.CHAIN_VALIDATION_ATTEMPTS)


if __name__ == '__main__':
    unittest.main()
