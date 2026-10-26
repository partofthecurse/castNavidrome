"""System handlers for the castNavidrome Alexa skill.

Handles launch, help, audio-interface checks and skill events (session end,
skill enabled/disabled).  Dependencies are injected via :func:`register`.
"""

import logging

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_model import Response

logger = logging.getLogger(__name__)

# Injected dependencies
_connection = None
_state = None
_translate = None
_skill_display_name = 'castNavidrome'
_help_overview_key = 'help_overview'


def register(
    connection,
    state,
    translate_func,
    skill_display_name: str = 'castNavidrome',
    help_overview_key: str = 'help_overview',
) -> None:
    """Inject shared dependencies into this module.

    :param connection: SubsonicConnection to the media server
    :param state: state module (shared runtime state)
    :param translate_func: translate(handler_input, key, **kwargs) callable
    :param str skill_display_name: Display name of the skill
    :param str help_overview_key: Message key for the help overview
    """
    global _connection, _state, _translate, _skill_display_name, _help_overview_key
    _connection = connection
    _state = state
    _translate = translate_func
    _skill_display_name = skill_display_name
    _help_overview_key = help_overview_key


class LaunchRequestHandler(AbstractRequestHandler):
    """Handle LaunchRequest and NavigateHomeIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            is_request_type('LaunchRequest')(handler_input) or
            is_intent_name('AMAZON.NavigateHomeIntent')(handler_input)
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In LaunchRequestHandler')

        _connection.ping()
        speech = _translate(handler_input, 'ready')

        handler_input.response_builder.speak(speech).ask(speech)
        return handler_input.response_builder.response


class CheckAudioInterfaceHandler(AbstractRequestHandler):
    """Check if device supports audio play.

    This can be used as the first handler to be checked, before invoking
    other handlers, thus making the skill respond to unsupported devices
    without doing much processing.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        if handler_input.request_envelope.context.system.device:
            # Since skill events won't have device information
            return handler_input.request_envelope.context.system.device.supported_interfaces.audio_player is None
        else:
            return False

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In CheckAudioInterfaceHandler')

        _ = handler_input.attributes_manager.request_attributes['_']
        speech = _translate(handler_input, 'device_not_supported')
        handler_input.response_builder.speak(speech).set_should_end_session(True)

        return handler_input.response_builder.response


class SkillEventHandler(AbstractRequestHandler):
    """Close session for skill events or when session ends.

    Handler to handle session end or skill events (SkillEnabled,
    SkillDisabled etc.)
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (handler_input.request_envelope.request.object_type.startswith(
                'AlexaSkillEvent') or
                is_request_type('SessionEndedRequest')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In SkillEventHandler')

        return handler_input.response_builder.response


class HelpHandler(AbstractRequestHandler):
    """Handle HelpIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('AMAZON.HelpIntent')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In HelpHandler')

        text = _translate(handler_input, _help_overview_key, skill=_skill_display_name)
        handler_input.response_builder.speak(text).ask(text)

        return handler_input.response_builder.response