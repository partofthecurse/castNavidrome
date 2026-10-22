"""Workarounds for bugs in the Alexa SDK.

The verification of the signature of a skill request fails with an internal
server error, if Amazon delivers a certificate chain with an empty or broken
certificate block.  The SDK does not catch the ``KeyError`` of asn1crypto in
that case, so the request is answered with a HTTP 500 and the Alexa device
reports an error instead of playing the music.

The functions of this module make the verification robust against such a
chain: the broken blocks are skipped and the chain is downloaded again when
the validation fails.
"""

import logging
import time

logger = logging.getLogger(__name__)

CHAIN_VALIDATION_ATTEMPTS = 3
CHAIN_VALIDATION_DELAY = 1.0


def install_certificate_chain_workaround() -> None:
    """Make the verification of the certificate chain of a request robust.

    The patch is applied to the ``RequestVerifier`` of the
    ``ask_sdk_webservice_support`` package.  It has to be called before the
    skill adapter is created.
    """

    try:
        from ask_sdk_webservice_support import verifier
        from asn1crypto import pem, x509
        from certvalidator import CertificateValidator, ValidationError
        from certvalidator.errors import PathError
    except ImportError:  # pragma: no cover - the SDK is always installed
        logger.warning('The Alexa SDK is not installed, the certificate chain workaround is not applied.')
        return

    original_retrieve = verifier.RequestVerifier._retrieve_and_validate_certificate_chain

    def _validate_cert_chain(self, cert_chain):
        """Validate the certificate chain and skip the broken blocks."""

        end_cert = None
        intermediate_certs = []

        for _, _, der_bytes in pem.unarmor(cert_chain, multiple=True):
            if not der_bytes:
                # An empty block is not a certificate, asn1crypto raises a
                # KeyError for it and the whole request would fail.
                logger.warning('The certificate chain contains an empty certificate, it is skipped.')
                continue

            try:
                # A block that cannot be parsed is not usable either.
                x509.Certificate.load(der_bytes)
            except Exception as error:
                logger.warning('A certificate of the chain cannot be parsed, it is skipped: %s', error)
                continue

            if end_cert is None:
                end_cert = der_bytes
            else:
                intermediate_certs.append(der_bytes)

        if end_cert is None:
            raise verifier.VerificationException('The certificate chain does not contain a certificate.')

        try:
            validator = CertificateValidator(end_cert, intermediate_certs)
            validator.validate_usage(key_usage={'digital_signature'})
        except (PathError, ValidationError) as error:
            raise verifier.VerificationException('Certificate chain is not valid', error) from None

    def _retrieve_and_validate_certificate_chain(self, cert_url, *args, **kwargs):
        """Download the certificate chain again when the validation fails."""

        last_error = None

        for attempt in range(1, CHAIN_VALIDATION_ATTEMPTS + 1):
            try:
                return original_retrieve(self, cert_url, *args, **kwargs)
            except Exception as error:
                last_error = error
                logger.warning('The validation of the certificate chain failed (attempt %s of %s): %s',
                               attempt, CHAIN_VALIDATION_ATTEMPTS, error)

                if attempt < CHAIN_VALIDATION_ATTEMPTS:
                    time.sleep(CHAIN_VALIDATION_DELAY)

        raise last_error

    verifier.RequestVerifier._validate_cert_chain = _validate_cert_chain
    verifier.RequestVerifier._retrieve_and_validate_certificate_chain = _retrieve_and_validate_certificate_chain

    logger.info('The workaround for the certificate chain of the Alexa SDK is installed.')
