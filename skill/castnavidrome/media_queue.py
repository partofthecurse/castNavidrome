"""The play queue of a single Alexa device.

The module provides the MediaQueue class, which stores the tracks that are
still to be played, the tracks that have already been played and a buffer of
tracks that are queued ahead for the Amazon 8 second timeout.  The queue is
shared between processes through a BaseManager so that background threads can
fill it while the web service answers requests.
"""

from collections import deque
from copy import deepcopy
import logging
import random

from .track import Track


class MediaQueue:
    """ The MediaQueue class

    This class provides a queue based on a Python deque.  This is used to store
    the tracks in the current play queue
    """

    def __init__(self) -> None:
        """
        :return: None
        """

        self.logger = logging.getLogger(__name__)
        """Logger"""

        self.queue: deque = deque()
        """Deque containing tracks still to be played"""

        self.history: deque = deque()
        """Deque to hold tracks that have already been played"""

        self.buffer: deque = deque()
        """Deque to contain the list of tracks to be enqueued

        This deque is created from self.queue when actions such as next or
        previous are performed.  This is because Amazon can send the
        PlaybackNearlyFinished request early.  Without self.buffer, this would
        change self.current_track causing us to lose the real position of the
        queue.
        """

        self.current_track: Track = Track()
        """Property to hold the current track object"""

        self.playback_active: bool = False
        """Property to hold the state of the playback

        It is used to find out if a new track has to be chained to the
        currently playing one, so that the ENQUEUE directive of Amazon is
        accepted.
        """

    def is_playback_active(self) -> bool:
        """Method to return the state of the playback

        Added to allow access to the playback_active attribute while using
        BaseManager for multi threading, as BaseManager does not allow access
        to class attributes / properties

        :return: True if a track is currently being played
        :rtype: bool
        """
        return self.playback_active

    def set_playback_active(self, active: bool) -> None:
        """Method to set the state of the playback

        :param active: True if a track is currently being played
        :type active: bool
        """

        self.playback_active = active

    def set_first_previous_id(self, previous_id: str) -> None:
        """Set the previous_id of the first track in the queue

        Needed when the queue is refilled while a track is playing:
        add_track() only chains a new track against whatever is already in
        the queue, so the very first track added to an empty queue gets no
        previous_id at all.  Without it the ENQUEUE directive of Amazon is
        rejected, because the expected previous token does not match the
        track that is playing.

        This has to be a method call and not a change of a returned copy of
        the queue, because get_current_queue() returns a pickled copy over
        the multiprocessing proxy boundary, so changing it locally would have
        no effect on the real queue.

        Ported from bickns/asknavidrome (MIT), see CREDITS.md.

        :param previous_id: The ID of the track that is playing
        :type previous_id: str
        """

        self.logger.debug('In set_first_previous_id()')

        if not self.queue:
            self.logger.debug('The queue is empty, there is no track to chain')
            return

        self.queue[0].previous_id = previous_id

    def get_current_track(self) -> Track:
        """Method to return current_track attribute

        Added to allow access to the current_track object while using BaseManager
        for multi threading, as BaseManager does not allow access to class
        attributes / properties

        :return: A Track object representing the current playing audio track
        :rtype: Track
        """
        return self.current_track

    def set_current_track_offset(self, offset: int) -> None:
        """Method to set the offset of the current track in milliseconds

        Set the offset for the current track in milliseconds.  This is used
        when resuming a paused track to ensure the track isn't played from
        the beginning again.

        :param offset: The track offset in milliseconds
        :type offset: int
        """

        self.current_track.offset = offset

    def get_current_queue(self) -> deque:
        """Get the current queue

        Returns a deque containing the current queue of music to be played

        :return: The current queue
        :rtype: deque
        """

        return self.queue

    def get_buffer(self) -> deque:
        """Get the buffer

        Returns a deque containing the current buffer

        :return: The current buffer
        :rtype: deque
        """

        return self.buffer

    def get_history(self) -> deque:
        """Get history

        Returns a deque of tracks that have already been played

        :return: A deque container tracks that have already been played
        :rtype: deque
        """

        return self.history

    def add_track(self, track: Track) -> None:
        """Add tracks to the queue

        :param Track track: A Track object containing details of the track to be played
        :return: None
        """

        self.logger.debug('In add_track()')

        if not self.queue:
            # This is the first track in the queue
            self.queue.append(track)
        else:
            # There are already tracks in the queue, ensure previous_id is set

            # Get the last track from the deque
            prev_track = self.queue.pop()

            # Set the previous_id attribute
            track.previous_id = prev_track.id

            # Return the previous track to the deque
            self.queue.append(prev_track)

            # Add the new track to the deque
            self.queue.append(track)

        self.logger.debug(f'In add_track() - there are {len(self.queue)} tracks in the queue')

    def shuffle(self) -> None:
        """Shuffle the queue

        Shuffles the queue and resets the previous track IDs required for the ENQUEUE PlayBehaviour

        :return: None
        """

        self.logger.debug('In shuffle()')

        # Copy the original queue
        orig = self.queue
        new_queue = deque()

        # Randomise the queue
        random.shuffle(orig)

        track_id = None

        for t in orig:
            if not new_queue:
                # This is the first track, get the ID and add it
                track_id = t.id
                new_queue.append(t)
            else:
                # Set the tracks previous_id
                t.previous_id = track_id

                # Get the track ID to use as the next previous_id
                track_id = t.id

                # Add the track to the queue
                new_queue.append(t)

        # Replace the original queue with the new shuffled one
        self.queue = new_queue

    def get_next_track(self) -> Track:
        """Get the next track

        Get the next track from self.queue and add it to the history deque

        :return: The next track object
        :rtype: Track
        """

        self.logger.debug('In get_next_track()')

        if not self.queue:
            # The queue is exhausted, there is no next track to skip to.
            # Return the current track unchanged instead of raising, so that
            # a caller that skipped the empty-queue guard still gets a sane
            # result and the queue state is not corrupted.
            self.logger.debug('The queue is empty, keeping the current track')
            return self.current_track

        if self.current_track.id == '' or self.current_track.id is None:
            # This is the first track
            self.current_track = self.queue.popleft()
        else:
            # This is not the first track
            self.history.append(self.current_track)
            self.current_track = self.queue.popleft()

        # Set the buffer to match the queue
        self.sync()

        return self.current_track

    def get_previous_track(self) -> Track:
        """Get the previous track

        Get the last track added to the history deque and
        add it to the front of the play queue

        :return: The previous track object
        :rtype: Track
        """

        self.logger.debug('In get_previous_track()')

        # Return the current track to the queue
        self.queue.appendleft(self.current_track)

        # Set the new current track
        self.current_track = self.history.pop()

        # Set the buffer to match the queue
        self.sync()

        return self.current_track

    def enqueue_next_track(self) -> Track:
        """Get the next buffered track

        Get the next track from the buffer without updating the current track
        attribute.  This allows Amazon to send the PlaybackNearlyFinished
        request early to queue the next track while maintaining the playlist

        If the buffer is empty, None is returned instead of raising an
        IndexError, so that an exhausted play queue ends the playback
        cleanly.

        Ported from locqust/asknavidrome (MIT), see CREDITS.md.

        :return: The next track to be played, or None if the buffer is empty
        :rtype: Track | None
        """

        self.logger.debug('In enqueue_next_track()')

        if not self.buffer:
            self.logger.debug('The buffer is empty, there is no next track to enqueue')
            return None

        return self.buffer.popleft()

    def set_current_track(self, track: Track) -> None:
        """Set the current track without queueing it

        This is used for the radio streams, they are not part of a play
        list and there is no next track.

        Ported from mpdeglau/asknavidrome (MIT), see CREDITS.md.

        :param Track track: The track that is played
        :return: None
        """

        self.logger.debug('In set_current_track()')

        self.current_track = track

    def clear(self) -> None:
        """Clear queue, history, buffer and the current track

        :return: None
        """

        self.logger.debug('In clear()')
        self.queue.clear()
        self.history.clear()
        self.buffer.clear()
        self.current_track = Track()
        """Reset the current track so that a new play list starts from a
        clean state and no stale track is carried over into the history
        or reported as the track that is playing."""

    def get_queue_count(self) -> int:
        """Get the number of tracks in the queue

        :return: The number of tracks in the queue deque
        :rtype: int
        """

        self.logger.debug('In get_queue_count()')
        return len(self.queue)

    def get_history_count(self) -> int:
        """Get the number of tracks in the history deque

        :return: The number of tracks in the history deque
        :rtype: int
        """

        self.logger.debug('In get_history_count()')
        return len(self.history)

    def sync(self) -> None:
        """Synchronise the buffer with the queue

        Overwrite the buffer with the current queue.
        This is useful when pausing or stopping to ensure
        the resulting PlaybackNearlyFinished request gets
        the correct.  In practice this will have already
        queued and there for missing from the current buffer

        :return: None
        """

        self.buffer = deepcopy(self.queue)
