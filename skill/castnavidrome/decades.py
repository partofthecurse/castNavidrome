"""The decades that the skill can play.

Ported from bickns/asknavidrome (MIT), see CREDITS.md.  The handling of the
German and the English spelling of a decade is our own local change.
"""

import logging


logger = logging.getLogger(__name__)

DECADE_RANGES = {
    '1920': (1920, 1929),
    '1930': (1930, 1939),
    '1940': (1940, 1949),
    '1950': (1950, 1959),
    '1960': (1960, 1969),
    '1970': (1970, 1979),
    '1980': (1980, 1989),
    '1990': (1990, 1999),
    '2000': (2000, 2009),
    '2010': (2010, 2019),
    '2020': (2020, 2029),
}

DECADE_SUFFIXES = ('s', 'er', 'ern', 's', "'s")


def normalise_decade(decade: str) -> str:
    """Get the four digit prefix of a decade

    The slot value of the decade can be written in different ways, for
    example "1990s", "1990er" or "the nineties".  Only the digits are used,
    so that every spelling of a decade can be found.

    :param str decade: The value of the decade
    :return: The four digit prefix of the decade or an empty string
    :rtype: str
    """

    if not decade:
        return ''

    digits = ''.join(character for character in str(decade) if character.isdigit())

    if len(digits) < 4:
        return ''

    return digits[:4]


def get_range(decade: str) -> tuple:
    """Get the first and the last year of a decade

    :param str decade: The value of the decade
    :return: A tuple of the first and the last year, empty if the decade is unknown
    :rtype: tuple
    """

    prefix = normalise_decade(decade)

    if prefix not in DECADE_RANGES:
        logger.warning('Unknown decade: %s', decade)
        return (), ()

    return DECADE_RANGES[prefix]
