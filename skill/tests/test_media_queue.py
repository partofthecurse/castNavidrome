import unittest

from castnavidrome.media_queue import MediaQueue
from castnavidrome.track import Track


def make_track(track_id='track-1', previous_id=''):
    return Track(id=track_id, title='A track', previous_id=previous_id)


class MediaQueueTests(unittest.TestCase):
    def setUp(self):
        self.queue = MediaQueue()

    def test_an_empty_buffer_has_no_next_track(self):
        # Ported from locqust/asknavidrome (MIT): an exhausted play queue
        # must not raise an IndexError.
        self.assertIsNone(self.queue.enqueue_next_track())

    def test_the_next_track_is_taken_from_the_buffer(self):
        self.queue.add_track(make_track('track-1'))
        self.queue.add_track(make_track('track-2'))
        self.queue.sync()

        self.assertEqual(self.queue.enqueue_next_track().id, 'track-1')

    def test_the_first_track_gets_the_previous_id(self):
        # Ported from bickns/asknavidrome (MIT)
        self.queue.add_track(make_track('track-1'))
        self.queue.set_first_previous_id('track-0')

        self.assertEqual(self.queue.get_current_queue()[0].previous_id, 'track-0')

    def test_an_empty_queue_is_not_chained(self):
        self.queue.set_first_previous_id('track-0')

        self.assertEqual(len(self.queue.get_current_queue()), 0)

    def test_the_playback_state_can_be_read_and_changed(self):
        self.assertFalse(self.queue.is_playback_active())

        self.queue.set_playback_active(True)

        self.assertTrue(self.queue.is_playback_active())

    def test_the_playback_state_is_not_shared_between_queues(self):
        first = MediaQueue()
        second = MediaQueue()

        first.set_playback_active(True)

        self.assertFalse(second.is_playback_active())

    def test_clear_resets_the_current_track(self):
        # Clearing the queue must not leave a stale current track behind,
        # otherwise the next get_next_track() would wrongly move the old
        # track into the history and desync the queue.
        self.queue.add_track(make_track('track-1'))
        self.queue.add_track(make_track('track-2'))
        self.queue.sync()
        self.queue.get_next_track()

        self.queue.clear()

        self.assertEqual(self.queue.get_current_track().id, '')
        self.assertEqual(len(self.queue.get_history()), 0)

    def test_get_next_track_after_clear_starts_at_the_first_track(self):
        # After clear() the current track is reset, so a fresh play starts at
        # the first track without moving a stale track into the history.
        self.queue.add_track(make_track('track-1'))
        self.queue.add_track(make_track('track-2'))
        self.queue.get_next_track()  # track-1 is now the current track

        self.queue.clear()
        self.queue.add_track(make_track('track-3'))
        self.queue.add_track(make_track('track-4'))

        track = self.queue.get_next_track()

        self.assertEqual(track.id, 'track-3')
        self.assertEqual(len(self.queue.get_history()), 0)
        self.assertEqual(len(self.queue.get_current_queue()), 1)

    def test_get_next_track_on_an_empty_queue_is_safe(self):
        # Calling get_next_track() on an empty queue must not raise and must
        # not corrupt the queue state.
        track = self.queue.get_next_track()

        self.assertEqual(track.id, '')
        self.assertEqual(len(self.queue.get_current_queue()), 0)
        self.assertEqual(len(self.queue.get_history()), 0)

    def test_get_next_track_and_enqueue_next_track_stay_in_sync(self):
        # Advancing through the queue with get_next_track() must keep the
        # buffer in sync so that enqueue_next_track() hands out the same
        # tracks in the same order.
        self.queue.add_track(make_track('track-1'))
        self.queue.add_track(make_track('track-2'))
        self.queue.add_track(make_track('track-3'))

        self.queue.get_next_track()  # track-1

        self.assertEqual(self.queue.enqueue_next_track().id, 'track-2')
        self.assertEqual(self.queue.enqueue_next_track().id, 'track-3')
        self.assertIsNone(self.queue.enqueue_next_track())

    def test_skipping_to_the_last_track_empties_the_queue(self):
        self.queue.add_track(make_track('track-1'))
        self.queue.add_track(make_track('track-2'))

        self.queue.get_next_track()  # track-1
        self.queue.get_next_track()  # track-2

        self.assertEqual(self.queue.get_current_track().id, 'track-2')
        self.assertEqual(len(self.queue.get_current_queue()), 0)
        self.assertEqual(len(self.queue.get_history()), 1)

    def test_an_unknown_skip_direction_is_ignored(self):
        self.queue.request_skip('forward')

        self.assertEqual(self.queue.consume_pending_skip(), '')

    def test_a_next_skip_can_be_requested_and_consumed(self):
        self.queue.request_skip('next')

        self.assertEqual(self.queue.consume_pending_skip(), 'next')
        self.assertEqual(self.queue.consume_pending_skip(), '')

    def test_a_previous_skip_can_be_requested_and_consumed(self):
        self.queue.request_skip('previous')

        self.assertEqual(self.queue.consume_pending_skip(), 'previous')
        self.assertEqual(self.queue.consume_pending_skip(), '')

    def test_only_the_last_skip_is_buffered(self):
        # Rapid Next/Previous presses must not flood the Amazon API.  Only
        # the last skip request is kept, so that the user ends up on the
        # track they wanted last.
        self.queue.request_skip('next')
        self.queue.request_skip('next')
        self.queue.request_skip('previous')

        self.assertEqual(self.queue.consume_pending_skip(), 'previous')

    def test_the_transitioning_state_can_be_read_and_changed(self):
        self.assertFalse(self.queue.is_transitioning())

        self.queue.set_transitioning(True)

        self.assertTrue(self.queue.is_transitioning())

    def test_the_transitioning_state_is_not_shared_between_queues(self):
        first = MediaQueue()
        second = MediaQueue()

        first.set_transitioning(True)

        self.assertFalse(second.is_transitioning())

    def test_clear_resets_the_pending_skip(self):
        self.queue.request_skip('next')

        self.queue.clear()

        self.assertEqual(self.queue.consume_pending_skip(), '')
