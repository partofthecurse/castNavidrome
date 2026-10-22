import unittest

from castnavidrome.search import (
    SearchResolver,
    best_album_match,
    best_song_match,
    filter_to_best_matches,
    genre_matches,
    match_score,
    parse_query_for_artist,
    search_variants,
)


class FakeConnection:
    """A media server that only knows a few songs, artists and albums"""

    def __init__(self):
        self.songs = [
            {'id': 's1', 'title': 'Hush', 'artist': 'Abby', 'artistId': 'a1'},
            {'id': 's2', 'title': 'Hush Hush', 'artist': 'Someone Else', 'artistId': 'a2'},
            {'id': 's3', 'title': 'Bad Romance', 'artist': 'Lady G', 'artistId': 'a3'},
            {'id': 's4', 'title': 'Midnight City', 'artist': 'M83', 'artistId': 'a4'},
            {'id': 's5', 'title': 'Kids', 'artist': 'MGMT', 'artistId': 'a5'},
        ]
        self.artists = [
            {'id': 'a1', 'name': 'Abby'},
            {'id': 'a3', 'name': 'Lady G'},
            {'id': 'a4', 'name': 'M83'},
            {'id': 'a5', 'name': 'MGMT'},
        ]
        self.albums = [
            {'id': 'al1', 'name': 'The Album', 'artist': 'Abby', 'songCount': 2},
        ]

    def search_song(self, term, count=20):
        term = (term or '').lower()

        return [song for song in self.songs if term in song['title'].lower()]

    def search_artist(self, term, count=20):
        term = (term or '').lower()

        return [artist for artist in self.artists if term in artist['name'].lower()]

    def search_album(self, term, count=20):
        term = (term or '').lower()

        return [album for album in self.albums if term in album['name'].lower()]

    def albums_by_artist(self, artist_id):
        return [album for album in self.albums if album.get('artistId') == artist_id or album.get('artist') == 'Abby']

    def build_song_list_from_albums(self, albums, length):
        return [song['id'] for album in albums for song in self.songs if song['artist'] == album.get('artist')]

    def build_song_list_from_genre(self, genre, count):
        return []

    def get_song_details(self, song_id):
        for song in self.songs:
            if song['id'] == song_id:
                return {'song': song}

        return {}

    def get_similar_songs(self, song_id, count=50):
        return ['s2']


class SearchHelpersTests(unittest.TestCase):
    def test_a_genre_is_matched_by_its_whole_words(self):
        # Ported from bickns/asknavidrome (MIT)
        self.assertTrue(genre_matches('dance', 'dance-pop'))
        self.assertFalse(genre_matches('dance', 'dancehall'))

    def test_a_query_with_an_artist_is_split(self):
        # Ported from bickns/asknavidrome (MIT)
        self.assertEqual(parse_query_for_artist('Hush by Abby'), ('Hush', 'Abby'))

    def test_a_query_without_an_artist_is_kept(self):
        self.assertEqual(parse_query_for_artist('Hush'), ('Hush', None))

    def test_the_filler_words_are_removed(self):
        self.assertEqual(parse_query_for_artist('the song Hush by the artist Abby'), ('Hush', 'Abby'))

    def test_the_variants_cover_the_punctuation(self):
        # Ported from bickns/asknavidrome (MIT)
        variants = search_variants('Simon and Garfunkel')

        self.assertIn('Simon & Garfunkel', variants)
        self.assertIn('Simon and Garfunkel', variants)

    def test_an_exact_match_scores_the_highest(self):
        self.assertEqual(match_score('hush', 'Hush'), 4.0)

    def test_a_prefix_match_scores_high(self):
        self.assertEqual(match_score('hus', 'Hush'), 3.0)

    def test_a_substring_match_scores_lower(self):
        self.assertEqual(match_score('ush', 'Hush'), 2.0)

    def test_the_best_song_comes_first(self):
        # Ported from bickns/asknavidrome (MIT)
        songs = [{'title': 'Hush Hush'}, {'title': 'Hush'}]

        self.assertEqual(best_song_match('Hush', songs)[0]['title'], 'Hush')

    def test_the_loosely_related_songs_are_filtered(self):
        # Ported from bickns/asknavidrome (MIT)
        songs = [{'title': 'Hush'}, {'title': 'Hush Hush'}, {'title': 'Bad Romance'}]

        filtered = filter_to_best_matches('Hush', songs)

        self.assertEqual(len(filtered), 1)

    def test_the_best_album_is_chosen(self):
        # Ported from bickns/asknavidrome (MIT)
        albums = [{'name': 'The Album'}, {'name': 'The Album Deluxe'}]

        self.assertEqual(best_album_match('The Album', albums)['name'], 'The Album')


class SearchResolverTests(unittest.TestCase):
    def setUp(self):
        self.resolver = SearchResolver(FakeConnection(), 10)

    def test_a_song_is_found(self):
        song_ids, description = self.resolver.resolve('Hush')

        self.assertIn('s1', song_ids)
        self.assertEqual(description, 'Hush')

    def test_a_song_with_an_artist_is_found(self):
        # Ported from bickns/asknavidrome (MIT)
        song_ids, description = self.resolver.resolve('Hush by Abby')

        self.assertIn('s1', song_ids)
        self.assertIn('Abby', description)

    def test_an_artist_is_found(self):
        song_ids, description = self.resolver.resolve('Abby')

        self.assertTrue(song_ids)
        self.assertIn('music by', description)

    def test_a_short_artist_name_is_found(self):
        song_ids, description = self.resolver.resolve('M83')

        self.assertTrue(song_ids)
        self.assertIn('M83', description)

    def test_another_short_artist_name_is_found(self):
        song_ids, description = self.resolver.resolve('MGMT')

        self.assertTrue(song_ids)
        self.assertIn('MGMT', description)

    def test_nothing_is_found_for_an_unknown_query(self):
        song_ids, description = self.resolver.resolve('nothinglikethis')

        self.assertIsNone(song_ids)
        self.assertIsNone(description)
