import unittest

from castnavidrome.cover_art import DEFAULT_ART_URL, build_cover_art_url, get_art_url


class CoverArtTests(unittest.TestCase):
    def test_the_url_points_to_the_proxy(self):
        # Ported from locqust/asknavidrome (MIT)
        url = build_cover_art_url('https://skill.example.com', 'al-42')

        self.assertEqual(url, 'https://skill.example.com/cover/al-42')

    def test_a_trailing_slash_is_removed(self):
        url = build_cover_art_url('https://skill.example.com/', 'al-42')

        self.assertEqual(url, 'https://skill.example.com/cover/al-42')

    def test_the_cover_id_is_escaped(self):
        url = build_cover_art_url('https://skill.example.com', 'al 42/1')

        self.assertEqual(url, 'https://skill.example.com/cover/al%2042%2F1')

    def test_without_a_base_url_there_is_no_url(self):
        self.assertEqual(build_cover_art_url('', 'al-42'), '')

    def test_without_a_cover_id_there_is_no_url(self):
        self.assertEqual(build_cover_art_url('https://skill.example.com', ''), '')

    def test_without_cover_art_the_logo_is_used(self):
        self.assertEqual(get_art_url('https://skill.example.com', ''), DEFAULT_ART_URL)

    def test_with_cover_art_the_proxy_is_used(self):
        url = get_art_url('https://skill.example.com', 'al-42')

        self.assertEqual(url, 'https://skill.example.com/cover/al-42')
