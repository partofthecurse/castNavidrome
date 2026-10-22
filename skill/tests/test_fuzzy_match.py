import unittest
from unittest.mock import MagicMock

try:
    import rapidfuzz  # noqa: F401
    _HAS_RAPIDFUZZ = True
except Exception:
    _HAS_RAPIDFUZZ = False

from castnavidrome.fuzzy_match import (
    CatalogCache, fuzzy_find_artist, fuzzy_find_album,
    fuzzy_find_genre, fuzzy_find_playlist,
)


@unittest.skipUnless(_HAS_RAPIDFUZZ, "rapidfuzz not installed")
class TestFuzzyMatch(unittest.TestCase):
    def test_artist_misspelled(self):
        conn = MagicMock()
        conn.conn.getArtists.return_value = {
            'artists': {'index': [{'artist': [{'id': '1', 'name': 'Radiohead'}]}]}
        }
        cache = CatalogCache(conn)
        result = fuzzy_find_artist(cache, "Radiehead")
        self.assertIsNotNone(result)
        self.assertEqual(result['name'], 'Radiohead')

    def test_genre_match(self):
        conn = MagicMock()
        conn.conn.getGenres.return_value = {
            'genres': {'genre': [{'value': 'Rock'}, {'value': 'Jazz'}]}
        }
        cache = CatalogCache(conn)
        result = fuzzy_find_genre(cache, "rok")
        self.assertEqual(result, 'Rock')

    def test_match_ignores_the_case(self):
        conn = MagicMock()
        conn.conn.getArtists.return_value = {
            'artists': {'index': [{'artist': [{'id': '1', 'name': 'Radiohead'}]}]}
        }
        conn.conn.getGenres.return_value = {
            'genres': {'genre': [{'value': 'Rock'}, {'value': 'Jazz'}]}
        }
        cache = CatalogCache(conn)
        self.assertEqual(fuzzy_find_genre(cache, "ROCK"), 'Rock')
        self.assertEqual(fuzzy_find_genre(cache, "rok"), 'Rock')
        self.assertEqual(fuzzy_find_artist(cache, "rAdIoHeAd")['name'], 'Radiohead')

    def test_playlist_match(self):
        playlists = [{'id': 'p1', 'name': 'My Favorites'}]
        result = fuzzy_find_playlist(playlists, "My Favourties")
        self.assertEqual(result, 'p1')

    def test_no_match(self):
        result = fuzzy_find_album([{'name': 'OK Computer'}], "zzzzzzzzzz", threshold=90)
        self.assertIsNone(result)

    def test_empty_catalog_defensive(self):
        conn = MagicMock()
        conn.conn.getArtists.return_value = None
        conn.conn.getGenres.return_value = {}
        cache = CatalogCache(conn)
        self.assertEqual(cache.get_artists(), [])
        self.assertEqual(cache.get_genres(), [])


if __name__ == '__main__':
    unittest.main()
