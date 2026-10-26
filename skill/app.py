"""castNavidrome Alexa skill - the web service that bridges Alexa devices to a Navidrome media server.

The module creates a Flask web service that receives requests from the Alexa
skill and turns them into playback on the media server.  It registers all
intent and audio player handlers, loads the configuration from environment
variables and exposes an HTTP API for controlling Alexa devices from the
renderer host.
"""

from datetime import datetime
import hmac  # cryptographic signatures for API key verification
from flask import Flask, abort, jsonify, redirect, render_template, request  # Flask micro web framework
from flask import Response as FlaskResponse  # Flask response type, separate from the ask SDK response
import logging
from multiprocessing import Process
import os
import random
import signal
import sys
import threading
import time

from ask_sdk_core.skill_builder import SkillBuilder  # builds the Alexa skill
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractRequestInterceptor, AbstractResponseInterceptor
from ask_sdk_core.utils import is_request_type, is_intent_name, get_intent_name, get_request_type
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from flask_ask_sdk.skill_adapter import SkillAdapter  # bridges the ask SDK skill to Flask

import castnavidrome.subsonic_api as api  # talks to the Navidrome media server
from castnavidrome.alexa_remote import AlexaRemoteError, AlexaTextCommandClient, build_control_text, find_devices_by_name
from castnavidrome.amazon_oauth import AmazonOAuthSession, AmazonOAuthError, AmazonOAuthCredentialsMissing
from castnavidrome.renderer_registry import RendererRegistry
import castnavidrome.controller as controller
import castnavidrome.queue_filler as queue_filler
import castnavidrome.state as state
import castnavidrome.decades as decades
from castnavidrome.search import SearchResolver
from castnavidrome.track import Track
from castnavidrome.playlist_names import build_playlist_names
from castnavidrome.utils import get_resolved_slot_value, sanitise_speech_output
from castnavidrome.localization import (
    HELP_OVERVIEW_KEY,
    HELP_TOPIC_ALIASES,
    HELP_TOPICS,
    SKILL_DISPLAY_NAME,
    get_configured_locale,
    get_translator,
)
from castnavidrome.exception_handlers import GeneralExceptionHandler, SystemExceptionHandler
from castnavidrome.cover_art import fetch_cover_art
from castnavidrome.ask_sdk_compat import install_certificate_chain_workaround
from castnavidrome.handlers import register_handlers

# Create the Flask web service
app = Flask(__name__)

# Create the Alexa skill builder
sb = SkillBuilder()

# Set up logging to stdout
log_level_name = os.getenv('NAVI_LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_name, logging.INFO)

logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)

#
# Get service configuration
#

logger.info('castNavidrome 0.10!')
logger.debug('Getting configuration from the environment...')

# Configuration validation
CONFIG_VALIDATION_ERRORS = []
CONFIG_VALIDATION_WARNINGS = []

# Required configuration variables that must be set.  They are read from the
# environment or from Docker secrets and are never optional.  When one of
# them is missing the service refuses to start with a clear error message so
# that the operator is pointed at the missing value.
REQUIRED_SENSITIVE_VARS = {
    'NAVI_SKILL_ID': 'Alexa Skill ID from the Alexa Developer Console',
    'NAVI_URL': 'URL of the Navidrome (Subsonic) media server',
    'NAVI_BASE_URL': 'Public https URL of the skill, used for cover art links',
    'NAVI_USER': 'Navidrome user name',
    'NAVI_PASS': 'Navidrome admin password',
    'NAVI_ALEXA_API_KEY': 'Alexa Remote API key',
    'NAVI_ALEXA_SKILL_NAME': 'Invocation name of the Alexa skill',
    'TS_AUTHKEY': 'Tailscale auth key for service authentication',
}

# Variables whose values should be masked in logs.  Only the required
# sensitive variables are masked, so that an operator never sees a password,
# API key or auth key in the log output.
SENSITIVE_CONFIG_VARS = {
    'NAVI_PASS',
    'NAVI_ALEXA_API_KEY',
    'NAVI_AMAZON_CLIENT_ID',
    'NAVI_AMAZON_CLIENT_SECRET',
    'NAVI_AMAZON_REDIRECT_URI',
    'TS_AUTHKEY',
}

# Optional configuration variables with sensible defaults.  When they are not
# set in the environment the default value is used, so that the service works
# out of the box.  When they are set (for example via docker-compose.yaml or
# a Docker secret) the set value takes precedence over the default.
OPTIONAL_CONFIG_VARS = {
    # Navidrome connection
    'NAVI_PORT': '443',
    'NAVI_API_PATH': '/rest',
    'NAVI_API_VER': '1.16.1',
    'NAVI_API_TIMEOUT': '10',
    'NAVI_DEBUG': '0',
    'NAVI_LOG_LEVEL': 'INFO',

    # Alexa skill
    'NAVI_ALEXA_DOMAIN': 'amazon.com',
    'NAVI_ALEXA_LOCALE': 'en-US',
    'NAVI_ALEXA_COOKIE_FILE': '/run/secrets/alexa.cookies',

    # Alexa renderer
    'NAVI_ALEXA_RENDERER_LOG_LEVEL': 'INFO',
    'NAVI_ALEXA_RENDERER_ENABLED': 'true',
    'NAVI_ALEXA_RENDERER_STATE_FILE': '/var/lib/castnavidrome/renderer-devices.json',
    'NAVI_ALEXA_RENDERER_ADVERTISE_HOST': '',
    'NAVI_ALEXA_RENDERER_PORT': '49443',
    'NAVI_ALEXA_RENDERER_REFRESH_SECONDS': '300',
    'NAVI_ALEXA_RENDERER_MIN_REFRESH_SECONDS': '60',
    'NAVI_ALEXA_RENDERER_NAME_PREFIX': '',
    'NAVI_ALEXA_RENDERER_DEVICE_TYPES': '',
    'NAVI_ALEXA_RENDERER_EXCLUDED_DEVICE_TYPES': 'TABLET,E_READER,EBOOK_READER,KINDLE,ECHO_READER,FIRE_READER',
    'NAVI_ALEXA_RENDERER_NAME_INCLUDE': '',
    'NAVI_ALEXA_RENDERER_NAME_EXCLUDE': '',
    'NAVI_ALEXA_RENDERER_NAME_REGEX': '',
    'NAVI_ALEXA_RENDERER_ONLY_ONLINE': 'false',
    'NAVI_ALEXA_RENDERER_ANNOUNCE': 'explicit',
    'NAVI_ALEXA_RENDERER_ANNOUNCE_INTERVAL': '60',
    'NAVI_ALEXA_RENDERER_SSDP_MX': '0',

    # Amazon OAuth (Login with Amazon).  These are only required when the OAuth
    # flow is enabled, i.e. when NAVI_AMAZON_CLIENT_ID is set.  When OAuth is
    # disabled the Alexa Remote API is used with a static cookie file instead.
    'NAVI_AMAZON_CLIENT_ID': '',
    'NAVI_AMAZON_CLIENT_SECRET': '',
    'NAVI_AMAZON_REDIRECT_URI': '',
    'NAVI_AMAZON_TOKEN_FILE': '/var/lib/castnavidrome/amazon_oauth_token.json',
    'NAVI_AMAZON_SCOPES': 'profile',
    'NAVI_AMAZON_SESSION_FILE': '/var/lib/castnavidrome/amazon_session.json',
    'NAVI_AUTO_RESTART_ON_OAUTH_TOKEN_SAVE': '',

    # Tailscale
    'TS_STATE_DIR': '/var/lib/tailscale',
    'TS_SERVE_CONFIG': '/config/serve.json',
    'TS_USERSPACE': 'false',
}

# Validate required sensitive variables
def validate_sensitive_config():
    """Validate required sensitive configuration variables are set."""
    errors = []
    warnings = []
    
    for var_name, description in REQUIRED_SENSITIVE_VARS.items():
        value = os.getenv(var_name)
        if not value:
            errors.append(f"Required sensitive configuration variable '{var_name}' is not set. {description}")
        else:
            # Log presence without exposing the value
            logger.debug(f"Required sensitive configuration variable '{var_name}' is set")
    
    return errors, warnings

# Load configuration with fallback values
def load_configuration():
    """Load configuration with fallback values and validation."""
    
    # First validate sensitive variables
    errors, warnings = validate_sensitive_config()
    
    # Load optional configuration with defaults
    config = {}
    
    for var_name, default_value in OPTIONAL_CONFIG_VARS.items():
        value = os.getenv(var_name, default_value)
        config[var_name] = value
        
        # Log non-default values for visibility
        if value != default_value:
            logger.debug(f"Configuration variable '{var_name}' set to custom value: '{value}'")
        else:
            logger.debug(f"Configuration variable '{var_name}' using default value: '{value}'")
    
    # Combine errors and warnings from validation
    all_errors = CONFIG_VALIDATION_ERRORS + errors
    all_warnings = CONFIG_VALIDATION_WARNINGS + warnings
    
    # Log all configuration for visibility with proper masking
    logger.info("=== Configuration Summary ===")
    
    # Log required sensitive variables with masking
    for var_name, description in REQUIRED_SENSITIVE_VARS.items():
        value = os.getenv(var_name)
        if value:
            logger.info(f"{var_name}: SET (default: N/A)")
        else:
            logger.error(f"{var_name}: NOT SET - {description}")
    
    # Log optional variables with default/user-set indication
    for var_name, default_value in OPTIONAL_CONFIG_VARS.items():
        value = config.get(var_name, '')
        # Skip variables already logged as required
        if var_name in REQUIRED_SENSITIVE_VARS:
            continue
        
        # Determine if this is a default or custom value
        env_value = os.getenv(var_name)
        is_user_set = env_value is not None and env_value != default_value
        
        # Mask sensitive values
        if var_name in SENSITIVE_CONFIG_VARS:
            display_value = "***" if value else "NOT SET"
        else:
            display_value = value if value else "NOT SET"
        
        if is_user_set:
            logger.info(f"{var_name}: {display_value} (user-set, default: {default_value if default_value else 'N/A'})")
        else:
            logger.info(f"{var_name}: {display_value} (default: {default_value if default_value else 'N/A'})")
    
    logger.info("=== End Configuration Summary ===")
    
    # Report warnings
    for warning in all_warnings:
        logger.warning(f"Configuration Warning: {warning}")
    
    # Exit if there are errors
    if all_errors:
        logger.error("Configuration validation failed with the following errors:")
        for error in all_errors:
            logger.error(f"  - {error}")
        logger.error("Please check your environment variables or docker-compose.yml configuration.")
        raise ValueError(f"Configuration validation failed: {len(all_errors)} error(s) found")
    
    return config

# Load configuration at startup
navidrome_config = load_configuration()

# Set skill ID, this is available on the Alexa Developer Console. defined in .env file
# if this is not set the web service will respond to any skill.
sb.skill_id = os.getenv('NAVI_SKILL_ID')
if sb.skill_id:
    logger.info('Skill ID set')
else:
    logger.warning('No Alexa skill ID configured; the web service will respond to any skill.')

min_song_count = int(os.getenv('NAVI_SONG_COUNT', '50'))
logger.info(f'Minimum song count is set to: {min_song_count}')

navidrome_url = os.getenv('NAVI_URL', '')
logger.info(f'The URL for Navidrome is set to: {navidrome_url}')

navidrome_user = os.getenv('NAVI_USER', '')
logger.info(f'The Navidrome user name is set to: {navidrome_user}')

navidrome_passwd = os.getenv('NAVI_PASS', '')
logger.info('The Navidrome password is set')

navidrome_port = int(os.getenv('NAVI_PORT', '443'))
logger.info(f'The Navidrome port is set to: {navidrome_port}')

navidrome_api_location = os.getenv('NAVI_API_PATH', '/rest')
logger.info(f'The Navidrome API path is set to: {navidrome_api_location}')

navidrome_api_version = os.getenv('NAVI_API_VER', '1.16.1')
logger.info(f'The Navidrome API version is set to: {navidrome_api_version}')

logger.debug('Configuration has been successfully loaded')

# Set log level based on config value
navidrome_log_level = 1

if 'NAVI_DEBUG' in os.environ:
    navidrome_log_level = int(os.getenv('NAVI_DEBUG'))

    if navidrome_log_level == 0:
        # Warnings and higher
        logger.setLevel(logging.WARNING)
        logger.warning('Log level set to WARNING')

    elif navidrome_log_level == 1:
        # Info messages and higher
        logger.setLevel(logging.INFO)
        logger.info('Log level set to INFO')

    elif navidrome_log_level == 2:
        # Debug with request and response interceptors
        logger.setLevel(logging.DEBUG)
        logger.debug('Log level set to DEBUG')

    elif navidrome_log_level == 3:
        # Debug with request / response interceptors and Web GUI
        logger.setLevel(logging.DEBUG)
        logger.debug('Log level set to DEBUG')

    else:
        # Invalid value provided - set to WARNING
        navidrome_log_level = 0
        logger.setLevel(logging.WARNING)
    logger.warning('Log level set to WARNING')

# The play queues are created by the state module, one for every Alexa device
# that sends a request.  They are shareable, so that they can be updated by
# multiple threads to enable larger playlists to be returned in the back
# ground avoiding the Amazon 8 second timeout.
logger.debug('MediaQueue objects are created on demand...')

# Connect to Navidrome
if not navidrome_url:
    raise ValueError("NAVI_URL is not set. Please configure the Navidrome URL in environment variables.")
connection = api.SubsonicConnection(navidrome_url,
                                    navidrome_user,
                                    navidrome_passwd,
                                    navidrome_port,
                                    navidrome_api_location,
                                    navidrome_api_version,
                                    timeout=int(os.getenv('NAVI_API_TIMEOUT', '10')))

try:
    connection.ping()

except:
    raise RuntimeError('Could not connect to SubSonic API!')

# The resolver of the free text search, it caches the artists and the
# genres of the collection
search_resolver = SearchResolver(connection, min_song_count)

# The names of the play lists of the media server, they can be grouped and
# they are spoken in a different way than they are stored
playlist_names = build_playlist_names()
logger.debug('The playlist names are configured with the pattern %s', playlist_names.pattern.pattern)


def translate(handler_input: HandlerInput, key: str, **kwargs) -> str:
    """Get a message of the skill in the language of the request

    The text is sanitised for the SSML standard, so that the characters
    that are reserved in it do not break the speech output.  The
    conjunction that replaces them is the one of the language of the
    request.

    :param handler_input: The Amazon Alexa HandlerInput object
    :param str key: The key of the message
    :param kwargs: The values of the placeholders of the message
    :return: The message in the language of the request
    :rtype: str
    """

    translator = get_translator(handler_input)

    return sanitise_speech_output(translator.t(key, **kwargs), translator.locale)

# Register the modular Alexa handlers (Launch, Help, Audio check, Skill events,
# and interceptors).  Complex playback handlers remain in app.py for now and
# are registered further below.
register_handlers(
    sb,
    connection=connection,
    state=state,
    controller=controller,
    search_resolver=search_resolver,
    playlist_names=playlist_names,
    translate_func=translate,
    skill_display_name=SKILL_DISPLAY_NAME,
    help_overview_key=HELP_OVERVIEW_KEY,
)

# The number of play lists that are read out at once
PLAYLIST_PAGE_SIZE = 10

# A play list is only played if its score is at least this high
PLAYLIST_MATCH_THRESHOLD = 0.6

# If the second best play list is this close to the best one, the user is
# asked which one of them they meant
PLAYLIST_MATCH_AMBIGUITY = 0.15

# The prefix of the ID of a radio stream, it is used to recognise a radio
# stream in the play queue
RADIO_TOKEN_PREFIX = 'radio:'

# The station that is played if the user does not name one
RADIO_DEFAULT_STATION = 'default'

logger.info('castNavidrome Web Service is ready to start!')


def translate(handler_input: HandlerInput, key: str, **kwargs) -> str:
    """Get a message of the skill in the language of the request

    The text is sanitised for the SSML standard, so that the characters
    that are reserved in it do not break the speech output.  The
    conjunction that replaces them is the one of the language of the
    request.

    :param handler_input: The Amazon Alexa HandlerInput object
    :param str key: The key of the message
    :param kwargs: The values of the placeholders of the message
    :return: The message in the language of the request
    :rtype: str
    """

    translator = get_translator(handler_input)

    return sanitise_speech_output(translator.t(key, **kwargs), translator.locale)


#
# Handler Classes
#

class LaunchRequestHandler(AbstractRequestHandler):
    """Handle LaunchRequest and NavigateHomeIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            is_request_type('LaunchRequest')(handler_input) or
            is_intent_name('AMAZON.NavigateHomeIntent')(handler_input)
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In LaunchRequestHandler')

        connection.ping()
        speech = translate(handler_input, 'ready')

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
        speech = translate(handler_input, 'device_not_supported')
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

        text = translate(handler_input, HELP_OVERVIEW_KEY, skill=SKILL_DISPLAY_NAME)
        handler_input.response_builder.speak(text).ask(text)

        return handler_input.response_builder.response


class castNavidromePlayMusicByArtist(AbstractRequestHandler):
    """Handle castNavidromePlayMusicByArtist

    Play a selection of songs for the given artist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayMusicByArtist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayMusicByArtist')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        # Get the requested artist
        artist = get_resolved_slot_value(handler_input, 'artist')

        # Search for an artist
        artist_lookup = connection.search_artist(artist)

        if artist_lookup is None:
            text = translate(handler_input, 'artist_not_found', artist=artist)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            # Get a list of albums by the artist
            artist_album_lookup = connection.albums_by_artist(artist_lookup[0].get('id'))

            # Build a list of songs to play
            song_id_list = connection.build_song_list_from_albums(artist_album_lookup, min_song_count)

            if not song_id_list:
                text = translate(handler_input, 'no_songs_by_artist', artist=artist)
                handler_input.response_builder.speak(text).ask(text)

                return handler_input.response_builder.response

            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

            speech = translate(handler_input, 'playing_music_by_artist', artist=artist)
            logger.info(speech)

            card = {'title': SKILL_DISPLAY_NAME,
                    'text': speech
                    }

            play_queue.shuffle()
            track_details = play_queue.get_next_track()
            return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromePlayAlbumByArtist(AbstractRequestHandler):
    """Handle castNavidromePlayAlbumByArtist

    Play a given album by a given artist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayAlbumByArtist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayAlbumByArtist')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        # Get variables from intent
        artist = get_resolved_slot_value(handler_input, 'artist')
        album = get_resolved_slot_value(handler_input, 'album')

        if artist is not None and album is not None:
            # Play album by artist method
            logger.debug(f'Searching for the album {album} by {artist}')

            # Search for an artist
            artist_lookup = connection.search_artist(artist)

            if artist_lookup is None:
                text = translate(handler_input, 'artist_not_found', artist=artist)
                handler_input.response_builder.speak(text).ask(text)

                return handler_input.response_builder.response

            else:
                artist_album_lookup = connection.albums_by_artist(artist_lookup[0].get('id'))

                # Search the list of dictionaries for the requested album
                # Strings are all converted to lower case to minimise matching errors
                result = [album_result for album_result in artist_album_lookup if album_result.get('name').lower() == album.lower()]

                if not result:
                    text = translate(handler_input, 'album_by_artist_not_found', album=album, artist=artist)
                    handler_input.response_builder.speak(text).ask(text)

                    return handler_input.response_builder.response

                # At this point we have found an album that matches
                song_id_list = connection.build_song_list_from_albums(result, -1)

                if not song_id_list:
                    text = translate(handler_input, 'no_songs_on_album', album=album)
                    handler_input.response_builder.speak(text).ask(text)

                    return handler_input.response_builder.response

                play_queue.clear()

                # Work around the Amazon / Alexa 8 second timeout.
                state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

                speech = translate(handler_input, 'playing_album_by_artist', album=album, artist=artist)
                logger.info(speech)
                card = {'title': SKILL_DISPLAY_NAME,
                        'text': speech
                        }
                track_details = play_queue.get_next_track()

                return controller.start_playback('play', speech, card, track_details, handler_input)

        elif artist is None and album:
            # Play album method
            logger.debug(f'Searching for the album {album}')

            result = connection.search_album(album)

            if result is None:
                text = translate(handler_input, 'album_not_found', album=album)
                handler_input.response_builder.speak(text).ask(text)

                return handler_input.response_builder.response

            else:
                song_id_list = connection.build_song_list_from_albums(result, -1)

                if not song_id_list:
                    text = translate(handler_input, 'no_songs_on_album', album=album)
                    handler_input.response_builder.speak(text).ask(text)

                    return handler_input.response_builder.response

                play_queue.clear()

                # Work around the Amazon / Alexa 8 second timeout.
                state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

                speech = translate(handler_input, 'playing_album', album=album)
                logger.info(speech)
                card = {'title': SKILL_DISPLAY_NAME,
                        'text': speech
                        }
                track_details = play_queue.get_next_track()

                return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromePlaySongByArtist(AbstractRequestHandler):
    """Handle the castNavidromePlaySongByArtist intent

    Play the given song by the given artist if it exists in the
    collection.
    """

    # When it is true, the skill plays the track without an answer, so
    # that the title and the artist are not read out.
    quiet = False

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlaySongByArtist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlaySongByArtist')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Get variables from intent
        artist = get_resolved_slot_value(handler_input, 'artist')
        song = get_resolved_slot_value(handler_input, 'song')

        logger.debug(f'Searching for the song {song} by {artist}')

        # Search for the artist
        artist_lookup = connection.search_artist(artist)

        if artist_lookup is None:
            text = translate(handler_input, 'artist_not_found', artist=artist)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            artist_id = artist_lookup[0].get('id')

            # Search for song
            song_list = connection.search_song(song)

            # Search for song by given artist.
            song_dets = [item.get('id') for item in song_list if item.get('artistId') == artist_id]

            if not song_dets:
                text = translate(handler_input, 'song_not_found', song=song, artist=artist)
                handler_input.response_builder.speak(text).ask(text)

                return handler_input.response_builder.response

            play_queue.clear()
            controller.enqueue_songs(connection, play_queue, song_dets)

            track_details = play_queue.get_next_track()

            if self.quiet:
                # The track is played without an answer of the skill, the
                # title and the artist are not read out.
                logger.info(f'Playing track quietly: {track_details.title} by: {track_details.artist}')

                return controller.start_playback('play', None, None, track_details, handler_input)

            speech = translate(handler_input, 'playing_song_by_artist', song=song, artist=artist)
            logger.info(speech)
            card = {'title': SKILL_DISPLAY_NAME,
                    'text': speech
                    }

            return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromePlaySongByArtistQuiet(castNavidromePlaySongByArtist):
    """Handle the castNavidromePlaySongByArtistQuiet intent

    Play the given song by the given artist, but without an answer of the
    skill.  The media renderers use it for the tracks that they start on
    their own, when the previous track has ended.
    """

    quiet = True

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlaySongByArtistQuiet')(handler_input)


class castNavidromePlayPlaylist(AbstractRequestHandler):
    """Handle castNavidromePlayPlaylist

    Play the given playlist
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayPlaylist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayPlaylist')
        device_id = state.get_device_id(handler_input)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        # Get the requested playlist
        playlist = get_resolved_slot_value(handler_input, 'playlist')

        # Search for a playlist
        playlist_id, playlist_name, alternatives = find_playlist(playlist)

        if playlist_id is None:
            if alternatives:
                return speak_playlist_choices(handler_input, alternatives)

            text = translate(handler_input, 'playlist_not_found', playlist=playlist)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        return play_playlist(handler_input, playlist_id, playlist_name)


class castNavidromePlayMusicByGenre(AbstractRequestHandler):
    """ Play songs from the given genre

    50 tracks from the given genre are shuffled and played
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayMusicByGenre')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayMusicByGenre')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        # Get the requested genre
        genre = get_resolved_slot_value(handler_input, 'genre')

        song_id_list = connection.build_song_list_from_genre(genre, min_song_count)

        if not song_id_list:
            text = translate(handler_input, 'no_genre_songs', genre=genre)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            random.shuffle(song_id_list)
            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

            speech = translate(handler_input, 'playing_genre', genre=genre)
            logger.info(speech)
            card = {'title': SKILL_DISPLAY_NAME,
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromePlayMusicRandom(AbstractRequestHandler):
    """Handle the castNavidromePlayMusicRandom intent

    Play a random selection of music.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayMusicRandom')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayMusicRandom')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        song_id_list = connection.build_random_song_list(min_song_count)

        if not song_id_list:
            text = translate(handler_input, 'no_songs_in_collection')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            random.shuffle(song_id_list)
            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

            speech = translate(handler_input, 'playing_random_music')
            logger.info(speech)
            card = {'title': SKILL_DISPLAY_NAME,
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromePlayFavouriteSongs(AbstractRequestHandler):
    """Handle the castNavidromePlayFavouriteSongs intent

    Play all starred / liked songs, songs are automatically shuffled.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayFavouriteSongs')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayFavouriteSongs')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        song_id_list = connection.build_song_list_from_favourites()

        if not song_id_list:
            text = translate(handler_input, 'no_favourite_songs')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        else:
            random.shuffle(song_id_list)
            play_queue.clear()

            # Work around the Amazon / Alexa 8 second timeout.
            state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

            speech = translate(handler_input, 'playing_favourites')
            logger.info(speech)
            card = {'title': SKILL_DISPLAY_NAME,
                    'text': speech
                    }
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromeRandomiseQueue(AbstractRequestHandler):
    """Handle castNavidromeRandomiseQueue Intent

    Shuffle the current play queue
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeRandomiseQueue')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeRandomiseQueue Handler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        play_queue.shuffle()
        play_queue.sync()

        return handler_input.response_builder.response


class castNavidromeSongDetails(AbstractRequestHandler):
    """Handle castNavidromeSongDetails Intent

    Returns information on the track that is currently playing
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeSongDetails')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeSongDetails Handler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        current_track = play_queue.get_current_track()

        text = translate(handler_input, 'now_playing',
                         title=current_track.title,
                         artist=current_track.artist,
                         album=current_track.album)
        handler_input.response_builder.speak(text)

        return handler_input.response_builder.response


class castNavidromeStarSong(AbstractRequestHandler):
    """Handle castNavidromeStarSong Intent

    Star / favourite the current song
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeStarSong')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeStarSong Handler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        current_track = play_queue.get_current_track()

        song_id = current_track.id
        connection.star_entry(song_id, 'song')

        return handler_input.response_builder.response


class castNavidromeUnstarSong(AbstractRequestHandler):
    """Handle castNavidromeUnstarSong Intent

    Star / favourite the current song
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeUnstarSong')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeUnstarSong Handler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        current_track = play_queue.get_current_track()

        song_id = current_track.id
        connection.star_entry(song_id, 'song')
        connection.unstar_entry(song_id, 'song')

        return handler_input.response_builder.response

class castNavidromeShufflePlaylist(AbstractRequestHandler):
    """Handle castNavidromeShufflePlaylist

    Play the given playlist in random order

    Ported from krimil/asknavidrome and johnpaulgosling/asknavidrome (MIT),
    see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeShufflePlaylist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeShufflePlaylist')
        device_id = state.get_device_id(handler_input)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        # Get the requested playlist
        playlist = get_resolved_slot_value(handler_input, 'playlist')

        playlist_id, playlist_name, alternatives = find_playlist(playlist)

        if playlist_id is None:
            if alternatives:
                return speak_playlist_choices(handler_input, alternatives)

            text = translate(handler_input, 'playlist_not_found', playlist=playlist)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        return play_playlist(handler_input, playlist_id, playlist_name, shuffle=True)


class castNavidromePlaySong(AbstractRequestHandler):
    """Handle the castNavidromePlaySong intent

    Play the given song, the artist is not needed.

    Ported from djh20/asknavidrome, greeninja/asknavidrome,
    johnpaulgosling/asknavidrome and locqust/asknavidrome (MIT),
    see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlaySong')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlaySong')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Get the requested song
        song = get_resolved_slot_value(handler_input, 'song')

        logger.debug(f'Searching for the song {song}')

        song_list = connection.search_song(song)

        if not song_list:
            text = translate(handler_input, 'song_not_found', song=song)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        song_dets = [item.get('id') for item in song_list if item.get('id')]

        if not song_dets:
            text = translate(handler_input, 'song_not_found', song=song)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        play_queue.clear()
        controller.enqueue_songs(connection, play_queue, song_dets)

        speech = translate(handler_input, 'playing_song', song=song)
        logger.info(speech)
        card = {'title': SKILL_DISPLAY_NAME,
                'text': speech
                }
        track_details = play_queue.get_next_track()

        return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromePlayRadio(AbstractRequestHandler):
    """Handle the castNavidromePlayRadio intent

    Play a live radio station.  A radio stream is endless, so it is not
    part of a play list and it cannot be skipped.

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayRadio')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayRadio')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        state.stop_background_process(device_id)

        station = get_resolved_slot_value(handler_input, 'station')

        if not station:
            station = RADIO_DEFAULT_STATION

        url = radio_stream_url(station)

        if not url:
            text = translate(handler_input, 'no_radio_station')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        track = Track(id=RADIO_TOKEN_PREFIX + station,
                      title=station,
                      artist='Live radio',
                      uri=url)

        play_queue.clear()
        play_queue.set_current_track(track)

        speech = translate(handler_input, 'playing_radio_station', station=station)
        logger.info(speech)
        card = {'title': SKILL_DISPLAY_NAME,
                'text': speech
                }

        return controller.start_playback('play', speech, card, track, handler_input)


class castNavidromePlaySearch(AbstractRequestHandler):
    """Handle the castNavidromePlaySearch intent

    Play whatever the free text query of the user matches, it can be a
    song, an album, an artist, a genre or a play list.

    Ported from bickns/asknavidrome and gsidhu/asknavidrome (MIT),
    see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlaySearch')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlaySearch')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        query = get_resolved_slot_value(handler_input, 'query')

        if not query:
            text = translate(handler_input, 'did_not_get_that')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        song_id_list, description = search_resolver.resolve(query)

        if not song_id_list:
            text = translate(handler_input, 'nothing_found_for_query', query=query)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        play_queue.clear()

        # Work around the Amazon / Alexa 8 second timeout.
        state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

        speech = translate(handler_input, 'playing_description', description=description)
        logger.info(speech)
        card = {'title': SKILL_DISPLAY_NAME,
                'text': speech
                }
        track_details = play_queue.get_next_track()

        return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromePlayMusicByDecade(AbstractRequestHandler):
    """Handle castNavidromePlayMusicByDecade

    Play the music of a decade, optionally of a genre

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromePlayMusicByDecade')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromePlayMusicByDecade')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        # Check if a background process is already running, if it is then terminate the process
        # in favour of the new process.
        state.stop_background_process(device_id)

        decade = get_resolved_slot_value(handler_input, 'decade')
        genre = get_resolved_slot_value(handler_input, 'genre')

        from_year, to_year = decades.get_range(decade)

        if not from_year:
            text = translate(handler_input, 'decade_not_understood', decade=decade)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        albums = connection.get_albums_by_year(from_year, to_year)

        if genre:
            albums = [album for album in albums
                      if genre.lower() in (album.get('genre') or '').lower()]

        if not albums:
            text = translate(handler_input, 'no_music_from_decade', decade=decade)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        song_id_list = connection.build_song_list_from_albums(albums, min_song_count)

        if not song_id_list:
            text = translate(handler_input, 'no_music_from_decade', decade=decade)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        random.shuffle(song_id_list)
        play_queue.clear()

        # Work around the Amazon / Alexa 8 second timeout.
        state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

        speech = translate(handler_input, 'playing_decade', decade=decade)
        logger.info(speech)
        card = {'title': SKILL_DISPLAY_NAME,
                'text': speech
                }
        track_details = play_queue.get_next_track()

        return controller.start_playback('play', speech, card, track_details, handler_input)


class castNavidromeListPlaylists(AbstractRequestHandler):
    """Handle castNavidromeListPlaylists

    List the play lists of the collection

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeListPlaylists')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeListPlaylists')

        playlists = connection.get_all_playlists()
        names = [item.get('name') for item in playlists if item.get('name')]

        if not names:
            text = translate(handler_input, 'no_playlists')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        handler_input.session_attributes['playlist_names'] = names
        handler_input.session_attributes['playlist_offset'] = 0

        speech = speak_playlist_page(handler_input, playlist_names.spoken_list(names), 0)
        logger.info(speech)
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response


class castNavidromeHearMorePlaylists(AbstractRequestHandler):
    """Handle castNavidromeHearMorePlaylists

    Read the next page of the play lists of the collection

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeHearMorePlaylists')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeHearMorePlaylists')

        names = handler_input.session_attributes.get('playlist_names')

        if not names:
            text = translate(handler_input, 'no_more_playlists')
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        offset = handler_input.session_attributes.get('playlist_offset', 0)
        offset = offset + PLAYLIST_PAGE_SIZE

        handler_input.session_attributes['playlist_offset'] = offset

        speech = speak_playlist_page(handler_input, playlist_names.spoken_list(names), offset)
        logger.info(speech)
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response


class castNavidromeFindPlaylist(AbstractRequestHandler):
    """Handle castNavidromeFindPlaylist

    Find a play list by a keyword, a mood or a genre

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeFindPlaylist')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeFindPlaylist')

        query = get_resolved_slot_value(handler_input, 'query')

        scored = connection.search_playlists_by_keyword(query)

        if not scored:
            text = translate(handler_input, 'playlist_not_found_by_query', query=query)
            handler_input.response_builder.speak(text).ask(text)

            return handler_input.response_builder.response

        best_score, best_id, best_name = scored[0]

        # The result is only played if it is a clear winner, otherwise the
        # user is asked which one of the candidates they meant.
        if len(scored) == 1 or (best_score == 1.0 and (best_score - scored[1][0]) > 0.3):
            return play_playlist(handler_input, best_id, best_name)

        alternatives = [(item[1], item[2]) for item in scored[:3]]

        return speak_playlist_choices(handler_input, alternatives)


class castNavidromeHelpTopic(AbstractRequestHandler):
    """Handle castNavidromeHelpTopic

    Answer a question about a topic of the skill

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name('castNavidromeHelpTopic')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In castNavidromeHelpTopic')

        topic = get_resolved_slot_value(handler_input, 'topic')

        if topic:
            topic = HELP_TOPIC_ALIASES.get(topic, topic)

        if not topic:
            topic = classify_help_topic(handler_input)

        help_key = HELP_TOPICS.get(topic)

        if help_key is None:
            help_key = HELP_OVERVIEW_KEY

        speech = translate(handler_input, help_key, skill=SKILL_DISPLAY_NAME)
        logger.info(speech)
        handler_input.response_builder.speak(speech).ask(speech)

        return handler_input.response_builder.response


#
# AudioPlayer Handlers
#


class PlaybackStartedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackStarted Directive received.

    Confirming that the requested audio file began playing.
    Do not send any specific response.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackStarted')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackStartedHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)
        logger.info('Playback started')

        play_queue.set_playback_active(True)

        current_track = play_queue.get_current_track()

        if is_radio_track(current_track):
            logger.debug('A radio stream is playing, it is not reported to Navidrome')
            return handler_input.response_builder.response

        # The now playing entry of Navidrome gets a client name per device,
        # so that the devices do not overwrite each other.  A media
        # renderer reports the track under the name of the client that
        # asked for it, in that case the track must not be reported a
        # second time, otherwise Navidrome shows it twice.
        try:
            if not connection.is_now_playing_reported_by_other_client(current_track.id):
                connection.now_playing(current_track.id, device_id)
        except Exception as error:
            logger.warning('Could not report the now playing track: %s', error)

        return handler_input.response_builder.response


class PlaybackStoppedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackStopped Directive received.

    Confirming that the requested audio file stopped playing.
    Do not send any specific response.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackStopped')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackStoppedHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        play_queue.set_playback_active(False)

        # store the current offset for later resumption
        play_queue.set_current_track_offset(handler_input.request_envelope.request.offset_in_milliseconds)

        current_track = play_queue.get_current_track()
        logger.debug(f'Stored track offset of: {current_track.offset} ms for {current_track.title}')
        logger.info('Playback stopped')

        return handler_input.response_builder.response


class PlaybackNearlyFinishedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackNearlyFinished Directive received.

    Replacing queue with the URL again. This should not happen on live streams.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackNearlyFinished')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackNearlyFinishedHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)
        logger.info('Queuing next track...')
        track_details = play_queue.enqueue_next_track()

        if track_details is None:
            # The play queue is exhausted, there is nothing left to play
            logger.warning('The play queue is empty, the playback ends here')
            return handler_input.response_builder.response

        return controller.start_playback('continue', None, None, track_details, handler_input)


class PlaybackFinishedHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackFinished Directive received.

    Confirming that the requested audio file completed playing.
    Do not send any specific response.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackFinished')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackFinishedHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        current_track = play_queue.get_current_track()

        if is_radio_track(current_track):
            logger.debug('A radio stream ended, it is not scrobbled')
            return handler_input.response_builder.response

        # py-sonic converts this UNIX timestamp to milliseconds for the API.
        timestamp = datetime.now().timestamp()
        connection.scrobble(current_track.id, timestamp)

        if play_queue.get_queue_count() > 0:
            play_queue.get_next_track()
        else:
            logger.warning('The play queue is empty, the playback has ended')

        return handler_input.response_builder.response


class PausePlaybackHandler(AbstractRequestHandler):
    """Handler for stopping audio.

    Handles Stop, Cancel and Pause Intents and PauseCommandIssued event.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('AMAZON.StopIntent')(handler_input) or
                is_intent_name('AMAZON.CancelIntent')(handler_input) or
                is_intent_name('AMAZON.PauseIntent')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PausePlaybackHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)
        play_queue.set_playback_active(False)
        play_queue.sync()

        return controller.stop(handler_input)


class ResumePlaybackHandler(AbstractRequestHandler):
    """Handler for resuming audio on different events.

    Handles PlayAudio Intent, Resume Intent.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('AMAZON.ResumeIntent')(handler_input) or
                is_intent_name('PlayAudio')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In ResumePlaybackHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        current_track = play_queue.get_current_track()

        if current_track.offset > 0:
            # There is a paused track, continue
            logger.info('Resuming ' + str(current_track.title))
            logger.info('Offset ' + str(current_track.offset))

            return controller.start_playback('play', None, None, current_track, handler_input)

        elif play_queue.get_queue_count() > 0 and current_track.offset == 0:
            # No paused tracks but tracks in queue
            logger.info('Resuming - There was no paused track, getting next track from queue')
            track_details = play_queue.get_next_track()

            return controller.start_playback('play', None, None, track_details, handler_input)

        else:
            # Nothing is paused and the queue is empty
            logger.warning('There is nothing to resume, the play queue is empty')
            speech = translate(handler_input, 'nothing_to_resume')
            handler_input.response_builder.speak(speech)

            return handler_input.response_builder.response


class NextPlaybackHandler(AbstractRequestHandler):
    """Handle NextIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('AMAZON.NextIntent')(handler_input) or
                is_request_type('PlaybackController.NextCommandIssued')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In NextPlaybackHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        if is_radio_track(play_queue.get_current_track()):
            logger.info('A radio stream is playing, it cannot be skipped')
            speech = translate(handler_input, 'radio_cannot_be_skipped')
            handler_input.response_builder.speak(speech)

            return handler_input.response_builder.response

        if play_queue.get_queue_count() == 0:
            logger.warning('The play queue is empty, there is no track to skip to')
            speech = translate(handler_input, 'no_more_tracks_in_queue')
            handler_input.response_builder.speak(speech)

            return handler_input.response_builder.response

        track_details = play_queue.get_next_track()

        # Set the offset to 0 as we are skipping we want to start at the beginning
        track_details.offset = 0

        return controller.start_playback('play', None, None, track_details, handler_input)


class PreviousPlaybackHandler(AbstractRequestHandler):
    """Handle PreviousIntent"""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (is_intent_name('AMAZON.PreviousIntent')(handler_input) or
                is_request_type('PlaybackController.PreviousCommandIssued')(handler_input))

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PreviousPlaybackHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        if is_radio_track(play_queue.get_current_track()):
            logger.info('A radio stream is playing, it cannot be skipped')
            speech = translate(handler_input, 'radio_cannot_be_skipped')
            handler_input.response_builder.speak(speech)

            return handler_input.response_builder.response

        if play_queue.get_history_count() == 0:
            logger.warning('The play history is empty, there is no previous track')
            speech = translate(handler_input, 'no_previous_track')
            handler_input.response_builder.speak(speech)

            return handler_input.response_builder.response

        track_details = play_queue.get_previous_track()

        # Set the offset to 0 as we are skipping we want to start at the beginning
        track_details.offset = 0

        return controller.start_playback('play', None, None, track_details, handler_input)


class PlaybackFailedEventHandler(AbstractRequestHandler):
    """AudioPlayer.PlaybackFailed Directive received.

    Logging the error and restarting playing with no output speech.
    """

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type('AudioPlayer.PlaybackFailed')(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        logger.debug('In PlaybackFailedHandler')
        device_id = state.get_device_id(handler_input)
        play_queue = state.get_play_queue(device_id)

        current_track = play_queue.get_current_track()
        song_id = current_track.id

        # Log failure and track ID
        logger.error(f'Playback Failed: {handler_input.request_envelope.request.error}')
        logger.error(f'Failed playing track with ID: {song_id}')

        if play_queue.get_queue_count() == 0:
            logger.warning('The play queue is empty, there is no track to skip to')
            return handler_input.response_builder.response

        # Skip to the next track instead of stopping
        track_details = play_queue.get_next_track()

        # Set the offset to 0 as we are skipping we want to start at the beginning
        track_details.offset = 0

        return controller.start_playback('play', None, None, track_details, handler_input)


#
# Exception Handers
#




#
# Request Interceptors
#


class LoggingRequestInterceptor(AbstractRequestInterceptor):
    """Intercept all requests

    Intercepts all requests sent to the skill and prints them in the log

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
        logger.debug('Response metadata: directives=%d has_output_speech=%s should_end_session=%s',
                     directives, has_output_speech, should_end_session)

#
# Functions
#


def queue_worker_thread(connection: object, play_queue: object, song_id_list: list) -> None:
    """Media queue worker

    This function allows media queues to be populated in the background enabling multithreading
    and increasing skill response times.

    :param connection: A SubSonic API connection object
    :type connection: object
    :param play_queue: A MediaQueue object
    :type play_queue: object
    :param song_id_list: A list containing Navidrome song IDs
    :type song_id_list: list
    """

    logger.debug('In playlist processing thread!')
    controller.enqueue_songs(connection, play_queue, song_id_list)
    play_queue.sync()
    logger.debug('Finished playlist processing!')


def enqueue_initial_tracks(song_id_list: list, play_queue: object) -> object:
    """Add the first tracks of a play list and queue the rest in the background

    Works around the Amazon / Alexa 8 second timeout by adding the first two
    tracks to the queue synchronously and adding the remaining ones in a
    background process.  A play list with no or only a single track is added
    completely, so that no IndexError is raised for it.

    Ported from nigelg/asknavidrome (MIT), see CREDITS.md.

    :param song_id_list: A list containing Navidrome song IDs
    :param play_queue: The play queue of the device
    :return: The background process, or None if no process was needed
    """

    first_tracks, remaining_tracks = queue_filler.split_initial_tracks(song_id_list)

    if not first_tracks:
        logger.warning('There are no tracks to enqueue')
        return None

    controller.enqueue_songs(connection, play_queue, first_tracks)

    # If a track is currently playing, the first new track has to be chained
    # to it, otherwise Amazon rejects the ENQUEUE directive because the
    # expected previous token does not match the track that is playing.
    if play_queue.is_playback_active():
        current_track_id = play_queue.get_current_track().id

        if current_track_id:
            play_queue.set_first_previous_id(current_track_id)

    if not remaining_tracks:
        return None

    background_process = Process(target=queue_worker_thread, args=(connection, play_queue, remaining_tracks))
    background_process.start()

    return background_process


def find_playlist(term: str) -> tuple:
    """Find the play list that the user meant

    The play lists are ranked, so that a name that is not written exactly as
    it is said is found as well.  If two play lists are almost equally good
    matches, the user is asked which one of them they meant.

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

    :param str term: The name of the play list as it was said
    :return: A tuple of the ID of the play list, its name and the
             alternatives, if the match is ambiguous
    :rtype: tuple
    """

    scored = connection.rank_playlists(term, playlist_names.match_forms)

    if not scored:
        return None, None, []

    best_score, best_id, best_name = scored[0]

    if best_score < PLAYLIST_MATCH_THRESHOLD:
        return None, None, []

    if len(scored) > 1:
        second_score = scored[1][0]

        if second_score >= PLAYLIST_MATCH_THRESHOLD and (best_score - second_score) < PLAYLIST_MATCH_AMBIGUITY:
            alternatives = [(item[1], item[2]) for item in scored[:3]]

            return None, None, alternatives

    return best_id, best_name, []


def speak_playlist_choices(handler_input: HandlerInput, alternatives: list) -> Response:
    """Ask the user which play list they meant

    The candidates are stored in the session, so that the user can pick one
    of them with a short answer.

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

    :param handler_input: The Amazon Alexa HandlerInput object
    :param alternatives: A list of the IDs and the names of the candidates
    :return: The response of the skill
    :rtype: Response
    """

    names = [name for _, name in alternatives]
    spoken = playlist_names.spoken_list(names)

    translator = get_translator(handler_input)

    if len(spoken) > 1:
        choices = ', '.join(spoken[:-1]) + f' {translator.conjunction("or")} ' + spoken[-1]
    else:
        choices = spoken[0] if spoken else ''

    speech = translate(handler_input, 'did_you_mean', choices=choices)
    logger.info(speech)

    handler_input.session_attributes['playlist_choices'] = alternatives
    handler_input.response_builder.speak(speech).ask(speech)

    return handler_input.response_builder.response


def play_playlist(handler_input: HandlerInput, playlist_id: str, playlist_name: str, shuffle: bool = False) -> Response:
    """Start the playback of a play list

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

    :param handler_input: The Amazon Alexa HandlerInput object
    :param str playlist_id: The ID of the play list
    :param str playlist_name: The name of the play list
    :param bool shuffle: True if the play list is played in random order
    :return: The response of the skill
    :rtype: Response
    """

    device_id = state.get_device_id(handler_input)
    play_queue = state.get_play_queue(device_id)

    state.stop_background_process(device_id)

    song_id_list = connection.build_song_list_from_playlist(playlist_id)

    if not song_id_list:
        text = translate(handler_input, 'playlist_without_songs', playlist=playlist_name)
        handler_input.response_builder.speak(text).ask(text)

        return handler_input.response_builder.response

    if shuffle:
        random.shuffle(song_id_list)

    play_queue.clear()

    # Work around the Amazon / Alexa 8 second timeout.
    state.set_background_process(device_id, enqueue_initial_tracks(song_id_list, play_queue))

    speech = translate(handler_input, 'playing_playlist', playlist=playlist_name)
    logger.info(speech)
    card = {'title': SKILL_DISPLAY_NAME,
            'text': speech
            }
    track_details = play_queue.get_next_track()

    return controller.start_playback('play', speech, card, track_details, handler_input)


def speak_playlist_page(handler_input: HandlerInput, spoken_names: list, offset: int) -> str:
    """Build the text of a page of play lists

    The text is built in the language of the request.

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

    :param handler_input: The Amazon Alexa HandlerInput object
    :param spoken_names: The spoken names of all the play lists
    :param offset: The number of play lists that were already read out
    :return: The text of the page
    :rtype: str
    """

    translator = get_translator(handler_input)

    page = spoken_names[offset:offset + PLAYLIST_PAGE_SIZE]

    if not page:
        return sanitise_speech_output(translator.t('no_more_playlists'), translator.locale)

    text = translator.t('playlists_list', page=', '.join(page))

    if offset + PLAYLIST_PAGE_SIZE < len(spoken_names):
        text += '. ' + translator.t('playlists_list_more')

    return sanitise_speech_output(text, translator.locale)


def classify_help_topic(handler_input: HandlerInput) -> str:
    """Guess the topic of a help request from its wording

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

    :param handler_input: The Amazon Alexa HandlerInput object
    :return: The key of the topic or an empty string
    :rtype: str
    """

    try:
        slots = handler_input.request_envelope.request.intent.slots
    except AttributeError:
        return ''

    words = ' '.join(slot.value or '' for slot in slots.values()).lower()

    if any(word in words for word in ('playlist', 'playlists', 'wiedergabeliste', 'wiedergabelisten', 'stimmung',
                                      'mood', 'lista', 'listas', 'ánimo', 'ambiance', 'umore', 'clima')):
        return 'finding_playlists'

    if any(word in words for word in ('control', 'pause', 'skip', 'shuffle', 'resume', 'stop', 'steuer', 'steuern',
                                      'weiter', 'controles', 'contrôle', 'commande', 'lecture', 'pausa',
                                      'siguiente', 'anterior', 'comandi', 'riproduzione', 'comandos',
                                      'reprodução')):
        return 'playback_controls'

    if any(word in words for word in ('music', 'play', 'song', 'album', 'artist', 'musik', 'lied', 'lieder',
                                      'interpret', 'música', 'canción', 'álbum', 'reproducir', 'chanson',
                                      'morceau', 'brano', 'canção')):
        return 'playing_music'

    return ''



def radio_stream_url(station: str) -> str:
    """Build the URL of a radio station

    The URLs of the stations are not part of the code, they are read from
    the environment, so that no secret path ends up in the log or in the
    source code.

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

    :param str station: The ID of the station
    :return: The URL of the stream or an empty string if it is not configured
    :rtype: str
    """

    stations_url = os.getenv('NAVI_RADIO_STATIONS_URL')

    if stations_url:
        return f'{stations_url.rstrip("/")}/{station}.mp3'

    if station == RADIO_DEFAULT_STATION:
        return os.getenv('NAVI_RADIO_URL', '')

    return ''


def is_radio_track(track) -> bool:
    """Check if the given track is a radio stream

    Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

    :param track: The track object
    :return: True if the track is a radio stream
    :rtype: bool
    """

    if track is None:
        return False

    return str(getattr(track, 'id', '')).startswith(RADIO_TOKEN_PREFIX)


# Register Intent Handlers
sb.add_request_handler(castNavidromePlayMusicByArtist())
sb.add_request_handler(castNavidromePlayAlbumByArtist())
sb.add_request_handler(castNavidromePlaySongByArtist())
sb.add_request_handler(castNavidromePlaySongByArtistQuiet())
sb.add_request_handler(castNavidromePlayPlaylist())
sb.add_request_handler(castNavidromePlayFavouriteSongs())
sb.add_request_handler(castNavidromePlayMusicByGenre())
sb.add_request_handler(castNavidromePlayMusicRandom())
sb.add_request_handler(castNavidromeRandomiseQueue())
sb.add_request_handler(castNavidromeShufflePlaylist())
sb.add_request_handler(castNavidromePlaySong())
sb.add_request_handler(castNavidromePlayMusicByDecade())
sb.add_request_handler(castNavidromePlaySearch())
sb.add_request_handler(castNavidromePlayRadio())
sb.add_request_handler(castNavidromeListPlaylists())
sb.add_request_handler(castNavidromeHearMorePlaylists())
sb.add_request_handler(castNavidromeFindPlaylist())
sb.add_request_handler(castNavidromeHelpTopic())
sb.add_request_handler(castNavidromeSongDetails())
sb.add_request_handler(castNavidromeStarSong())
sb.add_request_handler(castNavidromeUnstarSong())

# Register AutoPlayer Handlers
sb.add_request_handler(PlaybackStartedHandler())
sb.add_request_handler(PlaybackStoppedHandler())
sb.add_request_handler(PlaybackNearlyFinishedHandler())
sb.add_request_handler(PlaybackFinishedHandler())
sb.add_request_handler(PausePlaybackHandler())
sb.add_request_handler(NextPlaybackHandler())
sb.add_request_handler(PreviousPlaybackHandler())
sb.add_request_handler(ResumePlaybackHandler())
sb.add_request_handler(PlaybackFailedEventHandler())


# Register Exception Handlers
sb.add_exception_handler(SystemExceptionHandler())
sb.add_exception_handler(GeneralExceptionHandler())

# Make the verification of the certificate chain of a request robust, the
# Amazon SDK fails with an internal server error if a certificate of the
# chain is broken.
install_certificate_chain_workaround()

sa = SkillAdapter(skill=sb.create(), skill_id='test', app=app)
sa.register(app=app, route='/')

# Health check endpoint for the Docker HEALTHCHECK and the docker-compose
# healthcheck.  The Alexa skill dispatch is registered for POST only, so a
# plain GET on "/" would otherwise answer with 405.
@app.route('/', methods=['GET'])
def health_check():
    return 'castNavidrome is running', 200

#alexa bridge endpoints
def authorize_alexa_api():
    expected_key = os.getenv('NAVI_ALEXA_API_KEY')
    if not expected_key:
        return jsonify({'error': 'Alexa control API is not configured.'}), 503

    supplied_key = request.headers.get('X-API-Key', '')
    if not hmac.compare_digest(supplied_key, expected_key):
        return jsonify({'error': 'Unauthorized.'}), 401

    return None


def _schedule_container_restart(delay: float = 2.0) -> None:
    """Beendet den Hauptprozess nach einer Verzögerung, sodass Docker Compose
    (restart: unless-stopped) den Container automatisch neu startet.

    Die Verzögerung gibt dem HTTP-Client Zeit, die Antwort zu empfangen, bevor
    der Prozess beendet wird.
    """

    def _restart() -> None:
        time.sleep(delay)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            pass

    threading.Thread(target=_restart, daemon=True).start()


def get_alexa_remote_client():
    domain = os.getenv('NAVI_ALEXA_DOMAIN', 'amazon.com')
    if os.getenv('NAVI_AMAZON_CLIENT_ID'):
        # Authenticate with OAuth 2.0 (Login with Amazon) access/refresh tokens.
        session = AmazonOAuthSession(domain=domain)
        # Still load cookies from file for Alexa Remote API (which requires cookies)
        cookie_file = os.getenv('NAVI_ALEXA_COOKIE_FILE')
        return AlexaTextCommandClient(cookie_file, domain=domain, session=session)

    cookie_file = os.getenv('NAVI_ALEXA_COOKIE_FILE')
    if not cookie_file:
        raise AlexaRemoteError('NAVI_ALEXA_COOKIE_FILE is not configured.')

    return AlexaTextCommandClient(
        cookie_file,
        domain=domain,
    )


# Validate OAuth session at startup
if os.getenv('NAVI_AMAZON_CLIENT_ID'):
    _oauth_session = AmazonOAuthSession(domain=os.getenv('NAVI_ALEXA_DOMAIN', 'amazon.com'))
    if not _oauth_session.is_valid():
        logger.warning(
            'No valid Amazon OAuth tokens found. Open /api/alexa/amazon/login '
            'to authenticate before using the Alexa API.'
        )


@app.route('/api/alexa/amazon/login')
def amazon_login():
    """Start the OAuth 2.0 authorization code flow with Login with Amazon.

    Redirects the end user to Amazon so they can sign in and consent.  A
    CSRF state value is stored in a cookie and validated in the callback.
    """
    domain = os.getenv('NAVI_ALEXA_DOMAIN', 'amazon.com')
    session = AmazonOAuthSession(domain=domain)
    try:
        auth_url, state = session.authorization_url()
    except AmazonOAuthCredentialsMissing as error:
        return jsonify({'error': str(error)}), 503
    print(f'DEBUG amazon_login: auth_url={auth_url}', flush=True)
    response = redirect(auth_url)
    response.set_cookie('amazon_oauth_state', state, max_age=600,
                        httponly=True, samesite='Lax')
    return response


@app.route('/api/alexa/amazon/callback')
def amazon_callback():
    """OAuth 2.0 callback: exchange the authorization code for tokens."""
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    if error:
        return jsonify({'error': f'Amazon authorization declined: {error}'}), 400
    if not code or not state:
        return jsonify({'error': 'Missing authorization code or state.'}), 400
    expected_state = request.cookies.get('amazon_oauth_state')
    if not expected_state or not hmac.compare_digest(state, expected_state):
        return jsonify({'error': 'Invalid OAuth state parameter.'}), 400
    domain = os.getenv('NAVI_ALEXA_DOMAIN', 'amazon.com')
    session = AmazonOAuthSession(domain=domain)
    try:
        session.exchange_code_for_tokens(code)
    except AmazonOAuthError as error:
        return jsonify({'error': str(error)}), 400
    response = jsonify({'status': 'ok',
                        'message': 'Amazon OAuth tokens stored. The Alexa API is now authenticated.'})
    response.delete_cookie('amazon_oauth_state')
    # Automatischer Container-Neustart nach erfolgreichem Token-Save, damit
    # der neue Token sofort aktiv wird. Aktiviert durch
    # NAVI_AUTO_RESTART_ON_OAUTH_TOKEN_SAVE=true (Docker Compose restart: unless-stopped).
    if os.getenv('NAVI_AUTO_RESTART_ON_OAUTH_TOKEN_SAVE', '').lower() in ('1', 'true', 'yes', 'on'):
        _schedule_container_restart()
    return response


@app.route('/api/playback/status', methods=['GET'])
def playback_status():
    authorization_error = authorize_alexa_api()
    if authorization_error:
        return authorization_error

    try:
        response = connection.get_now_playing()
        now_playing = response.get('nowPlaying', {})
        entries = now_playing.get('entry', []) if isinstance(now_playing, dict) else []
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            entries = []

        players = [
            {
                'playerId': entry.get('playerId'),
                'name': entry.get('player') or entry.get('username') or 'Navidrome player',
                'title': entry.get('title'),
                'artist': entry.get('artist'),
                'album': entry.get('album'),
                'minutesAgo': entry.get('minutesAgo'),
            }
            for entry in entries
            if isinstance(entry, dict)
        ]
        return jsonify({'players': players})
    except Exception as error:
        logger.warning('Navidrome playback status lookup failed: %s', error)
        return jsonify({'error': 'Could not read Navidrome playback status.'}), 502


@app.route('/api/alexa/devices', methods=['GET'])
def alexa_devices():
    authorization_error = authorize_alexa_api()
    if authorization_error:
        return authorization_error

    try:
        return jsonify({'devices': get_alexa_remote_client().list_devices()})
    except AlexaRemoteError as error:
        logger.warning('Alexa device lookup failed: %s', error)
        return jsonify({'error': str(error)}), 502


@app.route('/api/alexa/renderers', methods=['GET'])
def alexa_renderers():
    authorization_error = authorize_alexa_api()
    if authorization_error:
        return authorization_error

    state_file = os.getenv('NAVI_ALEXA_RENDERER_STATE_FILE')
    if not state_file:
        return jsonify({'error': 'The renderer registry is not configured.'}), 503

    registry = RendererRegistry(state_file)
    registry.load()

    return jsonify({'renderers': registry.entries()})


@app.route('/api/alexa/test-play', methods=['POST'])
def alexa_test_play():
    authorization_error = authorize_alexa_api()
    if authorization_error:
        return authorization_error

    device = request.get_json(silent=True)
    if not isinstance(device, dict):
        device = {}

    required_fields = ('deviceOwnerCustomerId', 'deviceType', 'serialNumber')
    has_device_ids = all(isinstance(device.get(field), str) and device[field] for field in required_fields)
    device_name = device.get('deviceName')
    has_device_name = isinstance(device_name, str) and bool(device_name.strip())
    playlist_name = device.get('playlistName', '')
    if not isinstance(playlist_name, str):
        return jsonify({'error': 'playlistName must be a string.'}), 400
    playlist_name = playlist_name.strip()
    if not has_device_ids and not has_device_name:
        return jsonify({'error': 'Provide deviceName or deviceOwnerCustomerId, deviceType, and serialNumber.'}), 400

    try:
        client = get_alexa_remote_client()
        devices = client.list_devices()
        if has_device_ids:
            matches = [
                candidate for candidate in devices
                if all(candidate[field] == device[field] for field in required_fields)
            ]
        else:
            matches = find_devices_by_name(devices, device_name)

        if not matches:
            return jsonify({'error': 'The selected device is not in this Alexa account.'}), 404
        if len(matches) > 1:
            return jsonify({'error': 'Multiple Alexa devices have this name; use the device IDs.'}), 409

        target = matches[0]
        if not target['online']:
            return jsonify({'error': 'The selected Alexa device is offline.'}), 409

        client.send_play_command(
            target,
            skill_name=os.getenv('NAVI_ALEXA_SKILL_NAME', 'castnavidrome'),
            locale=get_configured_locale(),
            playlist_name=playlist_name,
        )
        logger.info('Sent the Alexa play command for the playlist "%s" to %s.',
                    playlist_name or 'random music', target['name'])
        return jsonify({'status': 'sent', 'device': target['name'], 'playlist': playlist_name or None})
    except AlexaRemoteError as error:
        logger.warning('Alexa play test failed: %s', error)
        return jsonify({'error': str(error)}), 502


@app.route('/cover/<cover_id>')
def cover_art(cover_id):
    """Serve the cover art of the media server

    Amazon cannot fetch the images of the media server, because the URL of
    the media server needs the credentials of the user.  The skill fetches the
    image and serves it, so that no credentials end up in the URL that is
    read by Amazon.

    Ported from locqust/asknavidrome (MIT), see CREDITS.md.
    """

    try:
        url = connection.get_cover_art_url(cover_id)
        data, content_type = fetch_cover_art(url)
    except Exception as error:
        logger.warning('Could not fetch the cover art %s: %s', cover_id, error)
        abort(404)

    return FlaskResponse(data, mimetype=content_type)


@app.route('/api/alexa/control', methods=['POST'])
def alexa_control():
    authorization_error = authorize_alexa_api()
    if authorization_error:
        return authorization_error

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({'error': 'Provide a JSON body.'}), 400

    device_name = body.get('deviceName')
    command = body.get('command')
    if not isinstance(device_name, str) or not device_name.strip():
        return jsonify({'error': 'Provide deviceName.'}), 400
    if not isinstance(command, str):
        return jsonify({'error': 'Provide command.'}), 400

    # The text of the command and the locale that is sent with it have to
    # be written in the same language, otherwise the Alexa device does not
    # understand the command.
    locale = get_configured_locale()

    try:
        text = build_control_text(
            command,
            os.getenv('NAVI_ALEXA_SKILL_NAME', 'castnavidrome'),
            body.get('volume'),
            locale=locale,
        )
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    try:
        client = get_alexa_remote_client()
        matches = find_devices_by_name(client.list_devices(), device_name)
        if not matches:
            return jsonify({'error': 'The selected device is not in this Alexa account.'}), 404
        if len(matches) > 1:
            return jsonify({'error': 'Multiple Alexa devices have this name.'}), 409

        target = matches[0]
        if not target['online']:
            return jsonify({'error': 'The selected Alexa device is offline.'}), 409

        client.send_text_command(
            target,
            text,
            locale=locale,
        )
        logger.info('Sent the Alexa command "%s" to %s.', text, target['name'])
        return jsonify({'status': 'sent', 'device': target['name'], 'command': command})
    except AlexaRemoteError as error:
        logger.warning('Alexa control command failed: %s', error)
        return jsonify({'error': str(error)}), 502

# Enable queue and history diagnostics
navidrome_debug_token = os.getenv('NAVI_DEBUG_TOKEN')

if navidrome_log_level == 3:
    logger.warning('castNavidrome debugging has been enabled, this should only be used when testing!')

    if not navidrome_debug_token:
        logger.warning('NAVI_DEBUG_TOKEN is not set, the debug endpoints are disabled.')
    else:
        logger.warning('The /queue, /history and /buffer http endpoints are enabled and require a token.')

    def validate_debug_token() -> None:
        """Check the token of a debug request

        The debug endpoints expose the play queue, so they are protected with
        a token.  If no token is configured, the endpoints are not available
        at all and answer with a 404, so that they cannot be found.

        Ported from johnpaulgosling/asknavidrome (MIT), see CREDITS.md.
        """

        if not navidrome_debug_token:
            abort(404)

        supplied_token = request.args.get('token')

        if not supplied_token or not hmac.compare_digest(supplied_token, navidrome_debug_token):
            abort(403)

    def resolve_debug_queue():
        """Get the play queue that the debug pages show

        Every device has its own play queue.  The device can be selected
        with the query parameter 'device', if it is not given the queue of
        the device that is used last is shown.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

        :return: The play queue of the selected device
        """

        device_id = request.args.get('device')

        if device_id:
            return state.get_play_queue(device_id)

        device_ids = list(state.get_known_device_ids())

        if not device_ids:
            return state.get_play_queue(state.DEFAULT_DEVICE_ID)

        return state.get_play_queue(device_ids[-1])

    @app.route('/queue')
    def view_queue():
        """View the contents of play_queue.queue

        Creates a tabulated page containing the contents of the play_queue.queue deque.
        """

        validate_debug_token()

        play_queue = resolve_debug_queue()
        current_track = play_queue.get_current_track()

        return render_template('table.html', title='castNavidrome - Queued Tracks',
                               tracks=play_queue.get_current_queue(), current=current_track)

    @app.route('/history')
    def view_history():
        """View the contents of play_queue.history

        Creates a tabulated page containing the contents of the play_queue.history deque.
        """

        validate_debug_token()

        play_queue = resolve_debug_queue()
        current_track = play_queue.get_current_track()

        return render_template('table.html', title='castNavidrome - Track History',
                               tracks=play_queue.get_history(), current=current_track)

    @app.route('/buffer')
    def view_buffer():
        """View the contents of play_queue.buffer

        Creates a tabulated page containing the contents of the play_queue.buffer deque.
        """

        validate_debug_token()

        play_queue = resolve_debug_queue()
        current_track = play_queue.get_current_track()

        return render_template('table.html', title='castNavidrome - Buffered Tracks',
                               tracks=play_queue.get_buffer(), current=current_track)


# Run web app by default when file is executed.
if __name__ == '__main__':
    # Start the web service
    app.run(host='0.0.0.0')
