# Alexa Developer Console - manual additions

The interaction models are stored per language as individual files in the `alexa/` directory.
The file for a language is copied unchanged into the JSON editor of the console.

Console additions apply to **all** languages present in `alexa/`.

New intents (11) in `alexa/`:
- castNavidromeShufflePlaylist
- castNavidromePlaySong
- castNavidromePlayMusicByDecade
- castNavidromeListPlaylists
- castNavidromeHearMorePlaylists
- castNavidromeFindPlaylist
- castNavidromeHelpTopic
- castNavidromePlaySearch
- castNavidromePlayRadio

New slot types (3):
- decade
- help_topic
- radio_station

These changes must be applied in the Alexa Developer Console, otherwise the intents are never triggered.

## Silent playback of the media renderers

New intent (1):
- castNavidromePlaySongByArtistQuiet

Samples (de-DE):
- "spiele das Lied {song} von {artist} leise"
- "spiele den Song {song} von {artist} leise"

Samples (en-US):
- "play the song {song} by {artist} quietly"
- "play the track {song} by {artist} quietly"

The intent is used by the media renderers to start the next track of a playlist without an announcement. Without the intent in the console, the Echo does not understand the command and the playlist ends after the first track. If you do not need this behavior, set `NAVI_ALEXA_RENDERER_ANNOUNCE=always` or `never`.

## Second language (English)

`alexa/en-US.json` contains the English interaction model.
The German model in `alexa/de-DE.json` remains the default model.

In the Alexa Developer Console:

1. *Interaction Model* → *Add Language* → *English (United States)*.
2. In the JSON editor, paste the English model from `alexa/en-US.json` and click *Save Model*.
3. The invocation name stays "zero mukke", so the media renderer voice commands match `NAVI_ALEXA_SKILL_NAME`.
4. In *Custom* → *Locale*, keep *German (Germany)* as the Primary Locale so the German variant stays active.

Without the English model, an Echo set to English does not understand the skill. The language of the Echo must match the language of the spoken commands, which is `NAVI_ALEXA_LOCALE`.

## Further languages (Spanish, French, Italian, Portuguese)

Four additional interaction models are available:

- `alexa/es-ES.json` (Spanish)
- `alexa/fr-FR.json` (French)
- `alexa/it-IT.json` (Italian)
- `alexa/pt-BR.json` (Brazilian Portuguese)

In the Alexa Developer Console for each language:

1. *Interaction Model* → *Add Language* → choose the language (Spanish (Spain), French (France), Italian (Italy), Portuguese (Brazil)).
2. In the JSON editor, paste the matching model from the `alexa/` directory and click *Save Model*.
3. The invocation name stays "zero mukke", so the media renderer voice commands match `NAVI_ALEXA_SKILL_NAME`.

Without the model, an Echo set to that language does not understand the skill. The language of the Echo must match the language of the spoken commands, which is `NAVI_ALEXA_LOCALE`. The skill's responses follow the language of the request, which may be a different language.

The values of the slot type `help_topic` are translated per language. They are defined in `HELP_TOPIC_ALIASES` in `skill/app.py`, so the skill finds the correct help topic.
