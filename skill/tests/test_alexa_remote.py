import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from castnavidrome.alexa_remote import (
    AlexaRemoteError,
    AlexaTextCommandClient,
    MAX_TEXT_COMMAND_LENGTH,
    build_control_text,
    build_play_track_text,
    find_devices_by_name,
)


class AlexaTextCommandClientTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        cookie_file = Path(self.temp_dir.name) / 'cookies.data'
        cookie_file.write_text('csrf=test-csrf\nsession-id=test-session\n', encoding='utf-8')
        self.opener = MagicMock()
        self.client = AlexaTextCommandClient(str(cookie_file), opener=self.opener)

    def mock_response(self, body=b''):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = body
        self.opener.open.return_value = response
        return response

    def mock_responses(self, bodies):
        """Mock sequential responses for consecutive opener.open() calls."""
        responses = []
        for body in bodies:
            response = MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = body
            responses.append(response)
        self.opener.open.side_effect = responses
        return responses

    def test_list_devices_returns_only_fields_needed_for_targeting(self):
        self.mock_responses([
            json.dumps({'alexaApiUrl': 'https://api.amazon.com'}).encode('utf-8'),
            json.dumps({
                'devices': [{
                    'accountName': 'Kitchen Echo',
                    'deviceOwnerCustomerId': 'customer-1',
                    'deviceType': 'device-type-1',
                    'deviceFamily': 'ECHO',
                    'serialNumber': 'serial-1',
                    'online': True,
                    'otherPrivateField': 'discarded',
                }],
            }).encode('utf-8'),
        ])

        devices = self.client.list_devices()

        self.assertEqual(devices, [{
            'name': 'Kitchen Echo',
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'deviceFamily': 'ECHO',
            'serialNumber': 'serial-1',
            'online': True,
        }])
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.amazon.com/api/devices-v2/device?cached=false')
        self.assertIn('csrf=test-csrf', request.headers['Cookie'])

    def test_find_devices_by_name_matches_case_insensitively(self):
        devices = [
            {'name': 'Kitchen Echo', 'serialNumber': 'serial-1'},
            {'name': 'Bedroom Echo', 'serialNumber': 'serial-2'},
        ]

        matches = find_devices_by_name(devices, ' kitchen echo ')

        self.assertEqual(matches, [devices[0]])

    def test_find_devices_by_name_returns_duplicate_matches(self):
        devices = [
            {'name': 'Echo', 'serialNumber': 'serial-1'},
            {'name': 'echo', 'serialNumber': 'serial-2'},
        ]

        self.assertEqual(find_devices_by_name(devices, 'Echo'), devices)

    def test_build_control_text_maps_playback_and_volume_commands(self):
        self.assertEqual(build_control_text('pause', 'zero mukke'), 'ask zero mukke to pause')
        self.assertEqual(build_control_text('next', 'zero mukke'), 'ask zero mukke to skip to the next song')
        self.assertEqual(build_control_text('volume_up', 'zero mukke'), 'volume up')
        self.assertEqual(build_control_text('set_volume', 'zero mukke', 6), 'set volume to 6')

    def test_build_control_text_uses_german_locale(self):
        self.assertEqual(build_control_text('pause', 'zero mukke', locale='de-DE'), 'frage zero mukke, pausiere')
        self.assertEqual(build_control_text('resume', 'zero mukke', locale='de-DE'), 'frage zero mukke, spiele weiter')
        self.assertEqual(build_control_text('volume_up', 'zero mukke', locale='de-DE'), 'lauter')
        self.assertEqual(build_control_text('set_volume', 'zero mukke', 6, 'de-DE'), 'setze die Lautstärke auf 6')

    def test_build_control_text_rejects_invalid_volume_and_command(self):
        with self.assertRaisesRegex(ValueError, 'between 0 and 10'):
            build_control_text('set_volume', 'zero mukke', 11)
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            build_control_text('arbitrary text', 'zero mukke')

    def test_the_play_track_text_is_announced(self):
        self.assertEqual(build_play_track_text('zero mukke', 'Himmel', 'Falke', locale='de-DE'),
                         'frage zero mukke, spiele das Lied Himmel von Falke')

    def test_the_quiet_play_track_text_is_not_announced(self):
        self.assertEqual(build_play_track_text('zero mukke', 'Himmel', 'Falke', locale='de-DE', quiet=True),
                         'frage zero mukke, spiele das Lied Himmel von Falke leise')

    def test_the_play_track_text_preserves_special_characters(self):
        self.assertEqual(
            build_play_track_text('zero mukke', 'Mötley Crüe - Dr. Feelgood & Co.', 'Mötley Crüe', locale='de-DE'),
            'frage zero mukke, spiele das Lied Mötley Crüe - Dr. Feelgood & Co. von Mötley Crüe',
        )

    def test_the_play_track_text_preserves_a_long_title(self):
        long_title = 'A' * 150
        self.assertEqual(
            build_play_track_text('zero mukke', long_title, 'Falke', locale='de-DE'),
            'frage zero mukke, spiele das Lied ' + long_title + ' von Falke',
        )

    def test_the_play_track_text_preserves_a_title_with_parentheses(self):
        self.assertEqual(
            build_play_track_text('zero mukke', 'Song (Live) (Remastered)', 'Falke', locale='de-DE'),
            'frage zero mukke, spiele das Lied Song von Falke',
        )

    def test_the_play_track_text_strips_parenthetical_additions(self):
        self.assertEqual(
            build_play_track_text('zero mukke', 'Holiday (live at Makuhari Messe, Tokyo, Japan, 13/07/05)', 'Greenday', locale='de-DE'),
            'frage zero mukke, spiele das Lied Holiday von Greenday',
        )

    def test_the_play_track_text_preserves_a_title_without_parentheses(self):
        self.assertEqual(
            build_play_track_text('zero mukke', 'Himmel', 'Falke', locale='de-DE'),
            'frage zero mukke, spiele das Lied Himmel von Falke',
        )

    def test_the_play_track_text_is_truncated_when_it_is_too_long(self):
        long_title = 'Langer Titel ' * 50
        text = build_play_track_text('zero mukke', long_title, 'Falke', locale='de-DE')

        self.assertLessEqual(len(text), MAX_TEXT_COMMAND_LENGTH)
        self.assertTrue(text.endswith(' von Falke'))
        self.assertNotIn(long_title, text)

    def test_the_play_track_text_is_truncated_in_english(self):
        long_title = 'A' * 300
        text = build_play_track_text('zero mukke', long_title, 'Falke')

        self.assertLessEqual(len(text), MAX_TEXT_COMMAND_LENGTH)
        self.assertTrue(text.endswith(' by Falke'))
        self.assertNotIn(long_title, text)

    def test_the_artist_is_truncated_only_when_the_title_is_gone(self):
        long_title = 'A' * 300
        long_artist = 'B' * 300
        text = build_play_track_text('zero mukke', long_title, long_artist, locale='de-DE')

        self.assertEqual(len(text), MAX_TEXT_COMMAND_LENGTH)
        self.assertEqual(text, 'frage zero mukke, spiele das Lied  von ' + 'B' * 201)

    def test_send_play_command_targets_device_and_uses_skill_phrase(self):
        self.mock_response()
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        self.client.send_play_command(device, 'castnavidrome')

        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://alexa.amazon.com/api/behaviors/preview')
        command = json.loads(request.data)
        sequence = json.loads(command['sequenceJson'])
        self.assertEqual(command['behaviorId'], 'PREVIEW')
        self.assertEqual(sequence['startNode']['type'], 'Alexa.TextCommand')
        self.assertEqual(sequence['startNode']['operationPayload']['text'], 'ask castnavidrome to play random music')
        self.assertEqual(sequence['startNode']['operationPayload']['deviceSerialNumber'], 'serial-1')

    def test_send_play_command_can_target_a_playlist(self):
        self.mock_response()
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        self.client.send_play_command(device, 'navi sonic', playlist_name='Morning Mix')

        request = self.opener.open.call_args.args[0]
        command = json.loads(request.data)
        sequence = json.loads(command['sequenceJson'])
        self.assertEqual(
            sequence['startNode']['operationPayload']['text'],
            'ask navi sonic to play playlist Morning Mix',
        )

    def test_send_play_command_uses_german_locale(self):
        self.mock_response()
        device = {'deviceOwnerCustomerId': 'customer-1', 'deviceType': 'device-type-1', 'serialNumber': 'serial-1'}

        self.client.send_play_command(device, 'zero mukke', locale='de-DE', playlist_name='reinhören')

        request = self.opener.open.call_args.args[0]
        command = json.loads(request.data)
        sequence = json.loads(command['sequenceJson'])
        payload = sequence['startNode']['operationPayload']
        self.assertEqual(payload['locale'], 'de-DE')
        self.assertEqual(payload['text'], 'frage zero mukke, spiele die Playlist reinhören')

    def test_send_text_command_targets_selected_device(self):
        self.mock_response()
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        self.client.send_text_command(device, 'ask zero mukke to pause')

        request = self.opener.open.call_args.args[0]
        command = json.loads(request.data)
        sequence = json.loads(command['sequenceJson'])
        operation = sequence['startNode']['operationPayload']
        self.assertEqual(operation['text'], 'ask zero mukke to pause')
        self.assertEqual(operation['deviceSerialNumber'], 'serial-1')

    def test_send_text_command_sends_the_locale_of_the_command(self):
        self.mock_response()
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        self.client.send_text_command(device, 'frage zero mukke, pausiere', locale='de-DE')

        request = self.opener.open.call_args.args[0]
        command = json.loads(request.data)
        sequence = json.loads(command['sequenceJson'])
        operation = sequence['startNode']['operationPayload']
        self.assertEqual(operation['locale'], 'de-DE')
        self.assertEqual(request.headers['Accept-language'], 'de-DE')

    def test_send_text_command_normalises_an_unsupported_locale(self):
        self.mock_response()
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        self.client.send_text_command(device, 'ask zero mukke to pause', locale='de-AT')

        request = self.opener.open.call_args.args[0]
        command = json.loads(request.data)
        sequence = json.loads(command['sequenceJson'])
        self.assertEqual(sequence['startNode']['operationPayload']['locale'], 'de-DE')

    def test_get_device_volume_reads_the_volume_from_the_alexa_device(self):
        self.mock_responses([
            json.dumps({'alexaApiUrl': 'https://alexa.amazon.com'}).encode('utf-8'),
            b'',
            json.dumps({'volume': 6}).encode('utf-8'),
        ])
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        volume = self.client.get_device_volume(device)

        self.assertEqual(volume, 6)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(
            request.full_url,
            'https://alexa.amazon.com/api/device-volume?deviceSerialNumber=serial-1&deviceType=device-type-1',
        )

    def test_get_device_volume_reads_from_all_device_volumes(self):
        self.mock_responses([
            json.dumps({'alexaApiUrl': 'https://alexa.amazon.com'}).encode('utf-8'),
            json.dumps([
                {'deviceSerialNumber': 'serial-1', 'deviceType': 'device-type-1', 'volume': 4},
                {'deviceSerialNumber': 'serial-2', 'deviceType': 'device-type-2', 'volume': 7},
            ]).encode('utf-8'),
        ])
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        volume = self.client.get_device_volume(device)

        self.assertEqual(volume, 4)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(
            request.full_url,
            'https://alexa.amazon.com/api/devices/deviceType/dsn/audio/v1/allDeviceVolumes',
        )

    def test_get_device_volume_clamps_the_volume_to_the_alexa_range(self):
        self.mock_responses([
            json.dumps({'alexaApiUrl': 'https://alexa.amazon.com'}).encode('utf-8'),
            b'',
            json.dumps({'volume': 12}).encode('utf-8'),
            b'',
            json.dumps({'volume': -3}).encode('utf-8'),
        ])
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        self.assertEqual(self.client.get_device_volume(device), 10)
        self.assertEqual(self.client.get_device_volume(device), 0)

    def test_get_device_volume_returns_none_on_no_session(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.cookies', delete=False)
        tmp.write(b'csrf=test-csrf\nsession-id=test-session\n')
        tmp.close()
        client = AlexaTextCommandClient(tmp.name, domain='amazon.com')
        device = {'serialNumber': 'serial-1'}
        self.assertIsNone(client.get_device_volume(device))
        Path(tmp.name).unlink(missing_ok=True)

    def test_get_device_volume_returns_none_on_html_response(self):
        self.mock_responses([
            json.dumps({'alexaApiUrl': 'https://alexa.amazon.com'}).encode('utf-8'),
            b'',
            b'<!DOCTYPE html><html><body>Please log in</body></html>',
        ])
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        volume = self.client.get_device_volume(device)

        self.assertIsNone(volume)

    def test_get_device_volume_falls_back_to_single_endpoint(self):
        # First call: /api/endpoints, then allDeviceVolumes returns HTML -> fall back to device-volume
        self.opener.open.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=json.dumps({'alexaApiUrl': 'https://alexa.amazon.com'}).encode('utf-8'))))),
            MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b'<html>')))),
            MagicMock(__enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=json.dumps({'volume': 5}).encode('utf-8'))))),
        ]
        device = {
            'deviceOwnerCustomerId': 'customer-1',
            'deviceType': 'device-type-1',
            'serialNumber': 'serial-1',
        }

        volume = self.client.get_device_volume(device)

        self.assertEqual(volume, 5)
        self.assertEqual(self.opener.open.call_count, 3)

    def test_cookie_file_requires_csrf_cookie(self):
        cookie_file = Path(self.temp_dir.name) / 'missing-csrf.data'
        cookie_file.write_text('session-id=test-session\n', encoding='utf-8')

        with self.assertRaisesRegex(AlexaRemoteError, 'csrf cookie'):
            AlexaTextCommandClient(str(cookie_file))

    def test_http_error_preserves_status_code(self):
        self.opener.open.side_effect = __import__('urllib.error').error.HTTPError(
            'https://api.amazon.com/api/behaviors/preview', 429, 'Too Many Requests', {}, None
        )

        with self.assertRaises(AlexaRemoteError) as context:
            self.client.send_text_command(
                {'deviceOwnerCustomerId': 'customer-1', 'deviceType': 'device-type-1', 'serialNumber': 'serial-1'},
                'ask zero mukke to pause',
            )

        self.assertEqual(context.exception.status_code, 429)


if __name__ == '__main__':
    unittest.main()
