"""Free text search for the castNavidrome skill.

Handles turning whatever Alexa hands back in a castNavidromePlaySearch slot into
an actual set of Navidrome song IDs.  The Subsonic search3 API is the only
real free text search primitive available - there is no separate "smarter"
endpoint - so everything here is client side scoring and fallback logic
layered on top of it: punctuation normalized retry variants, local fuzzy
spelling correction against the cached artist list, and a priority chain
(song, then artist, then genre, then album) with a minimum match score
threshold at every step, so a coincidental low quality match never wins
over a genuinely better one further down the chain.

Ported from bickns/asknavidrome (MIT), see CREDITS.md.  The resolver is a
class instead of a module with global state, the integration of the fuzzy
matching of gsidhu/asknavidrome (MIT) and the handling of the empty
results are our own local changes.
"""

from difflib import SequenceMatcher
import logging
import random
import re

from .fuzzy_match import CatalogCache, fuzzy_find_artist


logger = logging.getLogger(__name__)

SEARCH_RESULT_COUNT = 100
"""The number of results that are used for a search"""

MIN_ACCEPTABLE_SCORE = 2.0
"""The score a result has to reach to be used"""

ARTIST_SPELLING_CORRECTION_THRESHOLD = 0.75
"""The similarity a mistyped artist name has to reach to be corrected"""

FUZZY_ARTIST_THRESHOLD = 70
"""The score of the fuzzy artist matching, from 0 to 100"""


def genre_matches(query: str, genre_name: str) -> bool:
    """Whole word match against a genre name.

    Avoids false positives from raw substring matching - e.g. "dance"
    would wrongly match "dancehall" under a naive `in` check, since
    "dance" is a substring of "dancehall" but they are unrelated
    genres. Splitting on whitespace/hyphen/ampersand and comparing
    whole tokens avoids this while still correctly matching "dance"
    against "dance-pop" (which does split into legitimate tokens).

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param str query: The spoken/typed genre term
    :param str genre_name: A genre name from the known genres
    :return: True if query matches one of the whole tokens of genre_name
    :rtype: bool
    """

    tokens = re.split(r'[\s\-&]+', (genre_name or '').lower())

    return (query or '').lower() in tokens


def parse_query_for_artist(text: str) -> tuple:
    """Split 'song by artist' style phrasing out of a free text query.

    Strips optional filler words ("the song", "the band", "the artist")
    so both terse ("X by Y") and wordier ("the song X by the artist Y")
    phrasings resolve to clean search terms.

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param str text: The raw query text as spoken/typed
    :return: A tuple of the song text and the artist text, the artist text
             is None if the query does not name an artist
    :rtype: tuple
    """

    match = re.search(
        r'^(?:the\s+song\s+)?(.*?)\s+by\s+(?:the\s+(?:band|artist)\s+)?(.*)$',
        text or '', re.IGNORECASE
    )

    if match:
        return match.group(1).strip(), match.group(2).strip()

    return text, None


def search_variants(term: str) -> list:
    """Generate normalized variants of a search term to work around
    common tagging punctuation mismatches (e.g. 'and' vs '&').

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param str term: The original search term
    :return: A list of variants to try, starting with the original
    :rtype: list
    """

    variants = [term]

    if re.search(r'\band\b', term, re.IGNORECASE):
        variants.append(re.sub(r'\band\b', '&', term, flags=re.IGNORECASE))
    if '&' in term:
        variants.append(term.replace('&', 'and'))

    no_punct = re.sub(r"[,\.]", '', term)
    if no_punct != term:
        variants.append(no_punct)

    return variants


def match_score(query: str, candidate: str) -> float:
    """Score how well a candidate matches a query, for ranking the search
    results client side rather than trusting the order the server returned
    them in.

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param str query: The search term
    :param str candidate: A candidate string to score against it
    :return: 4.0 for an exact match, 3.0 for a prefix match, 2.0 for
             a substring match, otherwise a similarity ratio
    :rtype: float
    """

    q = (query or '').lower().strip()
    c = (candidate or '').lower().strip()

    if not q or not c:
        return 0.0

    if q == c:
        return 4.0
    if c.startswith(q):
        return 3.0
    if q in c:
        return 2.0

    return SequenceMatcher(None, q, c).ratio()


def best_song_match(query: str, songs: list) -> list:
    """Re-order a list of song dicts so the best match to the query is first.

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param str query: The search term
    :param list songs: A list of song dicts (each must have a 'title' key)
    :return: The same songs, sorted by descending match score
    :rtype: list
    """

    return sorted(songs, key=lambda song: match_score(query, song.get('title', '')), reverse=True)


def filter_to_best_matches(query: str, songs: list, threshold: float = 0.15) -> list:
    """Keep only songs whose match score is close to the best match's
    score, discarding loosely related results.

    Prevents e.g. 'play bad' queueing 'Bad Romance' and 'Bad Blood'
    behind the correct 'Bad' - without this, an exact match would
    still be followed by every other loosely similar title that the
    fuzzy search of the server happened to return.

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param str query: The search term
    :param list songs: A list of song dicts
    :param float threshold: Maximum score gap from the top match to still be kept
    :return: The subset of songs within the threshold of the best score
    :rtype: list
    """

    if not songs:
        return []

    scored = [(song, match_score(query, song.get('title', ''))) for song in songs]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    top_score = scored[0][1]

    return [song for song, score in scored if top_score - score <= threshold]


def best_album_match(query: str, albums: list):
    """Pick the single best matching album dict from a list of
    candidates, rather than combining every loosely matched album's
    songs together.

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.

    :param str query: The search term
    :param list albums: A list of album dicts (each must have a 'name' key)
    :return: The single best matching album dict
    :rtype: dict
    """

    return max(albums, key=lambda album: match_score(query, album.get('name', '')))


class SearchResolver:
    """Resolve a free text query against the collection

    The resolver needs a connection to the media server.  The list of the
    known genres and artists is filled on the first use, so that the
    genres of a query can be matched and a mistyped artist name can be
    corrected.

    Ported from bickns/asknavidrome (MIT), see CREDITS.md.
    """

    def __init__(self, connection, min_song_count: int = 50) -> None:
        """
        :param connection: The connection to the media server
        :param int min_song_count: The number of songs a genre returns
        """

        self.logger = logging.getLogger(__name__)

        self.connection = connection
        self.min_song_count = int(min_song_count)
        self.catalog = CatalogCache(connection)
        self._known_genres = None
        self._known_artists = None

    @property
    def known_genres(self) -> list:
        """The genres of the collection

        :return: A list of the genre names
        :rtype: list
        """

        if self._known_genres is None:
            self._known_genres = self.catalog.get_genres()

        return self._known_genres

    @property
    def known_artists(self) -> list:
        """The artists of the collection

        :return: A list of the artist names
        :rtype: list
        """

        if self._known_artists is None:
            self._known_artists = [artist.get('name', '') for artist in self.catalog.get_artists()]

        return self._known_artists

    def correct_artist_spelling(self, term: str, threshold: float = ARTIST_SPELLING_CORRECTION_THRESHOLD) -> str:
        """Find the closest known artist name to a term using local fuzzy
        matching, for cases where the speech to text produces a plausible
        but incorrectly spelled name (e.g. spoken "gipsy kings" vs the
        tagged "Gypsy Kings").

        The fuzzy matching of gsidhu/asknavidrome (MIT) is used if it is
        available, otherwise the artists are compared with the similarity
        ratio.

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param str term: The spoken/typed artist name
        :param float threshold: Minimum similarity ratio required to accept a match
        :return: The corrected name, or None if nothing scores above the threshold
        :rtype: str | None
        """

        if not term:
            return None

        matched = fuzzy_find_artist(self.catalog, term, FUZZY_ARTIST_THRESHOLD)

        if matched:
            return matched.get('name')

        if not self.known_artists:
            return None

        best_match = None
        best_score = 0.0

        for name in self.known_artists:
            score = SequenceMatcher(None, term.lower(), name.lower()).ratio()
            if score > best_score:
                best_score = score
                best_match = name

        if best_score >= threshold:
            self.logger.debug('correct_artist_spelling: "%s" -> "%s" (score %.2f)', term, best_match, best_score)
            return best_match

        return None

    def fuzzy_search_song(self, term: str) -> list:
        """Try to search a song against the normalized variants of a term
        until one of them returns a result.

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param str term: The song title to search for
        :return: A list of matching song dicts, empty if nothing matched
        :rtype: list
        """

        for variant in search_variants(term):
            self.logger.debug('fuzzy_search_song: trying the variant "%s"', variant)
            result = self.connection.search_song(variant, SEARCH_RESULT_COUNT)

            if result:
                self.logger.info('fuzzy_search_song("%s"): %s results', term, len(result))
                return result

        self.logger.info('fuzzy_search_song("%s"): no results', term)
        return []

    def fuzzy_search_artist(self, term: str) -> list:
        """Try to search an artist against the normalized variants of a
        term, then the local fuzzy spelling correction, and finally the
        metadata of the songs as a fallback.

        The song metadata fallback catches artists that exist as plain text
        metadata on tracks but were never indexed as a standalone artist
        entity, because the media server only indexes the artists that are
        the primary album artist on at least one album.

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param str term: The artist name to search for
        :return: A list of matching artist dicts, empty if nothing matched
        :rtype: list
        """

        for variant in search_variants(term):
            self.logger.debug('fuzzy_search_artist: trying the variant "%s"', variant)
            result = self.connection.search_artist(variant)

            if result:
                self.logger.info('fuzzy_search_artist("%s"): %s results', term, len(result))
                return result

        corrected = self.correct_artist_spelling(term)

        if corrected and corrected.lower() != term.lower():
            self.logger.debug('fuzzy_search_artist: no direct match for "%s", trying "%s"', term, corrected)
            result = self.connection.search_artist(corrected)

            if result:
                self.logger.info('fuzzy_search_artist("%s"): %s results via the spelling correction', term, len(result))
                return result

        self.logger.debug('fuzzy_search_artist: no indexed match for "%s", trying the song metadata', term)
        song_results = self.connection.search_song(term, SEARCH_RESULT_COUNT) or []

        for song in song_results:
            song_artist = song.get('artist', '')

            if match_score(term, song_artist) >= 3.0 and song.get('artistId'):
                self.logger.info('fuzzy_search_artist("%s"): matched via the song metadata - "%s"', term, song_artist)
                return [{'id': song.get('artistId'), 'name': song_artist}]

        self.logger.info('fuzzy_search_artist("%s"): no results', term)
        return []

    def fuzzy_search_album(self, term: str) -> list:
        """Try to search an album against the normalized variants of a term
        until one of them returns a result.

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param str term: The album title to search for
        :return: A list of matching album dicts, empty if nothing matched
        :rtype: list
        """

        for variant in search_variants(term):
            self.logger.debug('fuzzy_search_album: trying the variant "%s"', variant)
            result = self.connection.search_album(variant)

            if result:
                self.logger.info('fuzzy_search_album("%s"): %s results', term, len(result))
                return result

        self.logger.info('fuzzy_search_album("%s"): no results', term)
        return []

    def resolve(self, query: str) -> tuple:
        """Resolve a free text query against the collection.

        The query is resolved against the songs, then the artists, then the
        genres and finally the albums, in that order.  Every step logs what
        was searched and how many results came back, so the search
        behaviour is diagnosable directly from the log.

        If the query contains "X by Y" phrasing, X and Y are extracted with
        parse_query_for_artist(); the artist is looked up first, and an
        artist scoped song or album match is tried before falling through
        to the generic steps.

        Every match step requires a score of at least MIN_ACCEPTABLE_SCORE
        before it is accepted.

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param str query: The query as spoken/typed
        :return: A tuple of the song IDs and a description of what was
                 found, both None if nothing was found
        :rtype: tuple
        """

        song_text, artist_text = parse_query_for_artist(query)
        search_text = song_text if artist_text else query

        self.logger.info('resolve_search: the query "%s" is searched as "%s"', query, search_text)

        if artist_text:
            song_id_list, description = self._resolve_with_artist(search_text, artist_text)

            if song_id_list:
                return song_id_list, description

        song_id_list, description = self._resolve_song(search_text)

        if song_id_list:
            return song_id_list, description

        song_id_list, description = self._resolve_artist(search_text)

        if song_id_list:
            return song_id_list, description

        song_id_list, description = self._resolve_genre(search_text)

        if song_id_list:
            return song_id_list, description

        return self._resolve_album(search_text)

    def _resolve_with_artist(self, search_text: str, artist_text: str) -> tuple:
        """Resolve a query that names an artist

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.
        """

        artist_results = self.fuzzy_search_artist(artist_text)

        if not artist_results:
            self.logger.info('resolve_search: no artist match for "%s"', artist_text)
            return None, None

        artist_id = artist_results[0].get('id')
        self.logger.info('resolve_search: using the artist %s', artist_results[0].get('name'))

        song_results = self.fuzzy_search_song(search_text)
        song_dets = [item for item in song_results if item.get('artistId') == artist_id] if song_results else []

        if song_dets:
            song_dets = best_song_match(search_text, song_dets)
            top_score = match_score(search_text, song_dets[0].get('title', ''))

            if top_score >= MIN_ACCEPTABLE_SCORE:
                self.logger.info('resolve_search: matched via the artist scoped song step')
                return [item.get('id') for item in song_dets], f'{search_text} by {artist_text}'

        artist_album_lookup = self.connection.albums_by_artist(artist_id)

        if artist_album_lookup:
            candidate = best_album_match(search_text, artist_album_lookup)
            score = match_score(search_text, candidate.get('name', ''))

            if score >= MIN_ACCEPTABLE_SCORE:
                song_id_list = self.connection.build_song_list_from_albums([candidate], -1)
                return song_id_list, f'the album {candidate.get("name")} by {artist_text}'

        return None, None

    def _resolve_song(self, search_text: str) -> tuple:
        """Resolve a query as a song title

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.
        """

        song_results = self.fuzzy_search_song(search_text)

        if not song_results:
            return None, None

        song_results = best_song_match(search_text, song_results)
        top_score = match_score(search_text, song_results[0].get('title', ''))

        if top_score < MIN_ACCEPTABLE_SCORE:
            return None, None

        song_results = filter_to_best_matches(search_text, song_results)
        self.logger.info('resolve_search: the song step matched %s tracks', len(song_results))

        return [item.get('id') for item in song_results], search_text

    def _resolve_artist(self, search_text: str) -> tuple:
        """Resolve a query as an artist name

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.
        """

        artist_results = self.fuzzy_search_artist(search_text)

        if not artist_results:
            return None, None

        artist_name = artist_results[0].get('name', '')
        score = match_score(search_text, artist_name)
        corrected = self.correct_artist_spelling(search_text)
        was_corrected = (
            corrected is not None
            and corrected.lower() != search_text.lower()
            and corrected.lower() == artist_name.lower()
        )

        if not was_corrected and score < 3.0:
            self.logger.info(
                'resolve_search: artist step rejected "%s" (score %.2f < 3.0)', search_text, score
            )
            return None, None

        artist_album_lookup = self.connection.albums_by_artist(artist_results[0].get('id'))
        song_id_list = self.connection.build_song_list_from_albums(artist_album_lookup, SEARCH_RESULT_COUNT)

        if not song_id_list:
            return None, None

        random.shuffle(song_id_list)
        self.logger.info('resolve_search: the artist step matched "%s"', artist_results[0].get('name'))

        return song_id_list[:SEARCH_RESULT_COUNT], f'music by {search_text}'

    def _resolve_genre(self, search_text: str) -> tuple:
        """Resolve a query as a genre

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.
        """

        matched_genres = [genre for genre in self.known_genres if genre_matches(search_text, genre)]

        if not matched_genres:
            return None, None

        all_songs = []

        for genre in matched_genres:
            all_songs.extend(self.connection.build_song_list_from_genre(genre, self.min_song_count) or [])

        if not all_songs:
            return None, None

        random.shuffle(all_songs)
        self.logger.info('resolve_search: the genre step matched %s', matched_genres)

        return all_songs[:SEARCH_RESULT_COUNT], f'{search_text} music'

    def _resolve_album(self, search_text: str) -> tuple:
        """Resolve a query as an album title, the last resort

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.
        """

        album_results = self.fuzzy_search_album(search_text)

        if not album_results:
            self.logger.info('resolve_search: no match found for "%s"', search_text)
            return None, None

        best_album = best_album_match(search_text, album_results)
        song_id_list = self.connection.build_song_list_from_albums([best_album], -1)

        if not song_id_list:
            return None, None

        if len(song_id_list) == 1:
            # This "album" match is really a single track, so it is treated
            # as a song and the queue is extended with similar songs, rather
            # than stopping dead after one track.
            song_id = song_id_list[0]
            song_details = (self.connection.get_song_details(song_id) or {}).get('song') or {}
            song_title = song_details.get('title', search_text)
            song_artist = song_details.get('artist', 'an unknown artist')
            similar_ids = self.connection.get_similar_songs(song_id, self.min_song_count) or []
            combined = [song_id] + [item for item in similar_ids if item != song_id]

            return combined, f'{song_title} by {song_artist} and similar songs'

        found_artist = best_album.get('artist', 'an unknown artist')

        return song_id_list, f'the album {search_text} by {found_artist}'
