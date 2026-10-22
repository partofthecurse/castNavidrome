import json
import tempfile
import unittest
from pathlib import Path

from castnavidrome.renderer_registry import RendererRegistry, derive_uuid, device_identity_key


def make_device(name='Echo Dot', serial='serial-1', customer='customer-1'):
    return {
        'name': name,
        'deviceOwnerCustomerId': customer,
        'deviceType': 'ECHO',
        'serialNumber': serial,
        'online': True,
    }


class RendererRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_file = str(Path(self.temp_dir.name) / 'renderers.json')

    def test_the_identity_key_is_built_from_the_owner_and_the_serial_number(self):
        self.assertEqual(device_identity_key(make_device()), 'customer-1:serial-1')

    def test_the_identity_key_falls_back_to_the_name(self):
        self.assertEqual(device_identity_key(make_device(serial='')), 'customer-1:name:echo dot')

    def test_the_uuid_is_deterministic(self):
        self.assertEqual(derive_uuid(make_device()), derive_uuid(make_device()))

    def test_different_devices_get_different_uuids(self):
        self.assertNotEqual(derive_uuid(make_device(serial='serial-1')),
                            derive_uuid(make_device(serial='serial-2')))

    def test_a_registered_device_keeps_its_uuid_after_a_restart(self):
        registry = RendererRegistry(self.state_file)
        entry = registry.register(make_device(), 'castNavidrome: Echo Dot')
        registry.save()

        reloaded = RendererRegistry(self.state_file)
        reloaded.load()
        entry_after_restart = reloaded.register(make_device(), 'castNavidrome: Echo Dot')

        self.assertEqual(entry['uuid'], entry_after_restart['uuid'])

    def test_a_renamed_device_keeps_its_uuid(self):
        registry = RendererRegistry(self.state_file)
        entry = registry.register(make_device(name='Echo Dot'), 'castNavidrome: Echo Dot')
        registry.save()

        reloaded = RendererRegistry(self.state_file)
        reloaded.load()
        entry_after_rename = reloaded.register(make_device(name='Echo Dot Wohnzimmer'), 'castNavidrome: Echo Dot Wohnzimmer')

        self.assertEqual(entry['uuid'], entry_after_rename['uuid'])
        self.assertEqual(entry_after_rename['name'], 'Echo Dot Wohnzimmer')

    def test_the_registry_is_stored_as_json(self):
        registry = RendererRegistry(self.state_file)
        registry.register(make_device(), 'castNavidrome: Echo Dot')
        registry.save()

        with open(self.state_file, 'r', encoding='utf-8') as registry_file:
            data = json.load(registry_file)

        self.assertEqual(data['version'], 1)
        self.assertEqual(len(data['devices']), 1)

    def test_a_broken_registry_does_not_stop_the_renderer(self):
        Path(self.state_file).write_text('not json', encoding='utf-8')

        registry = RendererRegistry(self.state_file)
        registry.load()

        self.assertEqual(registry.entries(), [])
        self.assertTrue(registry.register(make_device(), 'castNavidrome: Echo Dot'))
