"""Helpers for the Alexa skill requests."""

import logging

from .localization import Translator


logger = logging.getLogger(__name__)

try:
    from ask_sdk_model.slu.entityresolution.status_code import StatusCode
    SUCCESS_MATCH = StatusCode.ER_SUCCESS_MATCH
except ImportError:
    # The SDK is not needed to use this module, it is only needed to compare
    # the status of a resolution.
    SUCCESS_MATCH = 'ER_SUCCESS_MATCH'


def get_resolved_slot_value(handler_input, slot_name: str) -> str:
    """Get the canonical value of a slot

    Alexa resolves a slot value against the values of the slot type.  If the
    user says a synonym of a custom slot value, the raw value of the slot is
    the spoken word, but the resolved value is the name of the slot value
    that it belongs to.  Only the resolved value can be used to search the
    media server, otherwise a synonym is not found.

    If the slot is not resolved, the raw value is returned, so that a slot
    without any resolution still works.

    Ported from jfagn/asknavidrome (MIT), see CREDITS.md.

    :param handler_input: The Amazon Alexa HandlerInput object
    :param str slot_name: The name of the slot
    :return: The value of the slot or None if the slot is not present
    :rtype: str | None
    """

    slots = handler_input.request_envelope.request.intent.slots
    slot = slots.get(slot_name)

    if slot is None:
        return None

    if slot.resolutions and slot.resolutions.resolutions_per_authority:
        for authority in slot.resolutions.resolutions_per_authority:
            if authority.status.code == SUCCESS_MATCH:
                return authority.values[0].value.name

    return slot.value


def sanitise_speech_output(speech_string: str, locale: str = None) -> str:
    """Sanitise speech output inline with the SSML standard

    Speech Synthesis Markup Language (SSML) has certain ASCII characters that are
    reserved.  This function replaces them with alternatives.

    The conjunction that replaces the reserved characters is the one of the
    language of the locale, so that the text stays understandable in the
    language that it is spoken in.

    Moved here from app.py, so that it can be used by the exception handlers
    without a circular import.

    :param speech_string: The string to process
    :type speech_string: str
    :param locale: The locale of the speech, the default locale when it is None
    :type locale: str | None
    :return: The processed SSML compliant string
    :rtype: str
    """

    logger.debug('In sanitise_speech_output()')

    conjunction = Translator(locale).conjunction('and')

    # The conjunction is surrounded by spaces, so that the words around it
    # stay separate words in the speech output.
    replacement = f' {conjunction} '

    if '&' in speech_string:
        speech_string = speech_string.replace('&', replacement)
    if '/' in speech_string:
        speech_string = speech_string.replace('/', replacement)
    if '\\' in speech_string:
        speech_string = speech_string.replace('\\', replacement)
    if '"' in speech_string:
        speech_string = speech_string.replace('"', '')
    if "'" in speech_string:
        speech_string = speech_string.replace("'", "")
    if "<" in speech_string:
        speech_string = speech_string.replace('<', '')
    if ">" in speech_string:
        speech_string = speech_string.replace('>', '')

    return ' '.join(speech_string.split())
