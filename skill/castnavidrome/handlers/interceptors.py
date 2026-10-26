"""Request and response interceptors for the castNavidrome Alexa skill.

Logs metadata of incoming requests and outgoing responses without leaking
session tokens.
"""

import logging

from ask_sdk_core.dispatch_components import AbstractRequestInterceptor, AbstractResponseInterceptor
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils import get_request_type, get_intent_name
from ask_sdk_model import Response

logger = logging.getLogger(__name__)


class LoggingRequestInterceptor(AbstractRequestInterceptor):
    """Intercept all requests

    Intercepts all requests sent to the skill and prints them in the log.

    Only the metadata of a request is logged.  The complete request contains
    the session token of the user, so it must never end up in the log.

    Ported from johnpaulgosling/asknavidrome (MIT), see CREDITS.md.
    """

    def process(self, handler_input: HandlerInput):
        request_type = get_request_type(handler_input)
        intent_name = get_intent_name(handler_input) if request_type == 'IntentRequest' else None
        logger.debug('Request metadata: type=%s intent=%s', request_type, intent_name)


class LoggingResponseInterceptor(AbstractResponseInterceptor):
    """Intercept all responses

    Intercepts all responses sent from the skill and prints them in the log
    """

    def process(self, handler_input: HandlerInput, response: Response):
        directives = len(response.directives) if response and response.directives else 0
        has_output_speech = bool(response and response.output_speech)
        should_end_session = response.should_end_session if response else None
        logger.debug(
            'Response metadata: directives=%d has_output_speech=%s should_end_session=%s',
            directives, has_output_speech, should_end_session,
        )