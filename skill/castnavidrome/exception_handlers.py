"""Exception handlers for the Alexa skill.

The handlers log what went wrong and answer the user with a short
explanation.  A request that only carries a directive, like the events of
the audio player, must not be answered with speech, because that would
start a new session and could end in a loop.

Ported from bickns/asknavidrome (MIT), see CREDITS.md.  The handling of the
request types without speech and the logging of the device are our own local
changes.
"""

import logging

from ask_sdk_core.dispatch_components import AbstractExceptionHandler
from ask_sdk_core.utils import get_intent_name, get_request_type
from ask_sdk_model import Response

from .localization import get_translator
from .utils import sanitise_speech_output


logger = logging.getLogger(__name__)

DIRECTIVE_REQUEST_TYPES = (
    'AudioPlayer.PlaybackStarted',
    'AudioPlayer.PlaybackFinished',
    'AudioPlayer.PlaybackNearlyFinished',
    'AudioPlayer.PlaybackStopped',
    'AudioPlayer.PlaybackFailed',
    'PlaybackController.PlayCommandIssued',
    'PlaybackController.PauseCommandIssued',
    'PlaybackController.NextCommandIssued',
    'PlaybackController.PreviousCommandIssued',
    'System.ExceptionEncountered',
)


def generic_error_speech(handler_input) -> str:
    """Get the apology of the skill in the language of the request

    :param handler_input: The Amazon Alexa HandlerInput object
    :return: The apology of the skill
    :rtype: str
    """

    translator = get_translator(handler_input)

    return sanitise_speech_output(translator.t('generic_error'), translator.locale)


def get_short_device_id(handler_input) -> str:
    """Get the ID of the device that sent the request

    Only the last characters of the ID are used, so that the log stays
    readable and does not contain a full identifier.

    :param handler_input: The Amazon Alexa HandlerInput object
    :return: The shortened device ID or an empty string
    :rtype: str
    """

    try:
        device = handler_input.request_envelope.context.system.device

        if device is None or not device.device_id:
            return ''

        return device.device_id[-8:]
    except AttributeError:
        return ''


def get_slot_summary(handler_input) -> str:
    """Get a readable summary of the slots of a request

    :param handler_input: The Amazon Alexa HandlerInput object
    :return: A summary of the slots
    :rtype: str
    """

    if get_request_type(handler_input) != 'IntentRequest':
        return ''

    try:
        slots = handler_input.request_envelope.request.intent.slots
    except AttributeError:
        return ''

    if not slots:
        return ''

    return ', '.join(f'{name}={slot.value}' for name, slot in slots.items() if slot.value)


def request_forbids_speech(handler_input) -> bool:
    """Check if the request must not be answered with speech

    :param handler_input: The Amazon Alexa HandlerInput object
    :return: True if the request must not be answered with speech
    :rtype: bool
    """

    request_type = get_request_type(handler_input)

    if request_type in DIRECTIVE_REQUEST_TYPES:
        return True

    return request_type is not None and request_type.startswith('AudioPlayer.')


class SystemExceptionHandler(AbstractExceptionHandler):
    """Handle System.ExceptionEncountered

    Handles exceptions and prints error information
    in the log
    """

    def can_handle(self, handler_input, exception: Exception) -> bool:
        return get_request_type(handler_input) == 'System.ExceptionEncountered'

    def handle(self, handler_input, exception: Exception) -> Response:
        logger.debug('In SystemExceptionHandler')

        logger.error('System Exception: %s', exception, exc_info=True)
        logger.error('Request Type Was: %s', get_request_type(handler_input))

        device_id = get_short_device_id(handler_input)

        if device_id:
            logger.error('Device Was: %s', device_id)

        if get_request_type(handler_input) == 'IntentRequest':
            logger.error('Intent Name Was: %s', get_intent_name(handler_input))

        slot_summary = get_slot_summary(handler_input)

        if slot_summary:
            logger.error('Slots Were: %s', slot_summary)

        if request_forbids_speech(handler_input):
            logger.info('The request does not allow any speech, answering with an empty response')
            return handler_input.response_builder.response

        speech = generic_error_speech(handler_input)
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response


class GeneralExceptionHandler(AbstractExceptionHandler):
    """Handle general exceptions

    Handles exceptions and prints error information
    in the log
    """

    def can_handle(self, handler_input, exception: Exception) -> bool:
        return True

    def handle(self, handler_input, exception: Exception) -> Response:
        logger.debug('In GeneralExceptionHandler')

        logger.error('General Exception: %s', exception, exc_info=True)
        logger.error('Request Type Was: %s', get_request_type(handler_input))

        device_id = get_short_device_id(handler_input)

        if device_id:
            logger.error('Device Was: %s', device_id)

        if get_request_type(handler_input) == 'IntentRequest':
            logger.error('Intent Name Was: %s', get_intent_name(handler_input))

        slot_summary = get_slot_summary(handler_input)

        if slot_summary:
            logger.error('Slots Were: %s', slot_summary)

        if request_forbids_speech(handler_input):
            logger.info('The request does not allow any speech, answering with an empty response')
            return handler_input.response_builder.response

        speech = generic_error_speech(handler_input)
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response
