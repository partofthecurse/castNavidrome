import unittest

from castnavidrome.alexa_device_filter import DeviceFilter


def make_device(name='Echo Dot', device_family='ECHO', device_type='A2U21SRK4QGSE1', online=True):
    return {
        'name': name,
        'deviceOwnerCustomerId': 'customer-1',
        'deviceType': device_type,
        'deviceFamily': device_family,
        'serialNumber': 'serial-1',
        'online': online,
    }


class DeviceFilterTests(unittest.TestCase):
    def test_echo_devices_are_selected_by_default(self):
        device_filter = DeviceFilter.from_env({})

        self.assertTrue(device_filter.matches(make_device()))

    def test_tablets_and_ereaders_are_excluded_by_default(self):
        device_filter = DeviceFilter.from_env({})

        self.assertFalse(device_filter.matches(make_device('Fire Tablet', 'TABLET', 'A1Q7QCGNMXAKYW')))
        self.assertFalse(device_filter.matches(make_device('Kindle', 'E_READER', 'A1A2B3C4D5E6')))
        self.assertFalse(device_filter.matches(make_device('E-Reader', 'KINDLE', 'A1A2B3C4D5E7')))

    def test_fire_tv_devices_are_selected_by_default(self):
        device_filter = DeviceFilter.from_env({})

        self.assertTrue(device_filter.matches(make_device('Fire TV', 'FIRE_TV', 'A2JKHJ0PX4J3L3')))

    def test_a_device_type_whitelist_limits_the_selection(self):
        device_filter = DeviceFilter.from_env({'NAVI_ALEXA_RENDERER_DEVICE_TYPES': 'ECHO'})

        self.assertTrue(device_filter.matches(make_device('Echo', 'ECHO')))
        self.assertTrue(device_filter.matches(make_device('Echo Show', 'ECHO')))
        self.assertFalse(device_filter.matches(make_device('Fire TV', 'FIRE_TV', 'A2JKHJ0PX4J3L3')))
        self.assertFalse(device_filter.matches(make_device('Fire Tablet', 'TABLET', 'A1Q7QCGNMXAKYW')))

    def test_a_single_device_can_be_selected_by_its_device_type_id(self):
        device_filter = DeviceFilter.from_env({'NAVI_ALEXA_RENDERER_DEVICE_TYPES': 'A2U21SRK4QGSE1'})

        self.assertTrue(device_filter.matches(make_device('Echo Dot Wohnzimmer')))
        self.assertFalse(device_filter.matches(make_device('Echo Show', 'ECHO', 'A2TF17PFR55MTB')))

    def test_the_excluded_device_types_can_be_replaced(self):
        device_filter = DeviceFilter.from_env({'NAVI_ALEXA_RENDERER_EXCLUDED_DEVICE_TYPES': 'FIRE_TV'})

        self.assertTrue(device_filter.matches(make_device('Fire Tablet', 'TABLET', 'A1Q7QCGNMXAKYW')))
        self.assertFalse(device_filter.matches(make_device('Fire TV', 'FIRE_TV', 'A2JKHJ0PX4J3L3')))

    def test_name_include_and_exclude_lists(self):
        device_filter = DeviceFilter.from_env({
            'NAVI_ALEXA_RENDERER_NAME_INCLUDE': 'Echo Dot, Kitchen Echo',
            'NAVI_ALEXA_RENDERER_NAME_EXCLUDE': 'Bedroom Echo',
        })

        self.assertTrue(device_filter.matches(make_device('Echo Dot')))
        self.assertTrue(device_filter.matches(make_device('kitchen echo')))
        self.assertFalse(device_filter.matches(make_device('Bedroom Echo')))
        self.assertFalse(device_filter.matches(make_device('Office Echo')))

    def test_name_regex(self):
        device_filter = DeviceFilter.from_env({'NAVI_ALEXA_RENDERER_NAME_REGEX': r'^Echo'})

        self.assertTrue(device_filter.matches(make_device('Echo Dot')))
        self.assertFalse(device_filter.matches(make_device('Kitchen Echo')))

    def test_only_online_devices(self):
        device_filter = DeviceFilter.from_env({'NAVI_ALEXA_RENDERER_ONLY_ONLINE': 'yes'})

        self.assertTrue(device_filter.matches(make_device(online=True)))
        self.assertFalse(device_filter.matches(make_device(online=False)))

    def test_filter_returns_the_matching_devices(self):
        device_filter = DeviceFilter.from_env({'NAVI_ALEXA_RENDERER_DEVICE_TYPES': 'ECHO'})

        devices = [
            make_device('Echo', 'ECHO'),
            make_device('Fire Tablet', 'TABLET', 'A1Q7QCGNMXAKYW'),
            make_device('Fire TV', 'FIRE_TV', 'A2JKHJ0PX4J3L3'),
        ]

        self.assertEqual(device_filter.filter(devices), [devices[0]])
