"""Client for the Subsonic API of a Navidrome media server.

The module wraps the libsonic client and adds helper methods that the skill
uses to search artists, albums and songs, build play lists, fetch song
details and stream URIs, scrobble played tracks and report the now playing
track.  Responses are read defensively because the media server omits
results that are empty.
"""

from hashlib import md5
from typing import Union
import difflib
import logging
import random
import re
import secrets

import libsonic


def _search_results(result_dict: dict, kind: str) -> list:
    """Get the results of a search3 call

    The media server does not return the search result at all if nothing
    was found, so every access has to be defensive.

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param dict result_dict: The response of the search3 call
    :param str kind: The kind of result to return, e.g. 'song'
    :return: A list of results, empty if there are none
    :rtype: list
    """

    search_result = result_dict.get('searchResult3') or {}

    return search_result.get(kind) or []


class SubsonicConnection:
    """Class with methods to interact with Subsonic API compatible media servers
    """

    # Words to ignore when scoring a keyword/mood search query, so carrier
    # phrasing ("find me a playlist about X") and common connectives don't
    # get treated as meaningful search terms.
    #
    # Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
    _KEYWORD_STOPWORDS = frozenset({
        'a', 'an', 'the', 'and', 'or', 'of', 'to', 'for', 'with', 'about',
        'me', 'my', 'some', 'something', 'please', 'find', 'suggest',
        'recommend', 'playlist', 'playlists', 'that', 'is', 'einen', 'eine',
        'der', 'die', 'das', 'und', 'oder', 'von', 'mit', 'über', 'für',
        'mir', 'mich', 'bitte', 'finde', 'empfehl', 'wiedergabeliste',
        'wiedergabelisten', 'song', 'songs', 'lied', 'lieder', 'musik',
    })

    def __init__(self, server_url: str, user: str, passwd: str, port: int, api_location: str, api_version: str,
                 timeout: int = 10) -> None:
        """
        :param str server_url: The URL of the Subsonic API compatible media server
        :param str user: Username to authenticate against the API
        :param str passwd: Password to authenticate against the API
        :param int port: Port the Subsonic compatible server is listening on
        :param str api_location: Path to the API, this is appended to server_url
        :param str api_version: The version of the Subsonic API that is in use
        :param int timeout: Timeout in seconds for API requests to the media server
        :return: None
        """

        self.logger = logging.getLogger(__name__)

        self.server_url = server_url
        self.user = user
        self.passwd = passwd
        self.port = port
        self.api_location = api_location
        self.api_version = api_version
        self.timeout = timeout

        self.conn = libsonic.Connection(self.server_url,
                                        self.user,
                                        self.passwd,
                                        self.port,
                                        self.api_location,
                                        'AskNavidrome',
                                        self.api_version,
                                        False)

        self.logger.debug('Connecting to Navidrome.....')

    def ping(self) -> bool:
        """Ping a Subsonic API server

        Verify the connection to a Subsonic compatible API server
        is working.  Enhanced logging has been added to examine the
        HTTP response returned from the server to assist with troubleshooting
        connection issues.

        :return: True if the connection works, False if it does not
        :rtype: bool
        """

        self.logger.debug('In function ping()')
        http_request = self.conn._getRequest('ping.view')
        try:
            http_request_result = self.conn._doInfoReq(http_request)
        except Exception as e:
            self.logger.error('Failed to connect to Navidrome: %s', e, exc_info=True)
            return False

        self.logger.debug('ping() response from server: %s', http_request_result)
        status = http_request_result.get('status')
        if status == 'ok':
            self.logger.info('Successfully connected to Navidrome')
            return True
        elif status == 'failed':
            err = http_request_result.get('error', {})
            self.logger.error('Failed to connect to Navidrome: code=%s msg=%s',
                              err.get('code'), err.get('message'))
            return False
        else:
            self.logger.error('Unexpected error when connecting to Navidrome: %r', status)
            return False

    def scrobble(self, track_id: str, time: int, submission: bool = True) -> None:
        """Scrobble the given track

        :param str track_id: The ID of the track to scrobble
        :param int time: UNIX timestamp of track play time
        :return: None
        """
        self.logger.debug('In function scrobble()')

        self.conn.scrobble(track_id, submission, time)

        return None

    def get_now_playing(self) -> dict:
        """Return active Subsonic playback sessions."""
        return self.conn.getNowPlaying()

    def now_playing(self, track_id: str, device_id: str = '', player: str = '') -> None:
        """Tell Navidrome that the given track is now playing

        A non submission scrobble is sent, which is what populates the
        getNowPlaying list of Navidrome without recording a play count.

        Navidrome keeps one now playing entry per user and client name, so
        every Echo that uses the same account and the same client would
        overwrite the entry of the other one.  If a device ID is given, the
        scrobble is sent with a client name per device, so that every Echo
        gets its own entry.  Only this call uses the client name per device,
        the streaming itself still uses the normal client name.

        A player name can be given to report the track under the name of
        the client that asked for it, which is what the media renderers do.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

        :param str track_id: The ID of the track that is playing
        :param str device_id: The ID of the Alexa device that plays the track
        :param str player: The name of the client that plays the track
        :return: None
        """

        self.logger.debug('In function now_playing()')

        query = {'id': track_id, 'submission': False}

        if player:
            query['c'] = player
        elif device_id:
            query['c'] = f'AskNavidrome-{device_id[-8:]}'

        # The client name of the connection cannot be changed for a single
        # call, so the request is built by hand.
        request = self.conn._getRequest('scrobble.view', self.conn._getQueryDict(query))
        response = self.conn._doInfoReq(request)
        self.conn._checkStatus(response)

    def is_now_playing_reported_by_other_client(self, track_id: str) -> bool:
        """Check whether another client already reported the given track

        The media renderers report the track that they play under the name
        of the DLNA client that asked for it.  The skill must not report it
        a second time under its own name, otherwise Navidrome shows the
        same track twice in the now playing list.

        :param str track_id: The ID of the track
        :return: True when another client reported the track
        :rtype: bool
        """

        if not track_id:
            return False

        try:
            response = self.get_now_playing()
        except Exception as error:
            self.logger.warning('Could not read the now playing list: %s', error)
            return False

        now_playing = response.get('nowPlaying', {}) if isinstance(response, dict) else {}
        entries = now_playing.get('entry', []) if isinstance(now_playing, dict) else []

        if isinstance(entries, dict):
            entries = [entries]

        if not isinstance(entries, list):
            return False

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            if entry.get('id') != track_id:
                continue

            player = str(entry.get('player') or '')

            if player and not player.startswith('AskNavidrome-'):
                return True

        return False

        return None

    def search_playlist(self, term: str) -> Union[str, None]:
        """Search the media server for the given playlist

        :param str term: The name of the playlist
        :return: The ID of the playlist or None if the playlist is not found
        :rtype: str | None
        """

        self.logger.debug('In function search_playlist()')

        playlist_dict = self.conn.getPlaylists()

        # Search the list of dictionaries for a playlist with a name that matches the search term
        playlist_id_list = [item.get('id') for item in playlist_dict['playlists']['playlist'] if item.get('name').lower() == term.lower()]

        if len(playlist_id_list) == 1:
            # We have matched the playlist return it
            self.logger.debug(f'Found playlist {playlist_id_list[0]}')

            return playlist_id_list[0]

        elif len(playlist_id_list) > 1:
            # More than one result was returned, this should not be possible
            self.logger.error(f'More than one playlist called {term} was found, multiple playlists with the same name are not supported')

            return None

        elif len(playlist_id_list) == 0:
            self.logger.error(f'No playlist matching the name {term} was found!')

            return None

    def get_all_playlists(self) -> list:
        """Return every playlist known to the media server.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

        :return: A list of playlist dictionaries (id, name, comment, ...) as returned by getPlaylists()
        :rtype: list
        """

        self.logger.debug('In function get_all_playlists()')

        playlist_dict = self.conn.getPlaylists() or {}
        playlists = playlist_dict.get('playlists') or {}

        return playlists.get('playlist') or []

    @staticmethod
    def _normalize_words(text: str) -> list:
        """Lowercase and split into words, stripping punctuation but
        keeping word boundaries (unlike _normalize_playlist_name, which
        collapses everything into one contiguous blob). Used for keyword/
        mood matching against multi-word text like playlist comments.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
        """

        return re.sub(r'[^a-z0-9\s]', ' ', (text or '').lower()).split()

    @staticmethod
    def _normalize_playlist_name(name: str) -> str:
        """Lowercase and strip everything but letters/digits, so that
        voice-friendly slot values can be compared against stylized
        playlist titles without punctuation, spacing or casing getting in
        the way.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
        """

        return re.sub(r'[^a-z0-9]', '', (name or '').lower())

    @staticmethod
    def _normalize_search_term(term: str) -> str:
        """As _normalize_playlist_name, but first strips generic carrier
        words (e.g. "playlist"/"playlists") that can be swept into the slot
        value from phrasing like "my {playlist} playlist" but that never
        appear in an actual playlist name, so they don't get treated as part
        of the search term.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
        """

        words = SubsonicConnection._normalize_words(term)
        words = [word for word in words if word not in SubsonicConnection._KEYWORD_STOPWORDS]

        return ''.join(words)

    def _score_playlist_name(self, normalized_term: str, name: str) -> float:
        """Score a playlist name against a normalized search term

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.
        """

        normalized_name = self._normalize_playlist_name(name)

        if normalized_name == normalized_term:
            return 1.0
        if normalized_term and normalized_term in normalized_name:
            # A stylized name containing the whole spoken term (e.g.
            # "crossover" inside "FM-X (The Cross-Over)") is a strong
            # signal, but not quite as certain as an exact match.
            return 0.9

        return difflib.SequenceMatcher(None, normalized_term, normalized_name).ratio()

    def rank_playlists(self, term: str, name_forms=None) -> list:
        """Score every playlist's name against `term`, best match first.

        Used instead of a plain first-match search so callers can tell an
        unambiguous match (score close to 1.0, clear of the runner-up) from
        an ambiguous one (several playlists scoring close together) and
        decide whether to just play it or ask which one was meant.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

        :param str term: The playlist name as spoken/transcribed
        :param name_forms: Optional callable returning every form of a stored
            name a user might say (e.g. without its genre prefix); each
            playlist scores as its best-matching form. Defaults to the stored
            name only.
        :return: A list of (score, id, name) tuples sorted by score descending
        :rtype: list
        """

        self.logger.debug('In function rank_playlists()')

        normalized_term = self._normalize_search_term(term)

        scored = []

        for item in self.get_all_playlists():
            name = item.get('name')
            forms = name_forms(name) if name_forms else [name]

            score = max(self._score_playlist_name(normalized_term, form) for form in forms)

            scored.append((score, item.get('id'), name))

        scored.sort(key=lambda entry: entry[0], reverse=True)

        return scored

    def search_playlists_by_keyword(self, term: str, limit: int = 5) -> list:
        """Search playlist names and descriptions for a mood/genre/keyword
        match, for discovery-style requests (e.g. "find me an upbeat
        playlist") rather than requests for a specific playlist by name.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

        :param str term: The keyword(s)/mood to search for
        :param int limit: Maximum number of candidates to return
        :return: A list of (score, id, name) tuples sorted by score descending, best first
        :rtype: list
        """

        self.logger.debug('In function search_playlists_by_keyword()')

        query_words = [word for word in self._normalize_words(term) if word not in self._KEYWORD_STOPWORDS]

        if not query_words:
            return []

        scored = []

        for item in self.get_all_playlists():
            name = item.get('name')
            # AudioMuse auto-generated playlists carry a "_automatic" suffix
            # that's not part of the descriptive text, and the comment field
            # (when present) holds a human-written blurb describing the
            # playlist's mood/genre.
            corpus_words = self._normalize_words(name.replace('_automatic', '') + ' ' + (item.get('comment') or ''))

            word_hits = sum(1 for query_word in query_words if any(query_word in corpus_word for corpus_word in corpus_words))
            score = word_hits / len(query_words)

            if score > 0:
                scored.append((score, item.get('id'), name))

        scored.sort(key=lambda entry: entry[0], reverse=True)

        return scored[:limit]

    def search_artist(self, term: str, count: int = 20) -> Union[list, None]:
        """Search the media server for the given artist

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.  The number of
        results can be limited and the response is read defensively, because
        the media server omits the result if nothing was found.

        :param str term: The name of the artist
        :param int count: The maximum number of results
        :return: A list of artists or None if no results are found
        :rtype: list | None
        """

        self.logger.debug('In function search_artist()')

        result_dict = self.conn.search3(term, artistCount=count)
        artists = _search_results(result_dict, 'artist')

        if not artists:
            return None

        self.logger.debug(f'Searching artists for term: {term} found {len(artists)} entries.')

        return artists

    def search_album(self, term: str, count: int = 20) -> Union[list, None]:
        """Search the media server for the given album

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param str term: The name of the album
        :param int count: The maximum number of results
        :return: A list of albums or None if no results are found
        :rtype: list | None
        """

        self.logger.debug('In function search_album()')

        result_dict = self.conn.search3(term, albumCount=count)
        albums = _search_results(result_dict, 'album')

        if not albums:
            return None

        self.logger.debug(f'Searching albums for term: {term} found {len(albums)} entries.')

        return albums

    def search_song(self, term: str, count: int = 100) -> Union[list, None]:
        """Search the media server for the given song

        The search of the media server is fuzzy, so it can return songs that
        have nothing to do with the search term.  Only the songs whose title
        contains the search term are kept.  If none of the results matches,
        all results are returned, so that a song that is stored under a
        slightly different title is still found.

        Ported from djh20/asknavidrome (MIT), see CREDITS.md.  The number of
        results and the defensive reading of the response come from
        bickns/asknavidrome (MIT).

        :param str term: The name of the song
        :param int count: The maximum number of results
        :return: A list of songs or None if no results are found
        :rtype: list | None
        """

        self.logger.debug('In function search_song()')

        result_dict = self.conn.search3(term, songCount=count)
        songs = _search_results(result_dict, 'song')

        if not songs:
            return None

        matching_songs = [song for song in songs
                          if term.lower() in (song.get('title') or '').lower()]

        if matching_songs:
            self.logger.debug(f'Filtered {len(songs)} songs down to {len(matching_songs)} matching ones.')
            songs = matching_songs

        self.logger.debug(f'Searching songs for term: {term} found {len(songs)} entries.')

        return songs

    def albums_by_artist(self, id: str) -> 'list[dict]':
        """Get the albums for a given artist

        :param str id: The artist ID
        :return: A list of albums
        :rtype: list of dict
        """

        self.logger.debug('In function albums_by_artist()')

        result_dict = self.conn.getArtist(id)
        album_list = result_dict['artist'].get('album')

        # Shuffle the album list to keep generic requests fresh
        random.shuffle(album_list)

        return album_list

    def build_song_list_from_albums(self, albums: 'list[dict]', length: int) -> list:
        """Get a list of songs from given albums

        Build a list of songs from the given albums, keep adding tracks
        until song_count is greater than of equal to length

        :param list[dict] albums: A list of dictionaries containing album information
        :param int length: The minimum number of songs that should be returned, if -1 there is no limit
        :return: A list of song IDs
        :rtype: list
        """

        self.logger.debug('In function build_song_list_from_albums()')

        song_id_list = []

        if length != -1:
            song_count = 0
            album_id_list = []

            # The list of songs should be limited by length
            for album in albums:
                if song_count < int(length):
                    # We need more songs
                    album_id_list.append(album.get('id'))
                    song_count = song_count + album.get('songCount')
                else:
                    # We have enough songs, stop iterating
                    break
        else:
            # The list of songs should not be limited
            album_id_list = [album.get('id') for album in albums]

        # Get a song listing for each album
        for album_id in album_id_list:
            album_details = self.conn.getAlbum(album_id)

            for song_detail in album_details['album']['song']:
                # Capture the song ID
                song_id_list.append(song_detail.get('id'))

        return song_id_list

    def build_song_list_from_playlist(self, id: str) -> list:
        """Build a list of songs from a given playlist

        :param str id: The playlist ID
        :return: A list of song IDs
        :rtype: list
        """

        self.logger.debug('In function build_song_list_from_playlist()')

        song_id_list = []
        playlist_details = self.conn.getPlaylist(id)

        song_id_list = [song_detail.get('id') for song_detail in playlist_details.get('playlist').get('entry')]

        return song_id_list

    def build_song_list_from_favourites(self) -> Union[list, None]:
        """Build a shuffled list favourite songs

        :return: A list of song IDs or None if no favourite tracks are found.
        :rtype: list | None
        """

        self.logger.debug('In function build_song_list_from_favourites()')

        favourite_songs = self.conn.getStarred2().get('starred2').get('song')

        if len(favourite_songs) > 0:
            song_id_list = [song.get('id') for song in favourite_songs]

            return song_id_list

        else:
            return None

    def get_similar_songs(self, id: str, count: int = 50) -> list:
        """Get the songs that are similar to the given song

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param str id: The ID of the song
        :param int count: The number of songs to return
        :return: A list of song IDs
        :rtype: list
        """

        self.logger.debug('In function get_similar_songs()')

        result_dict = self.conn.getSimilarSongs2(id, count) or {}
        similar = result_dict.get('similarSongs2') or {}
        songs = similar.get('song') or []

        return [song.get('id') for song in songs if song.get('id')]

    def get_albums_by_year(self, from_year: int, to_year: int, size: int = 100) -> list:
        """Get the albums of a range of years

        The client library of the Subsonic API does not support the year
        range, so the request is built by hand.

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param int from_year: The first year of the range
        :param int to_year: The last year of the range
        :param int size: The maximum number of albums
        :return: A list of albums
        :rtype: list
        """

        self.logger.debug('In function get_albums_by_year()')

        query = {'type': 'byYear', 'fromYear': from_year, 'toYear': to_year, 'size': size}
        request = self.conn._getRequest('getAlbumList2.view', self.conn._getQueryDict(query))
        response = self.conn._doInfoReq(request)
        self.conn._checkStatus(response)

        album_list = response.get('albumList2') or {}

        return album_list.get('album') or []

    def build_song_list_from_genre(self, genre: str, count: int) -> Union[list, None]:
        """Build a shuffled list songs of songs from the given genre.

        :param str genre: The genre, acceptable values are with the getGenres Subsonic API call.
        :param int count: The number of songs to return
        :return: A list of song IDs or None if no tracks are found.
        :rtype: list | None
        """

        self.logger.debug('In function build_song_list_from_genre()')

        # Note the use of title() to capitalise the first letter of each word in the genre
        # without this the genres do not match the strings returned by the API.
        self.logger.debug(f'Searching for {genre.title()} music')
        songs_from_genre = self.conn.getSongsByGenre(genre.title(), count).get('songsByGenre').get('song')

        if len(songs_from_genre) > 0:
            song_id_list = [song.get('id') for song in songs_from_genre]

            return song_id_list

        else:
            return None

    def build_random_song_list(self, count: int) -> Union[list, None]:
        """Build a shuffled list of random songs

        :param int count: The number of songs to return
        :return: A list of song IDs or None if no tracks are found.
        :rtype: list | None
        """

        self.logger.debug('In function build_random_song_list()')
        random_songs = self.conn.getRandomSongs(count).get('randomSongs').get('song')

        if len(random_songs) > 0:
            song_id_list = [song.get('id') for song in random_songs]

            return song_id_list

        else:
            return None

    def get_song_details(self, id: str) -> dict:
        """Get details about a given song ID

        :param str id: A song ID
        :return: A dictionary of details about the given song.
        :rtype: dict
        """

        self.logger.debug('In function get_song_details()')

        song_details = self.conn.getSong(id)

        return song_details

    def get_song(self, id: str) -> Union[dict, None]:
        """Get a single song of the collection

        :param str id: The ID of the song
        :return: The song or None when it does not exist
        :rtype: dict | None
        """

        if not id:
            return None

        try:
            details = self.get_song_details(id)
        except Exception as error:
            self.logger.debug('The song %s was not found: %s', id, error)
            return None

        song = details.get('song') if isinstance(details, dict) else None

        return song if isinstance(song, dict) else None

    def get_album_songs(self, album_id: str) -> list:
        """Get the songs of an album, in the order of the album

        :param str album_id: The ID of the album
        :return: A list of the songs of the album
        :rtype: list
        """

        if not album_id:
            return []

        try:
            details = self.conn.getAlbum(album_id)
        except Exception as error:
            self.logger.warning('Could not read the album %s: %s', album_id, error)
            return []

        album = details.get('album') if isinstance(details, dict) else None
        songs = album.get('song') if isinstance(album, dict) else None

        if isinstance(songs, dict):
            songs = [songs]

        return songs if isinstance(songs, list) else []

    def get_playlist_songs(self, playlist_id: str) -> list:
        """Get the songs of a play list, in the order of the play list

        :param str playlist_id: The ID of the play list
        :return: A list of the songs of the play list
        :rtype: list
        """

        if not playlist_id:
            return []

        try:
            details = self.conn.getPlaylist(playlist_id)
        except Exception as error:
            self.logger.warning('Could not read the play list %s: %s', playlist_id, error)
            return []

        playlist = details.get('playlist') if isinstance(details, dict) else None
        entries = playlist.get('entry') if isinstance(playlist, dict) else None

        if isinstance(entries, dict):
            entries = [entries]

        return entries if isinstance(entries, list) else []

    def find_song_by_title(self, title: str, artist: str = '') -> Union[dict, None]:
        """Find a song of the collection by its title and its artist

        The search is used when the client that drives a media renderer
        does not send an URI that carries the ID of the song.

        :param str title: The title of the song
        :param str artist: The artist of the song
        :return: The song or None when it was not found
        :rtype: dict | None
        """

        if not title:
            return None

        songs = self.search_song(title) or []

        if not songs:
            return None

        if artist:
            for song in songs:
                if str(song.get('artist', '')).casefold() == str(artist).casefold():
                    return song

        return songs[0]

    def get_song_uri(self, id: str) -> str:
        """Create a URI for a given song

        Creates a URI for the song represented by the given ID.  Authentication details are
        embedded in the URI

        :param str id: A song ID
        :return: A properly formatted URI
        :rtype: str
        """

        self.logger.debug('In function get_song_uri()')

        salt = secrets.token_hex(16)
        auth_token = md5(self.passwd.encode() + salt.encode())

        # This creates a multiline f string, uri contains a single line with both
        # f strings.
        uri = (
            f'{self.server_url}:{self.port}{self.api_location}/stream.view?f=json&v={self.api_version}&c=AskNavidrome&u='
            f'{self.user}&s={salt}&t={auth_token.hexdigest()}&id={id}'
        )

        return uri

    def get_cover_art_url(self, id: str) -> str:
        """Create a URI for the cover art of a song

        Creates a URI for the cover art of the song represented by the given
        ID.  Authentication details are embedded in the URI.

        The URI is only used by the skill itself, to fetch the image.  Amazon
        gets the image from the cover art proxy of the skill, so that no
        credentials end up in a URL that is read by a third party.

        Ported from locqust/asknavidrome (MIT), see CREDITS.md.

        :param str id: A song or album ID
        :return: A properly formatted URI
        :rtype: str
        """

        self.logger.debug('In function get_cover_art_url()')

        salt = secrets.token_hex(16)
        auth_token = md5(self.passwd.encode() + salt.encode())

        uri = (
            f'{self.server_url}:{self.port}{self.api_location}/getCoverArt?f=json&v={self.api_version}&c=AskNavidrome&u='
            f'{self.user}&s={salt}&t={auth_token.hexdigest()}&id={id}'
        )

        return uri

    def star_entry(self, id: str, mode: str) -> None:
        """Add a star to the given entity

        :param str id: The Navidrome ID of the entity.
        :param str mode: The type of entity, must be song, artist or album
        :return: None.
        """

        # Convert id to list
        id_list = [id]

        if mode == 'song':
            self.conn.star(id_list, None, None)

            return None
        elif mode == 'album':
            self.conn.star(None, id_list, None)

            return None
        elif mode == 'artist':
            self.conn.star(None, None, id_list)

            return None

    def unstar_entry(self, id: str, mode: str) -> None:
        """Remove a star from the given entity

        :param str id: The Navidrome ID of the entity.
        :param str mode: The type of entity, must be song, artist or album
        :return: None.
        """

        # Convert id to list
        id_list = [id]

        if mode == 'song':
            self.conn.unstar(id_list, None, None)

            return None
        elif mode == 'album':
            self.conn.unstar(None, id_list, None)

            return None
        elif mode == 'artist':
            self.conn.unstar(None, None, id_list)

            return None
