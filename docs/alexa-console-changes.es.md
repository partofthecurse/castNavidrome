# Alexa Developer Console - adiciones manuales

Los modelos de interacción se almacenan por idioma como archivos individuales en el directorio `alexa/`.
El archivo de un idioma se copia sin cambios en el editor JSON de la consola.

Las adiciones en la consola aplican a **todos** los idiomas presentes en `alexa/`.

Nuevos intents (11) en `alexa/`:
- castNavidromeShufflePlaylist
- castNavidromePlaySong
- castNavidromePlayMusicByDecade
- castNavidromeListPlaylists
- castNavidromeHearMorePlaylists
- castNavidromeFindPlaylist
- castNavidromeHelpTopic
- castNavidromePlaySearch
- castNavidromePlayRadio

Nuevos tipos de slot (3):
- decade
- help_topic
- radio_station

Estos cambios deben aplicarse en la Alexa Developer Console, de lo contrario los intents nunca se activan.

## Reproducción silenciosa de los media renderers

Nuevo intent (1):
- castNavidromePlaySongByArtistQuiet

Muestras (de-DE):
- "spiele das Lied {song} von {artist} leise"
- "spiele den Song {song} von {artist} leise"

Muestras (en-US):
- "play the song {song} by {artist} quietly"
- "play the track {song} by {artist} quietly"

El intent lo usan los media renderers para iniciar la siguiente pista de una lista de reproducción sin anuncio. Sin el intent en la consola, el Echo no entiende el comando y la lista termina tras la primera pista. Si no necesitas este comportamiento, establece `NAVI_ALEXA_RENDERER_ANNOUNCE=always` o `never`.

## Segundo idioma (inglés)

`alexa/en-US.json` contiene el modelo de interacción en inglés.
El modelo alemán en `alexa/de-DE.json` sigue siendo el modelo por defecto.

En la Alexa Developer Console:

1. *Interaction Model* → *Add Language* → *English (United States)*.
2. En el editor JSON, pega el modelo inglés de `alexa/en-US.json` y haz clic en *Save Model*.
3. El nombre de invocación sigue siendo "zero mukke", para que los comandos de voz de los media renderers coincidan con `NAVI_ALEXA_SKILL_NAME`.
4. En *Custom* → *Locale*, mantén *German (Germany)* como Primary Locale para que la variante alemana siga activa.

Sin el modelo inglés, un Echo configurado en inglés no entiende la skill. El idioma del Echo debe coincidir con el idioma de los comandos hablados, que es `NAVI_ALEXA_LOCALE`.

## Más idiomas (español, francés, italiano, portugués)

Hay cuatro modelos de interacción adicionales:

- `alexa/es-ES.json` (español)
- `alexa/fr-FR.json` (francés)
- `alexa/it-IT.json` (italiano)
- `alexa/pt-BR.json` (portugués brasileño)

En la Alexa Developer Console para cada idioma:

1. *Interaction Model* → *Add Language* → elige el idioma (Spanish (Spain), French (France), Italian (Italy), Portuguese (Brazil)).
2. En el editor JSON, pega el modelo correspondiente del directorio `alexa/` y haz clic en *Save Model*.
3. El nombre de invocación sigue siendo "zero mukke", para que los comandos de voz de los media renderers coincidan con `NAVI_ALEXA_SKILL_NAME`.

Sin el modelo, un Echo configurado en ese idioma no entiende la skill. El idioma del Echo debe coincidir con el idioma de los comandos hablados, que es `NAVI_ALEXA_LOCALE`. Las respuestas de la skill siguen el idioma de la solicitud, que puede ser otro idioma.

Los valores del tipo de slot `help_topic` se traducen por idioma. Están definidos en `HELP_TOPIC_ALIASES` de `skill/app.py`, para que la skill encuentre el tema de ayuda correcto.
