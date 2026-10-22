"""Persistent mapping between an Alexa device and its UPnP renderer identity.

Every Alexa device that is exposed as a media renderer owns a stable UUID.
The UUID is derived from the device identity (owner id and serial number) so
that it survives restarts of the renderer host, and it is additionally stored
in a small JSON file. The file keeps the mapping alive even if the device
identity changes in a way that would produce a different UUID, and it allows
the friendly name to be restored after a rename of the device.
"""

import json
import logging
import os
import tempfile
import uuid

logger = logging.getLogger(__name__)

# Namespace for the deterministic renderer UUIDs, derived from the project name.
RENDERER_UUID_NAMESPACE = uuid.UUID('6b1a5b64-9f6d-5f5e-9d43-2f8a2b6a1f30')

REGISTRY_VERSION = 1


def device_identity_key(device: dict) -> str:
    """Return a stable key for the given Alexa device.

    The serial number together with the owner id identifies a device across
    renames. Devices without a serial number fall back to their name.
    """

    if not isinstance(device, dict):
        return ''

    owner = (device.get('deviceOwnerCustomerId') or '').strip()
    serial = (device.get('serialNumber') or '').strip()
    name = (device.get('name') or '').strip().casefold()

    if serial:
        return f'{owner}:{serial}'

    return f'{owner}:name:{name}'


def derive_uuid(device: dict) -> str:
    """Derive a deterministic UUID for the given Alexa device."""

    key = device_identity_key(device)

    return str(uuid.uuid5(RENDERER_UUID_NAMESPACE, key))


class RendererRegistry:
    """Stores the UUID and friendly name of every known media renderer."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._devices = {}
        self._loaded = False

    def load(self) -> None:
        """Read the registry from disk. Missing or broken files are ignored."""

        self._devices = {}
        self._loaded = True

        if not self.path or not os.path.isfile(self.path):
            logger.info('No renderer registry found at %s, starting with an empty registry.', self.path)
            return

        try:
            with open(self.path, 'r', encoding='utf-8') as registry_file:
                data = json.load(registry_file)
        except (OSError, ValueError) as error:
            logger.warning('Could not read the renderer registry %s: %s', self.path, error)
            return

        devices = data.get('devices') if isinstance(data, dict) else None
        if not isinstance(devices, dict):
            return

        for key, entry in devices.items():
            if isinstance(entry, dict) and entry.get('uuid'):
                self._devices[key] = dict(entry)

        logger.info('Loaded %s renderer(s) from %s.', len(self._devices), self.path)

    def save(self) -> None:
        """Write the registry to disk."""

        if not self.path:
            return

        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)

        payload = {
            'version': REGISTRY_VERSION,
            'devices': self._devices,
        }

        handle, temporary_path = tempfile.mkstemp(dir=directory or '.', prefix='.renderers-', suffix='.json')
        try:
            with os.fdopen(handle, 'w', encoding='utf-8') as registry_file:
                json.dump(payload, registry_file, indent=2, sort_keys=True)
                registry_file.write('\n')
            os.replace(temporary_path, self.path)
        except OSError as error:
            logger.warning('Could not write the renderer registry %s: %s', self.path, error)
            try:
                os.unlink(temporary_path)
            except OSError:
                pass

    def register(self, device: dict, friendly_name: str = '') -> dict:
        """Return the registry entry of a device and create it when needed."""

        if not self._loaded:
            self.load()

        key = device_identity_key(device)
        entry = self._devices.get(key)

        if entry is None:
            entry = {
                'uuid': derive_uuid(device),
                'friendlyName': friendly_name or (device.get('name') or ''),
                'name': device.get('name') or '',
                'deviceType': device.get('deviceType') or '',
                'deviceFamily': device.get('deviceFamily') or '',
                'serialNumber': device.get('serialNumber') or '',
                'deviceOwnerCustomerId': device.get('deviceOwnerCustomerId') or '',
            }
            self._devices[key] = entry
        else:
            entry['name'] = device.get('name') or entry.get('name', '')
            entry['deviceType'] = device.get('deviceType') or entry.get('deviceType', '')
            entry['deviceFamily'] = device.get('deviceFamily') or entry.get('deviceFamily', '')
            entry['serialNumber'] = device.get('serialNumber') or entry.get('serialNumber', '')
            entry['deviceOwnerCustomerId'] = device.get('deviceOwnerCustomerId') or entry.get('deviceOwnerCustomerId', '')
            if friendly_name:
                entry['friendlyName'] = friendly_name

        return entry

    def entries(self) -> list:
        """Return all known registry entries."""

        if not self._loaded:
            self.load()

        return list(self._devices.values())

    def get(self, device: dict) -> dict:
        """Return the registry entry of a device without creating it."""

        if not self._loaded:
            self.load()

        return self._devices.get(device_identity_key(device))
