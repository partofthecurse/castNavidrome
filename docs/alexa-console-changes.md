# Alexa Developer Console - manuelle Nachzüge

Die Interaction Models liegen je Sprache als einzelne Datei im Verzeichnis `alexa/`.
Die Datei einer Sprache wird unverändert in den JSON-Editor des Consoles kopiert.

Nachzüge im Console gelten für **alle** Sprachen, die in `alexa/` liegen.

Neue Intents (11) in `alexa/`:
- castNavidromeShufflePlaylist
- castNavidromePlaySong
- castNavidromePlayMusicByDecade
- castNavidromeListPlaylists
- castNavidromeHearMorePlaylists
- castNavidromeFindPlaylist
- castNavidromeHelpTopic
- castNavidromePlaySearch
- castNavidromePlayRadio

Neue Slot-Typen (3):
- decade
- help_topic
- radio_station

Diese Änderungen müssen im Alexa Developer Console nachgezogen werden,
sonst werden die Intents nie ausgelöst.

## Stille Wiedergabe der Media Renderer

Neuer Intent (1):
- castNavidromePlaySongByArtistQuiet

Samples (de-DE):
- "spiele das Lied {song} von {artist} leise"
- "spiele den Song {song} von {artist} leise"

Samples (en-US):
- "play the song {song} by {artist} quietly"
- "play the track {song} by {artist} quietly"

Der Intent wird von den Media Renderern benutzt, um den nächsten Titel
einer Playlist ohne Ansage zu starten.  Ohne den Intent im Console
versteht das Echo den Befehl nicht und die Playlist endet nach dem
ersten Titel.  Wer das Verhalten nicht braucht, setzt
`NAVI_ALEXA_RENDERER_ANNOUNCE=always` oder `never`.

## Zweite Sprache (Englisch)

`alexa/en-US.json` enthält das englische Interaction Model.
Das deutsche Model in `alexa/de-DE.json` bleibt das Standard-Model.

Im Alexa Developer Console:

1. *Interaction Model* → *Add Language* → *English (United States)*.
2. Im JSON-Editor das englische Model aus `alexa/en-US.json`
   einfügen und *Save Model* klicken.
3. Der Invocation Name bleibt "zero mukke", damit die Sprachbefehle der
   Media Renderer mit `NAVI_ALEXA_SKILL_NAME` zusammenpassen.
4. In *Custom* → *Locale* die Sprache *German (Germany)* als Primary
   Locale behalten, damit die deutsche Variante aktiv bleibt.

Ohne das englische Model versteht ein Echo, das auf Englisch steht, den
Skill nicht. Die Sprache des Echos muss zur Sprache der gesprochenen
Befehle passen, das ist `NAVI_ALEXA_LOCALE`.

## Weitere Sprachen (Spanisch, Französisch, Italienisch, Portugiesisch)

Es gibt zusätzlich vier Interaction Models:

- `alexa/es-ES.json` (Spanisch)
- `alexa/fr-FR.json` (Französisch)
- `alexa/it-IT.json` (Italienisch)
- `alexa/pt-BR.json` (Brasilianisches Portugiesisch)

Im Alexa Developer Console für jede Sprache:

1. *Interaction Model* → *Add Language* → die Sprache wählen
   (Spanish (Spain), French (France), Italian (Italy),
   Portuguese (Brazil)).
2. Im JSON-Editor das passende Model aus dem Verzeichnis `alexa/` einfügen
   und *Save Model* klicken.
3. Der Invocation Name bleibt "zero mukke", damit die Sprachbefehle der
   Media Renderer mit `NAVI_ALEXA_SKILL_NAME` zusammenpassen.

Ohne das Model versteht ein Echo, das auf der Sprache steht, den Skill
nicht.  Die Sprache des Echos muss zur Sprache der gesprochenen Befehle
passen, das ist `NAVI_ALEXA_LOCALE`.  Die Antworten des Skills richten
sich nach der Sprache der Anfrage, die auch in einer anderen Sprache
sein darf.

Die Werte des Slot-Typs `help_topic` sind pro Sprache übersetzt.  Sie
stehen in `HELP_TOPIC_ALIASES` der `skill/app.py`, damit der Skill das
richtige Hilfethema findet.
