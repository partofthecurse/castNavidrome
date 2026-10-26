"""Handler registration for the castNavidrome Alexa skill.

This package splits the monolithic ``app.py`` into domain-specific handler
modules.  Each module sets its own module-level dependencies via
``register_handlers()`` which is called from ``app.py``.
"""

from . import system, interceptors

# Module-level dependencies shared across handler modules.
_connection = None
_state = None
_controller = None
_search_resolver = None
_playlist_names = None
_translate = None
_skill_display_name = 'castNavidrome'
_help_overview_key = 'help_overview'


def register_handlers(
    sb,
    connection,
    state,
    controller,
    search_resolver,
    playlist_names,
    translate_func,
    skill_display_name: str = 'castNavidrome',
    help_overview_key: str = 'help_overview',
) -> None:
    """Wire dependencies into the handler modules and register all handlers.

    :param sb: The Alexa SkillBuilder instance
    :param connection: SubsonicConnection to the media server
    :param state: state module (shared runtime state)
    :param controller: controller module (playback control)
    :param search_resolver: SearchResolver instance
    :param playlist_names: PlaylistNames instance
    :param translate_func: translate(handler_input, key, **kwargs) callable
    :param str skill_display_name: Display name of the skill
    :param str help_overview_key: Message key for the help overview
    """
    global _connection, _state, _controller, _search_resolver
    global _playlist_names, _translate, _skill_display_name, _help_overview_key

    _connection = connection
    _state = state
    _controller = controller
    _search_resolver = search_resolver
    _playlist_names = playlist_names
    _translate = translate_func
    _skill_display_name = skill_display_name
    _help_overview_key = help_overview_key

    system.register(_connection, _state, _translate, _skill_display_name, _help_overview_key)

    # Register simple system handlers with the SkillBuilder
    sb.add_request_handler(system.LaunchRequestHandler())
    sb.add_request_handler(system.CheckAudioInterfaceHandler())
    sb.add_request_handler(system.SkillEventHandler())
    sb.add_request_handler(system.HelpHandler())

    # Register interceptors
    sb.add_request_interceptor(interceptors.LoggingRequestInterceptor())
    sb.add_response_interceptor(interceptors.LoggingResponseInterceptor())