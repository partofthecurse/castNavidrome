import unittest

from castnavidrome.decades import DECADE_RANGES, get_range, normalise_decade
from castnavidrome.playlist_names import PlaylistNames


class DecadesTests(unittest.TestCase):
    def test_a_decade_is_normalised_to_its_prefix(self):
        self.assertEqual(normalise_decade('1990er'), '1990')

    def test_an_english_decade_is_normalised(self):
        self.assertEqual(normalise_decade('1990s'), '1990')

    def test_a_number_is_normalised(self):
        self.assertEqual(normalise_decade('1990'), '1990')

    def test_a_word_without_a_number_has_no_prefix(self):
        self.assertEqual(normalise_decade('neunziger'), '')

    def test_the_range_of_a_decade_is_returned(self):
        self.assertEqual(get_range('1980er'), (1980, 1989))

    def test_an_unknown_decade_has_no_range(self):
        from_year, to_year = get_range('2120')

        self.assertFalse(from_year)
        self.assertFalse(to_year)

    def test_all_the_decades_have_a_range(self):
        for decade in DECADE_RANGES:
            from_year, to_year = get_range(decade)

            self.assertEqual(to_year - from_year, 9)


class PlaylistNamesTests(unittest.TestCase):
    def setUp(self):
        self.names = PlaylistNames()

    def test_a_grouped_name_is_split(self):
        self.assertEqual(self.names.parse('Rock - Easy Drive'), ('Rock', 'Easy Drive'))

    def test_the_machine_suffix_is_removed(self):
        self.assertEqual(self.names.parse('Rock - Easy Drive_automatic'), ('Rock', 'Easy Drive'))

    def test_a_name_without_a_group_is_not_split(self):
        self.assertIsNone(self.names.parse('Play-Rewind'))

    def test_the_group_of_a_name(self):
        self.assertEqual(self.names.group_of('Rock - Easy Drive'), 'Rock')

    def test_a_name_without_a_group_has_no_group(self):
        self.assertIsNone(self.names.group_of('Play-Rewind'))

    def test_the_spoken_form_drops_the_group(self):
        self.assertEqual(self.names.spoken('Rock - Easy Drive'), 'Easy Drive')

    def test_the_qualified_form_keeps_the_group(self):
        self.assertEqual(self.names.qualified('Rock - Easy Drive'), 'Rock Easy Drive')

    def test_a_name_without_a_group_is_spoken_as_it_is(self):
        self.assertEqual(self.names.spoken('Play-Rewind'), 'Play-Rewind')

    def test_colliding_names_are_qualified(self):
        spoken = self.names.spoken_list(['Rock - Easy Drive', 'Pop - Easy Drive'])

        self.assertEqual(spoken, ['Rock Easy Drive', 'Pop Easy Drive'])

    def test_names_without_a_collision_stay_short(self):
        spoken = self.names.spoken_list(['Rock - Easy Drive', 'Pop - Slow Ride'])

        self.assertEqual(spoken, ['Easy Drive', 'Slow Ride'])

    def test_the_match_forms_contain_every_spelling(self):
        forms = self.names.match_forms('Rock - Easy Drive_automatic')

        self.assertIn('Rock - Easy Drive_automatic', forms)
        self.assertIn('Easy Drive', forms)
        self.assertIn('Rock Easy Drive', forms)

    def test_the_groups_are_compared_loosely(self):
        self.assertEqual(PlaylistNames.normalize_group('R & B'), PlaylistNames.normalize_group('R and B'))

    def test_the_names_are_compared_loosely(self):
        self.assertEqual(PlaylistNames.normalize_name('Play-Rewind'), PlaylistNames.normalize_name('play rewind'))
