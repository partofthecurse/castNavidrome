"""Tests for the interaction models of the skill.

The models are not part of the deployment of the skill, they are uploaded
in the Alexa Developer Console, so the tests are skipped when the files are
not there.

Every locale has its own model in the ``alexa`` directory, one file per
locale.
"""

import json
import re
import unittest
from pathlib import Path

from castnavidrome.localization import HELP_TOPIC_ALIASES, SUPPORTED_LOCALES, alexa_command

ROOT = Path(__file__).resolve().parent.parent.parent
ALEXA_DIR = ROOT / 'alexa'

# The intent that is triggered by a voice command and the key of the command
COMMANDS = {
    'castNavidromePlaySongByArtist': 'play_track',
    'castNavidromePlaySongByArtistQuiet': 'play_track_quiet',
    'castNavidromePlayPlaylist': 'play_playlist',
    'castNavidromePlayMusicRandom': 'play_random',
}

# The articles of the supported languages, they are not in every sample
ARTICLES = ('the', 'der', 'die', 'das', 'el', 'la', 'los', 'las', 'il', 'un', 'una',
            'uno', 'os', 'as', 'o', 'a', 'e')

# The values of the radio stations are machine keys, they build the URL of
# the stream and they must be the same in every locale.
MACHINE_VALUES = ('radio_station', 'default', 'pop', 'rock', 'jazz', 'classical', 'chillout')


def locale_models():
    """Get the language model of every locale file in the alexa directory."""

    locales = {}

    for path in sorted(ALEXA_DIR.glob('*.json')):
        with path.open(encoding='utf-8') as file:
            model = json.load(file)

        locales[path.stem] = model['interactionModel']['languageModel']

    return locales


def tokens(text):
    """Get the words of a text without the placeholders and the articles."""

    words = re.findall(r"[\w'À-ɏ]+", re.sub(r'\{\w+\}', ' ', text).lower())

    return [word for word in words if word not in ARTICLES]


@unittest.skipUnless(ALEXA_DIR.is_dir(), 'The interaction models are not part of the deployment.')
class InteractionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = locale_models()

    def test_every_supported_locale_has_a_model(self):
        for locale in SUPPORTED_LOCALES:
            self.assertIn(locale, self.models, f'The locale {locale} has no interaction model')

    def test_every_model_has_the_same_intents(self):
        reference = self.models['de-DE']

        for locale, language_model in self.models.items():
            self.assertEqual([intent['name'] for intent in language_model['intents']],
                             [intent['name'] for intent in reference['intents']],
                             f'The intents of the locale {locale} are different')

    def test_every_model_has_the_same_slots(self):
        reference = self.models['de-DE']

        for locale, language_model in self.models.items():
            for intent, expected in zip(language_model['intents'], reference['intents']):
                self.assertEqual(intent.get('slots', []), expected.get('slots', []),
                                 f'The slots of the intent {intent["name"]} differ in {locale}')

    def test_the_samples_of_an_intent_are_unique(self):
        for locale, language_model in self.models.items():
            for intent in language_model['intents']:
                samples = intent.get('samples', [])

                self.assertEqual(len(samples), len(set(samples)),
                                 f'The intent {intent["name"]} has a duplicate sample in {locale}')

    def test_the_samples_only_use_the_slots_of_the_intent(self):
        for locale, language_model in self.models.items():
            for intent in language_model['intents']:
                slots = {slot['name'] for slot in intent.get('slots', [])}

                for sample in intent.get('samples', []):
                    for placeholder in re.findall(r'{(\w+)}', sample):
                        self.assertIn(placeholder, slots,
                                      f'The sample "{sample}" uses an unknown slot in {locale}')

    def test_every_model_has_the_same_slot_types(self):
        reference = self.models['de-DE']

        for locale, language_model in self.models.items():
            self.assertEqual([slot_type['name'] for slot_type in language_model['types']],
                             [slot_type['name'] for slot_type in reference['types']],
                             f'The slot types of the locale {locale} are different')

    def test_the_values_of_the_radio_stations_are_the_same_in_every_locale(self):
        for locale, language_model in self.models.items():
            stations = next(slot_type for slot_type in language_model['types']
                            if slot_type['name'] == 'radio_station')

            self.assertEqual([value['name']['value'] for value in stations['values']],
                             list(MACHINE_VALUES[1:]),
                             f'The radio stations of the locale {locale} are different')

    def test_the_decades_contain_the_digits_of_the_year(self):
        for locale, language_model in self.models.items():
            decades = next(slot_type for slot_type in language_model['types']
                           if slot_type['name'] == 'decade')

            for value in decades['values']:
                digits = re.findall(r'\d+', value['name']['value'])

                self.assertTrue(digits, f'The decade "{value["name"]["value"]}" of the locale {locale} has no digits')
                self.assertEqual(len(digits[0]), 4,
                                 f'The decade "{value["name"]["value"]}" of the locale {locale} has no year')

    @unittest.skipIf(HELP_TOPIC_ALIASES is None, 'The skill service is not installed.')
    def test_the_help_topics_are_known_by_the_skill(self):
        for locale, language_model in self.models.items():
            topics = next(slot_type for slot_type in language_model['types']
                          if slot_type['name'] == 'help_topic')

            for value in topics['values']:
                self.assertIn(value['name']['value'], HELP_TOPIC_ALIASES,
                              f'The help topic "{value["name"]["value"]}" of the locale {locale} is unknown')

    def test_the_samples_match_the_voice_commands(self):
        """A device matches a voice command against the samples of the model

        The words of a sample have to be in the command that is sent to the
        device, so that the device understands it.  The first word of a
        sample is the verb, it is the only word that may be different, the
        command uses the conjugated form of it.
        """

        for locale, language_model in self.models.items():
            for intent_name, command in COMMANDS.items():
                intent = next(i for i in language_model['intents'] if i['name'] == intent_name)
                text = alexa_command(command, locale, skill_name='zero mukke', title='Himmel',
                                     artist='Falke', playlist_name='Rock')

                words = tokens(text)
                matched = any(tokens(sample)[1:] and set(tokens(sample)[1:]) <= set(words)
                              for sample in intent['samples'])

                self.assertTrue(matched,
                                f'The samples of the intent {intent_name} do not match the command '
                                f'"{text}" in {locale}')


if __name__ == '__main__':
    unittest.main()
