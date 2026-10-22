import logging
import unittest

from castnavidrome.subsonic_api import SubsonicConnection


class FakeConn:
    """A stand in for the libsonic connection."""

    def __init__(self, now_playing=None, album=None, playlist=None, song=None, songs=None):
        self.now_playing = now_playing or {'nowPlaying': {}}
        self.album = album
        self.playlist = playlist
        self.song = song
        self.songs = songs or []
        self.requested = []

    def getNowPlaying(self):
        return self.now_playing

    def getAlbum(self, album_id):
        self.requested.append(('getAlbum', album_id))

        if self.album is None:
            raise ValueError('The album does not exist.')

        return {'album': {'song': self.album}}

    def getPlaylist(self, playlist_id):
        self.requested.append(('getPlaylist', playlist_id))

        if self.playlist is None:
            raise ValueError('The play list does not exist.')

        return {'playlist': {'entry': self.playlist}}

    def getSong(self, song_id):
        self.requested.append(('getSong', song_id))

        if self.song is None:
            raise ValueError('The song does not exist.')

        return {'song': self.song}

    def search3(self, query, songCount=None, artistCount=None, albumCount=None):
        self.requested.append(('search3', query))

        return {'searchResult3': {'song': self.songs}}


def make_connection(conn: FakeConn) -> SubsonicConnection:
    connection = SubsonicConnection.__new__(SubsonicConnection)
    connection.logger = logging.getLogger(__name__)
    connection.conn = conn

    return connection


class NowPlayingTests(unittest.TestCase):
    def test_a_track_of_another_client_is_found(self):
        conn = FakeConn(now_playing={'nowPlaying': {'entry': [
            {'id': '42', 'player': 'Jellybox (Echo Dot)'},
        ]}})

        self.assertTrue(make_connection(conn).is_now_playing_reported_by_other_client('42'))

    def test_the_own_entry_of_the_skill_is_not_a_report_of_another_client(self):
        conn = FakeConn(now_playing={'nowPlaying': {'entry': [
            {'id': '42', 'player': 'AskNavidrome-A7AL2IPY'},
        ]}})

        self.assertFalse(make_connection(conn).is_now_playing_reported_by_other_client('42'))

    def test_another_track_is_not_a_report(self):
        conn = FakeConn(now_playing={'nowPlaying': {'entry': [
            {'id': '43', 'player': 'Jellybox (Echo Dot)'},
        ]}})

        self.assertFalse(make_connection(conn).is_now_playing_reported_by_other_client('42'))

    def test_an_empty_now_playing_list_is_handled(self):
        conn = FakeConn(now_playing={'nowPlaying': {}})

        self.assertFalse(make_connection(conn).is_now_playing_reported_by_other_client('42'))

    def test_a_single_entry_is_handled(self):
        conn = FakeConn(now_playing={'nowPlaying': {'entry': {'id': '42', 'player': 'Jellybox'}}})

        self.assertTrue(make_connection(conn).is_now_playing_reported_by_other_client('42'))


class CollectionTests(unittest.TestCase):
    def test_the_songs_of_an_album_are_returned(self):
        conn = FakeConn(album=[{'id': '42'}, {'id': '43'}])

        songs = make_connection(conn).get_album_songs('album-1')

        self.assertEqual([song['id'] for song in songs], ['42', '43'])

    def test_a_single_song_of_an_album_is_returned_as_a_list(self):
        conn = FakeConn(album={'id': '42'})

        songs = make_connection(conn).get_album_songs('album-1')

        self.assertEqual([song['id'] for song in songs], ['42'])

    def test_an_unknown_album_returns_no_songs(self):
        conn = FakeConn(album=None)

        self.assertEqual(make_connection(conn).get_album_songs('album-1'), [])

    def test_the_songs_of_a_playlist_are_returned(self):
        conn = FakeConn(playlist=[{'id': '42'}, {'id': '43'}])

        songs = make_connection(conn).get_playlist_songs('playlist-1')

        self.assertEqual([song['id'] for song in songs], ['42', '43'])

    def test_an_unknown_playlist_returns_no_songs(self):
        conn = FakeConn(playlist=None)

        self.assertEqual(make_connection(conn).get_playlist_songs('playlist-1'), [])

    def test_a_song_is_found_by_its_title_and_its_artist(self):
        conn = FakeConn(songs=[
            {'id': '42', 'title': 'Some Song', 'artist': 'Some Artist'},
            {'id': '43', 'title': 'Some Song', 'artist': 'Another Artist'},
        ])

        song = make_connection(conn).find_song_by_title('Some Song', 'Another Artist')

        self.assertEqual(song['id'], '43')

    def test_the_first_song_is_used_when_the_artist_does_not_match(self):
        conn = FakeConn(songs=[{'id': '42', 'title': 'Some Song', 'artist': 'Some Artist'}])

        song = make_connection(conn).find_song_by_title('Some Song', 'Unknown Artist')

        self.assertEqual(song['id'], '42')

    def test_an_unknown_song_is_not_found(self):
        conn = FakeConn(songs=[])

        self.assertIsNone(make_connection(conn).find_song_by_title('Some Song', 'Some Artist'))


if __name__ == '__main__':
    unittest.main()
