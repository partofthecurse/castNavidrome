"""Helpers for filling the play queue.

The Amazon / Alexa skill has a response timeout of eight seconds, so the
first tracks of a play list are added to the queue synchronously and the
remaining ones are added by a background process.

Ported from nigelg/asknavidrome (MIT), see CREDITS.md for the full list of
changes.
"""

import logging


logger = logging.getLogger(__name__)


def split_initial_tracks(song_id_list: list, count: int = 2) -> tuple:
    """Split a list of song IDs into the tracks to add first and the rest.

    Play lists with fewer than `count` tracks are returned completely as the
    first part, so that no IndexError is raised for a play list that holds
    no or only a single track.

    :param song_id_list: A list containing Navidrome song IDs
    :param count: The number of tracks to add synchronously
    :return: A tuple of the tracks to add first and the tracks to add later
    :rtype: tuple
    """

    if song_id_list is None:
        return [], []

    if len(song_id_list) <= count:
        return list(song_id_list), []

    return list(song_id_list[:count]), list(song_id_list[count:])
