"""Fuzzy matching helpers for the castnavidrome skill.

Ported from gsidhu/asknavidrome (author Gurjot Sidhu, MIT license).

The graceful degradation when rapidfuzz is missing and the integration of
CatalogCache with our castnavidrome.subsonic_api.SubsonicConnection are our
own local changes.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import fuzz, process, utils
    _RAPIDFUZZ_AVAILABLE = True
    _PROCESSOR = utils.default_process
except Exception:  # pragma: no cover - exercised only when dependency missing
    fuzz = None
    process = None
    utils = None
    _PROCESSOR = None
    _RAPIDFUZZ_AVAILABLE = False
    logger.warning('rapidfuzz is not installed; fuzzy matching disabled')


def _extract_one(query: str, choices, threshold: int):
    """Return the best match of a query, ignoring the case and the punctuation.

    rapidfuzz 3 does not lowercase the strings any more, so a query like
    "rok" would not match the genre "Rock" any more.  The default processor
    of rapidfuzz lowercases the strings and drops the punctuation, which
    restores the behaviour of the 2.x releases the feature was ported from.

    :param str query: The search term
    :param choices: The choices to search in, a list of strings
    :param int threshold: Minimum score (0-100) to accept a match
    :return: The result tuple of rapidfuzz or None
    """

    return process.extractOne(
        query,
        choices,
        scorer=fuzz.token_sort_ratio,
        processor=_PROCESSOR,
        score_cutoff=threshold,
    )


class CatalogCache:
    """Lazily fetches and caches artist and genre lists from the Subsonic server.

    :param connection: A SubsonicConnection instance
    """

    def __init__(self, connection) -> None:
        """
        :param connection: The connection to the Subsonic server
        :type connection: SubsonicConnection
        :return: None
        """

        self.logger = logging.getLogger(__name__)
        """Logger"""

        self._connection = connection
        self._artists = None
        self._genres = None

    def get_artists(self) -> list:
        """Return the cached list of artists, fetching on first use.

        :return: A list of artist dicts
        :rtype: list
        """

        if self._artists is None:
            self._artists = self._fetch_all_artists()
        return self._artists

    def get_genres(self) -> list:
        """Return the cached list of genres, fetching on first use.

        :return: A list of genre strings
        :rtype: list
        """

        if self._genres is None:
            self._genres = self._fetch_all_genres()
        return self._genres

    def refresh(self) -> None:
        """Clear the cached artist and genre lists.

        :return: None
        """

        self._artists = None
        self._genres = None

    def _fetch_all_artists(self) -> list:
        """Flatten the alphabetical index structure from getArtists() into a list.

        :return: A list of artist dicts with 'id' and 'name' keys
        :rtype: list
        """

        try:
            response = self._connection.conn.getArtists() or {}
            artists_container = response.get('artists') if isinstance(response, dict) else None
            if not isinstance(artists_container, dict):
                artists_container = {}
            index_list = artists_container.get('index') or []

            artists = []
            for index in index_list or []:
                if not isinstance(index, dict):
                    continue
                for artist in (index.get('artist') or []):
                    if not isinstance(artist, dict):
                        continue
                    artists.append({'id': artist.get('id'), 'name': artist.get('name', '')})

            self.logger.debug(f'Cached {len(artists)} artists from server')
            return artists
        except Exception:
            self.logger.error('Failed to fetch artist catalog', exc_info=True)
            return []

    def _fetch_all_genres(self) -> list:
        """Fetch the genre list from the server.

        :return: A list of genre strings
        :rtype: list
        """

        try:
            response = self._connection.conn.getGenres() or {}
            genres_container = response.get('genres') if isinstance(response, dict) else None
            if not isinstance(genres_container, dict):
                genres_container = {}
            genre_list = genres_container.get('genre') or []

            genres = [g.get('value', '') for g in genre_list if isinstance(g, dict) and g.get('value')]
            self.logger.debug(f'Cached {len(genres)} genres from server')
            return genres
        except Exception:
            self.logger.error('Failed to fetch genre catalog', exc_info=True)
            return []


def fuzzy_find_artist(catalog, query, threshold=70):
    """Find the best matching artist from the cached catalog.

    :param catalog: A CatalogCache instance
    :param query: The artist name to search for
    :param threshold: Minimum score (0-100) to accept a match
    :return: The matched artist dict {id, name} or None
    :rtype: dict or None
    """

    if not _RAPIDFUZZ_AVAILABLE:
        return None

    artists = catalog.get_artists()
    if not artists:
        return None

    choices = {artist['name']: artist for artist in artists if artist.get('name')}

    result = _extract_one(query, list(choices.keys()), threshold)

    if result is None:
        logger.debug(f'Fuzzy artist search: no match for "{query}" above threshold {threshold}')
        return None

    matched_name, score, _ = result
    logger.info(f'Fuzzy artist match: "{query}" -> "{matched_name}" (score: {score})')
    return choices[matched_name]


def fuzzy_find_album(albums, query, threshold=70):
    """Find the best matching album from a list of album dicts.

    :param albums: A list of album dicts (each must have a 'name' key)
    :param query: The album name to search for
    :param threshold: Minimum score (0-100) to accept a match
    :return: The matched album dict or None
    :rtype: dict or None
    """

    if not _RAPIDFUZZ_AVAILABLE:
        return None

    if not albums:
        return None

    choices = {album.get('name', ''): album for album in albums if album.get('name')}

    result = _extract_one(query, list(choices.keys()), threshold)

    if result is None:
        logger.debug(f'Fuzzy album search: no match for "{query}" above threshold {threshold}')
        return None

    matched_name, score, _ = result
    logger.info(f'Fuzzy album match: "{query}" -> "{matched_name}" (score: {score})')
    return choices[matched_name]


def fuzzy_find_genre(catalog, query, threshold=70):
    """Find the best matching genre from the cached catalog.

    :param catalog: A CatalogCache instance
    :param query: The genre name to search for
    :param threshold: Minimum score (0-100) to accept a match
    :return: The matched genre string or None
    :rtype: str or None
    """

    if not _RAPIDFUZZ_AVAILABLE:
        return None

    genres = catalog.get_genres()
    if not genres:
        return None

    result = _extract_one(query, genres, threshold)

    if result is None:
        logger.debug(f'Fuzzy genre search: no match for "{query}" above threshold {threshold}')
        return None

    matched_name, score, _ = result
    logger.info(f'Fuzzy genre match: "{query}" -> "{matched_name}" (score: {score})')
    return matched_name


def fuzzy_find_playlist(playlists, query, threshold=70):
    """Find the best matching playlist from a list of playlist dicts.

    :param playlists: A list of playlist dicts (each must have 'id' and 'name' keys)
    :param query: The playlist name to search for
    :param threshold: Minimum score (0-100) to accept a match
    :return: The matched playlist ID or None
    :rtype: str or None
    """

    if not _RAPIDFUZZ_AVAILABLE:
        return None

    if not playlists:
        return None

    choices = {}
    for pl in playlists:
        name = pl.get('name', '')
        if name:
            choices[name] = pl.get('id')

    result = _extract_one(query, list(choices.keys()), threshold)

    if result is None:
        logger.debug(f'Fuzzy playlist search: no match for "{query}" above threshold {threshold}')
        return None

    matched_name, score, _ = result
    logger.info(f'Fuzzy playlist match: "{query}" -> "{matched_name}" (score: {score})')
    return choices[matched_name]