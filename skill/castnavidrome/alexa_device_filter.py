"""Selection of the Alexa devices that are exposed as UPnP media renderers.

The filter is configured with environment variables so that it can be changed
without touching the code:

``NAVI_ALEXA_RENDERER_DEVICE_TYPES``
    Comma separated list of allowed device types. An empty value allows every
    device type. A device matches when its device family (``ECHO``,
    ``FIRE_TV``, ``TABLET``, ...) or its device type id matches one of the
    configured values.

``NAVI_ALEXA_RENDERER_EXCLUDED_DEVICE_TYPES``
    Comma separated list of device types that are never exposed. Defaults to
    the tablet and e-reader types. Set the value to a name that never matches
    a device type to disable the built-in exclusion.

``NAVI_ALEXA_RENDERER_NAME_INCLUDE``
    Comma separated list of device names. When set, only devices with one of
    these names are exposed.

``NAVI_ALEXA_RENDERER_NAME_EXCLUDE``
    Comma separated list of device names that are never exposed.

``NAVI_ALEXA_RENDERER_NAME_REGEX``
    Regular expression that the device name has to match.

``NAVI_ALEXA_RENDERER_ONLY_ONLINE``
    When set to a truthy value only devices that are currently online are
    exposed.
"""

import os
import re

DEFAULT_EXCLUDED_DEVICE_TYPES = (
    'TABLET',
    'E_READER',
    'EBOOK_READER',
    'KINDLE',
    'ECHO_READER',
    'FIRE_READER',
)

TRUTHY_VALUES = ('1', 'true', 'yes', 'on')


def _split_list(value: str) -> tuple:
    """Split a comma separated environment value into a tuple of strings."""

    if not value:
        return ()

    return tuple(item.strip() for item in value.split(',') if item.strip())


def _is_truthy(value: str) -> bool:
    return bool(value) and value.strip().lower() in TRUTHY_VALUES


def _matches_type(device_type: str, candidates: tuple) -> bool:
    """Return True when the device type matches one of the candidates."""

    normalized = (device_type or '').strip().upper()

    for candidate in candidates:
        candidate = candidate.strip().upper()
        if not candidate:
            continue
        if normalized == candidate or normalized.startswith(candidate + '_'):
            return True

    return False


def _matches_any_type(device: dict, candidates: tuple) -> bool:
    """Return True when the device family or the device type matches."""

    if not candidates:
        return False

    family = device.get('deviceFamily') or ''
    device_type = device.get('deviceType') or ''

    return _matches_type(family, candidates) or _matches_type(device_type, candidates)


class DeviceFilter:
    """Decides which Alexa devices are turned into UPnP media renderers."""

    def __init__(self,
                 device_types: tuple = (),
                 excluded_device_types: tuple = DEFAULT_EXCLUDED_DEVICE_TYPES,
                 name_include: tuple = (),
                 name_exclude: tuple = (),
                 name_regex: str = '',
                 only_online: bool = False) -> None:
        self.device_types = tuple(device_types)
        self.excluded_device_types = tuple(excluded_device_types)
        self.name_include = tuple(name_include)
        self.name_exclude = tuple(name_exclude)
        self.name_regex = name_regex or ''
        self.only_online = bool(only_online)

        self._name_pattern = re.compile(self.name_regex) if self.name_regex else None

    @classmethod
    def from_env(cls, env=None) -> 'DeviceFilter':
        env = os.environ if env is None else env

        excluded = env.get('NAVI_ALEXA_RENDERER_EXCLUDED_DEVICE_TYPES', '')
        if not excluded or not excluded.strip():
            excluded_device_types = DEFAULT_EXCLUDED_DEVICE_TYPES
        else:
            excluded_device_types = _split_list(excluded)

        return cls(
            device_types=_split_list(env.get('NAVI_ALEXA_RENDERER_DEVICE_TYPES', '')),
            excluded_device_types=excluded_device_types,
            name_include=_split_list(env.get('NAVI_ALEXA_RENDERER_NAME_INCLUDE', '')),
            name_exclude=_split_list(env.get('NAVI_ALEXA_RENDERER_NAME_EXCLUDE', '')),
            name_regex=env.get('NAVI_ALEXA_RENDERER_NAME_REGEX', ''),
            only_online=_is_truthy(env.get('NAVI_ALEXA_RENDERER_ONLY_ONLINE', '')),
        )

    def matches(self, device: dict) -> bool:
        """Return True when the given Alexa device should become a renderer."""

        if not isinstance(device, dict):
            return False

        name = device.get('name') or ''

        if self.name_include and name.strip().casefold() not in {
                candidate.strip().casefold() for candidate in self.name_include}:
            return False

        if name.strip().casefold() in {candidate.strip().casefold() for candidate in self.name_exclude}:
            return False

        if self._name_pattern and not self._name_pattern.search(name):
            return False

        if self.excluded_device_types and _matches_any_type(device, self.excluded_device_types):
            return False

        if self.device_types and not _matches_any_type(device, self.device_types):
            return False

        if self.only_online and not device.get('online'):
            return False

        return True

    def filter(self, devices: list) -> list:
        """Return the subset of the given devices that matches the filter."""

        return [device for device in devices or [] if self.matches(device)]
