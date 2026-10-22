import unittest

from castnavidrome.queue_filler import split_initial_tracks


class QueueFillerTests(unittest.TestCase):
    def test_an_empty_list_stays_empty(self):
        # Ported from nigelg/asknavidrome (MIT): a play list without any
        # track must not raise an IndexError.
        self.assertEqual(split_initial_tracks([]), ([], []))

    def test_a_single_track_is_added_completely(self):
        self.assertEqual(split_initial_tracks(['a']), (['a'], []))

    def test_two_tracks_are_added_completely(self):
        self.assertEqual(split_initial_tracks(['a', 'b']), (['a', 'b'], []))

    def test_the_rest_is_returned_for_longer_lists(self):
        self.assertEqual(split_initial_tracks(['a', 'b', 'c', 'd']), (['a', 'b'], ['c', 'd']))

    def test_the_count_can_be_changed(self):
        self.assertEqual(split_initial_tracks(['a', 'b', 'c'], 1), (['a'], ['b', 'c']))

    def test_none_is_handled(self):
        self.assertEqual(split_initial_tracks(None), ([], []))
