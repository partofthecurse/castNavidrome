import re
import unittest

from castnavidrome.alexa_remote import build_control_text, build_play_track_text
from castnavidrome.localization import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    Translator,
    alexa_command,
    command_keys,
    get_request_locale,
    get_translator,
    message_keys,
    normalize_locale,
)
from castnavidrome.utils import sanitise_speech_output


class FakeRequest:
    def __init__(self, locale=None, slots=None):
        self.locale = locale
        self.intent = type('Intent', (), {'slots': slots or {}})()


class FakeEnvelope:
    def __init__(self, locale=None, slots=None):
        self.request = FakeRequest(locale, slots)


class FakeHandlerInput:
    def __init__(self, locale=None, slots=None):
        self.request_envelope = FakeEnvelope(locale, slots)


class NormalizeLocaleTests(unittest.TestCase):
    def test_a_supported_locale_is_kept(self):
        self.assertEqual(normalize_locale('de-DE'), 'de-DE')
        self.assertEqual(normalize_locale('en-US'), 'en-US')

    def test_the_case_and_the_separator_do_not_matter(self):
        self.assertEqual(normalize_locale('DE-de'), 'de-DE')
        self.assertEqual(normalize_locale('de_de'), 'de-DE')

    def test_a_language_only_locale_maps_to_its_locale(self):
        self.assertEqual(normalize_locale('de'), 'de-DE')
        self.assertEqual(normalize_locale('en'), 'en-US')

    def test_a_regional_variant_maps_to_the_language(self):
        self.assertEqual(normalize_locale('de-AT'), 'de-DE')
        self.assertEqual(normalize_locale('en-GB'), 'en-US')

    def test_an_unsupported_locale_falls_back_to_the_default(self):
        self.assertEqual(normalize_locale('nl-NL'), DEFAULT_LOCALE)
        self.assertEqual(normalize_locale('kl-GL'), DEFAULT_LOCALE)

    def test_a_missing_locale_falls_back_to_the_default(self):
        self.assertEqual(normalize_locale(None), DEFAULT_LOCALE)
        self.assertEqual(normalize_locale(''), DEFAULT_LOCALE)
        self.assertEqual(normalize_locale('   '), DEFAULT_LOCALE)


class TranslatorTests(unittest.TestCase):
    def test_the_message_is_translated(self):
        self.assertEqual(Translator('de-DE').t('ready'), 'Bereit!')
        self.assertEqual(Translator('en-US').t('ready'), 'Ready!')

    def test_the_placeholders_are_replaced(self):
        text = Translator('de-DE').t('artist_not_found', artist='Pink Floyd')

        self.assertEqual(text, 'Ich konnte den Interpreten Pink Floyd nicht in der Sammlung finden.')

    def test_an_unknown_placeholder_is_kept(self):
        text = Translator('en-US').t('artist_not_found')

        self.assertEqual(text, "I couldn't find the artist {artist} in the collection.")

    def test_an_unknown_message_raises_an_error(self):
        with self.assertRaisesRegex(KeyError, 'Unknown message'):
            Translator('en-US').t('there_is_no_such_message')

    def test_every_message_is_translated_into_every_locale(self):
        for key in message_keys():
            for locale in SUPPORTED_LOCALES:
                text = Translator(locale).t(key)

                self.assertTrue(text.strip(), f'The message "{key}" is empty in {locale}')

    def test_the_conjunctions_are_translated(self):
        self.assertEqual(Translator('de-DE').conjunction('and'), 'und')
        self.assertEqual(Translator('de-DE').conjunction('or'), 'oder')
        self.assertEqual(Translator('en-US').conjunction('and'), 'and')
        self.assertEqual(Translator('en-US').conjunction('or'), 'or')


class RequestLocaleTests(unittest.TestCase):
    def test_the_locale_of_the_request_is_used(self):
        handler_input = FakeHandlerInput('de-DE')

        self.assertEqual(get_request_locale(handler_input), 'de-DE')

    def test_a_request_without_a_locale_uses_the_fallback(self):
        handler_input = FakeHandlerInput()

        self.assertEqual(get_request_locale(handler_input, 'en-US'), 'en-US')

    def test_the_translator_of_a_request_follows_its_locale(self):
        handler_input = FakeHandlerInput('de-DE')

        self.assertEqual(get_translator(handler_input).t('ready'), 'Bereit!')


class SanitiseSpeechOutputTests(unittest.TestCase):
    def test_the_conjunction_of_the_locale_is_used(self):
        self.assertEqual(sanitise_speech_output('AC/DC & BC', 'en-US'), 'AC and DC and BC')
        self.assertEqual(sanitise_speech_output('AC/DC & BC', 'de-DE'), 'AC und DC und BC')

    def test_the_default_locale_is_english(self):
        self.assertEqual(sanitise_speech_output('AC/DC'), 'AC and DC')

    def test_the_reserved_characters_are_removed(self):
        self.assertEqual(sanitise_speech_output('a "b" \'c\' <d>'), 'a b c d')


class AlexaCommandTests(unittest.TestCase):
    def test_the_command_follows_the_locale(self):
        self.assertEqual(alexa_command('pause', 'de-DE', skill_name='zero mukke'),
                         'frage zero mukke, pausiere')
        self.assertEqual(alexa_command('pause', 'en-US', skill_name='zero mukke'),
                         'ask zero mukke to pause')

    def test_an_unsupported_locale_falls_back_to_the_default(self):
        self.assertEqual(alexa_command('pause', 'nl-NL', skill_name='zero mukke'),
                         'ask zero mukke to pause')

    def test_an_unknown_command_raises_an_error(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            alexa_command('there_is_no_such_command', 'de-DE')

    def test_the_track_command_follows_the_locale(self):
        self.assertEqual(build_play_track_text('zero mukke', 'Himmel', 'Falke', locale='de-DE'),
                         'frage zero mukke, spiele das Lied Himmel von Falke')
        self.assertEqual(build_play_track_text('zero mukke', 'Himmel', 'Falke', locale='en-US'),
                         'ask zero mukke to play the song Himmel by Falke')

    def test_the_quiet_track_command_follows_the_locale(self):
        self.assertEqual(build_play_track_text('zero mukke', 'Himmel', 'Falke', locale='de-DE', quiet=True),
                         'frage zero mukke, spiele das Lied Himmel von Falke leise')
        self.assertEqual(build_play_track_text('zero mukke', 'Himmel', 'Falke', locale='en-US', quiet=True),
                         'ask zero mukke to play the song Himmel by Falke quietly')


class TranslatedLocaleTests(unittest.TestCase):
    def test_the_new_locales_are_supported(self):
        for locale in ('es-ES', 'fr-FR', 'it-IT', 'pt-BR'):
            self.assertEqual(normalize_locale(locale), locale)
            self.assertEqual(normalize_locale(locale.split('-')[0]), locale)

    def test_the_skill_answers_in_the_language_of_the_request(self):
        self.assertEqual(Translator('es-ES').t('ready'), '¡Listo!')
        self.assertEqual(Translator('fr-FR').t('ready'), 'Prêt !')
        self.assertEqual(Translator('it-IT').t('ready'), 'Pronto!')
        self.assertEqual(Translator('pt-BR').t('ready'), 'Pronto!')

    def test_every_command_is_translated_into_every_locale(self):
        for key in command_keys():
            for locale in SUPPORTED_LOCALES:
                text = alexa_command(key, locale, skill_name='zero mukke', title='Himmel',
                                     artist='Falke', playlist_name='Rock', volume=6)

                self.assertTrue(text.strip(), f'The command "{key}" is empty in {locale}')

    def test_the_placeholders_are_the_same_in_every_locale(self):
        for key in message_keys():
            placeholders = set(re.findall(r'{(\w+)}', Translator('en-US').template(key)))

            for locale in SUPPORTED_LOCALES:
                self.assertEqual(set(re.findall(r'{(\w+)}', Translator(locale).template(key))), placeholders,
                                 f'The placeholders of the message "{key}" differ in {locale}')

    def test_the_conjunctions_are_translated_into_the_new_locales(self):
        self.assertEqual(Translator('es-ES').conjunction('and'), 'y')
        self.assertEqual(Translator('fr-FR').conjunction('and'), 'et')
        self.assertEqual(Translator('it-IT').conjunction('and'), 'e')
        self.assertEqual(Translator('pt-BR').conjunction('and'), 'e')


if __name__ == '__main__':
    unittest.main()
