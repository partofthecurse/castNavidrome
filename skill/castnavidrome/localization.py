"""Localization of the answers of the skill and of the Alexa voice commands.

The skill answers in the language of the request, so that the Alexa device
speaks the same language as the user.  The voice commands that are sent to
an Alexa device use the language of the configured Alexa locale, because an
Alexa device only understands a command in the language that it is set to.

Our own local change, see CREDITS.md.
"""

import logging
import os


logger = logging.getLogger(__name__)

DEFAULT_LOCALE = 'en-US'
SUPPORTED_LOCALES = ('en-US', 'de-DE', 'es-ES', 'fr-FR', 'it-IT', 'pt-BR')

# The name of the skill as it is shown in the Alexa app and as it is spoken
SKILL_DISPLAY_NAME = 'castNavidrome'

# The messages of the skill.  Every message has a text for every supported
# locale, the English text is the fallback for a locale that is not
# supported.
_MESSAGES = {
    'ready': {
        'en-US': 'Ready!',
        'de-DE': 'Bereit!',
        'es-ES': '¡Listo!',
        'fr-FR': 'Prêt !',
        'it-IT': 'Pronto!',
        'pt-BR': 'Pronto!',
    },
    'device_not_supported': {
        'en-US': 'This device is not supported',
        'de-DE': 'Dieses Gerät wird nicht unterstützt',
        'es-ES': 'Este dispositivo no es compatible',
        'fr-FR': "Cet appareil n'est pas pris en charge",
        'it-IT': 'Questo dispositivo non è supportato',
        'pt-BR': 'Este dispositivo não é compatível',
    },
    'help_overview': {
        'en-US': (
            '{skill} lets you interact with media servers that offer a Subsonic compatible A.P.I. '
            'You can play music by an artist, an album, a song, a play list, a genre or a decade, '
            'and you can find your play lists by a mood. You can pause, resume, skip and stop the '
            'playback. Which topic do you want to know more about?'
        ),
        'de-DE': (
            '{skill} erlaubt dir, mit Medien-Servern zu arbeiten, die eine Subsonic kompatible '
            'A.P.I. anbieten. Du kannst Musik nach Interpreten, Album, Titel, Playlist, Genre oder '
            'Jahrzehnt abspielen und Playlists nach Stimmung finden. Du kannst die Wiedergabe '
            'pausieren, fortsetzen, überspringen und stoppen. Über welches Thema möchtest du mehr '
            'erfahren?'
        ),
        'es-ES': (
            '{skill} te permite interactuar con servidores de medios que ofrecen una API compatible '
            'con Subsonic. Puedes reproducir música por artista, álbum, canción, lista de '
            'reproducción, género o década, y buscar tus listas de reproducción por estado de ánimo. '
            'Puedes pausar, reanudar, saltar y detener la reproducción. ¿Sobre qué tema quieres '
            'saber más?'
        ),
        'fr-FR': (
            "{skill} te permet d'interagir avec des serveurs multimédias compatibles avec l'API "
            'Subsonic. Tu peux jouer de la musique par artiste, album, morceau, playlist, genre ou '
            'décennie, et trouver tes playlists selon une ambiance. Tu peux mettre en pause, '
            'reprendre, passer ou arrêter la lecture. De quel sujet veux-tu en savoir plus ?'
        ),
        'it-IT': (
            "{skill} ti permette di interagire con server multimediali che offrono un'API "
            'compatibile con Subsonic. Puoi riprodurre musica di un artista, di un album, di un '
            'brano, di una playlist, di un genere o di un decennio, e puoi trovare le tue playlist '
            "in base all'umore. Puoi mettere in pausa, riprendere, saltare e fermare la "
            'riproduzione. Su quale argomento vuoi saperne di più?'
        ),
        'pt-BR': (
            '{skill} permite que você interaja com servidores de mídia que oferecem uma API '
            'compatível com Subsonic. Você pode tocar música por artista, álbum, música, playlist, '
            'gênero ou década, e pode encontrar suas playlists por clima. Você pode pausar, '
            'continuar, pular e parar a reprodução. Sobre qual assunto você quer saber mais?'
        ),
    },
    'help_topic_playing_music': {
        'en-US': (
            'You can say play music by the artist name, play the album name by the artist name, play '
            'the song name, play the playlist name, play some music of the genre name, play music '
            'from the decade, or play my favourite songs.'
        ),
        'de-DE': (
            'Du kannst sagen spiele Musik von dem Interpreten, spiele das Album von dem Interpreten, '
            'spiele den Titel, spiele die Playlist, spiele Musik des Genres, spiele Musik aus dem '
            'Jahrzehnt oder spiele meine Lieblingstitel.'
        ),
        'es-ES': (
            'Puedes decir reproduce música del artista, reproduce el álbum del artista, reproduce la '
            'canción, reproduce la lista de reproducción, reproduce música del género, reproduce '
            'música de la década o reproduce mis canciones favoritas.'
        ),
        'fr-FR': (
            "Tu peux dire : joue de la musique de l'artiste, joue l'album par l'artiste, joue le "
            'morceau, joue la playlist, joue de la musique du genre, joue de la musique de la '
            'décennie, ou joue mes morceaux favoris.'
        ),
        'it-IT': (
            "Puoi dire riproduci la musica di un artista, riproduci l'album di un artista, riproduci "
            "un brano, riproduci una playlist, riproduci un po' di musica di un genere, riproduci la "
            'musica di un decennio, oppure riproduci i miei brani preferiti.'
        ),
        'pt-BR': (
            'Você pode dizer tocar música pelo nome do artista, tocar o nome do álbum pelo nome do '
            'artista, tocar o nome da música, tocar o nome da playlist, tocar alguma música do nome '
            'do gênero, tocar música da década, ou tocar minhas músicas favoritas.'
        ),
    },
    'help_topic_finding_playlists': {
        'en-US': (
            'You can say what playlists do I have to hear all of your play lists, say hear more to '
            'hear the next ones, or say find me a playlist about a mood to find a play list by its '
            'description.'
        ),
        'de-DE': (
            'Du kannst sagen welche Playlists habe ich, um alle Playlists zu hören, höre mehr, um '
            'die nächsten zu hören, oder finde mir eine Playlist zu einer Stimmung, um eine Playlist '
            'nach ihrer Beschreibung zu finden.'
        ),
        'es-ES': (
            'Puedes decir qué listas de reproducción tengo para escuchar todas tus listas de '
            'reproducción, di escuchar más para escuchar las siguientes, o búscame una lista de '
            'reproducción sobre un estado de ánimo para encontrar una lista de reproducción por su '
            'descripción.'
        ),
        'fr-FR': (
            "Tu peux dire quelles playlists j'ai pour entendre toutes tes playlists, dis « en savoir "
            'plus » pour entendre les suivantes, ou trouve-moi une playlist sur une ambiance pour '
            'trouver une playlist selon sa description.'
        ),
        'it-IT': (
            'Puoi dire quali playlist ho per sentire tutte le tue playlist, senti altre per sentire '
            'le successive, oppure trova una playlist su un umore per trovare una playlist in base '
            'alla sua descrizione.'
        ),
        'pt-BR': (
            'Você pode dizer quais playlists eu tenho para ouvir todas as suas playlists, dizer '
            'ouvir mais para ouvir as próximas, ou dizer encontre uma playlist sobre um clima para '
            'encontrar uma playlist pela descrição dela.'
        ),
    },
    'help_topic_playback_controls': {
        'en-US': (
            'You can say pause or stop to stop the playback, say resume or play to continue it, and '
            'say next or previous to jump to another track.'
        ),
        'de-DE': (
            'Du kannst sagen pausiere oder stoppe, um die Wiedergabe zu stoppen, spiele weiter oder '
            'spiele, um sie fortzusetzen, und nächste oder vorherige, um zu einem anderen Titel zu '
            'springen.'
        ),
        'es-ES': (
            'Puedes decir pausa o detén para detener la reproducción, di continúa o reproduce para '
            'reanudarla, y di siguiente o anterior para saltar a otra canción.'
        ),
        'fr-FR': (
            'Tu peux dire pause ou stop pour arrêter la lecture, dire reprendre ou jouer pour la '
            'continuer, et dire suivant ou précédent pour passer à un autre morceau.'
        ),
        'it-IT': (
            'Puoi dire metti in pausa o ferma per fermare la riproduzione, riprendi o riproduci per '
            'continuarla, e successivo o precedente per passare a un altro brano.'
        ),
        'pt-BR': (
            'Você pode dizer pausar ou parar para parar a reprodução, dizer continuar ou tocar para '
            'retomar a reprodução, e dizer próxima ou anterior para pular para outra música.'
        ),
    },
    'artist_not_found': {
        'en-US': "I couldn't find the artist {artist} in the collection.",
        'de-DE': 'Ich konnte den Interpreten {artist} nicht in der Sammlung finden.',
        'es-ES': 'No he podido encontrar al artista {artist} en la colección.',
        'fr-FR': "Je n'ai pas trouvé l'artiste {artist} dans ta collection.",
        'it-IT': "Non riesco a trovare l'artista {artist} nella collezione.",
        'pt-BR': 'Não consegui encontrar o artista {artist} na coleção.',
    },
    'no_songs_by_artist': {
        'en-US': "I couldn't find any songs by {artist} in the collection.",
        'de-DE': 'Ich konnte keine Titel von {artist} in der Sammlung finden.',
        'es-ES': 'No he podido encontrar ninguna canción de {artist} en la colección.',
        'fr-FR': "Je n'ai trouvé aucun morceau de {artist} dans ta collection.",
        'it-IT': 'Non riesco a trovare brani di {artist} nella collezione.',
        'pt-BR': 'Não consegui encontrar nenhuma música de {artist} na coleção.',
    },
    'playing_music_by_artist': {
        'en-US': 'Playing music by: {artist}',
        'de-DE': 'Ich spiele Musik von: {artist}',
        'es-ES': 'Reproduciendo música de: {artist}',
        'fr-FR': 'Je joue de la musique de : {artist}',
        'it-IT': 'Riproduco la musica di: {artist}',
        'pt-BR': 'Tocando música de: {artist}',
    },
    'album_by_artist_not_found': {
        'en-US': "I couldn't find an album called {album} by {artist} in the collection.",
        'de-DE': 'Ich konnte das Album {album} von {artist} nicht in der Sammlung finden.',
        'es-ES': 'No he podido encontrar el álbum {album} de {artist} en la colección.',
        'fr-FR': "Je n'ai pas trouvé l'album {album} de {artist} dans ta collection.",
        'it-IT': "Non riesco a trovare l'album {album} di {artist} nella collezione.",
        'pt-BR': 'Não consegui encontrar um álbum chamado {album} de {artist} na coleção.',
    },
    'no_songs_on_album': {
        'en-US': "I couldn't find any songs on the album {album}.",
        'de-DE': 'Ich konnte keine Titel auf dem Album {album} finden.',
        'es-ES': 'No he podido encontrar ninguna canción en el álbum {album}.',
        'fr-FR': "Je n'ai trouvé aucun morceau sur l'album {album}.",
        'it-IT': "Non riesco a trovare brani nell'album {album}.",
        'pt-BR': 'Não consegui encontrar nenhuma música no álbum {album}.',
    },
    'playing_album_by_artist': {
        'en-US': 'Playing {album} by: {artist}',
        'de-DE': 'Ich spiele {album} von: {artist}',
        'es-ES': 'Reproduciendo {album} de: {artist}',
        'fr-FR': 'Je joue {album} de {artist}',
        'it-IT': 'Riproduco {album} di: {artist}',
        'pt-BR': 'Tocando {album} de: {artist}',
    },
    'album_not_found': {
        'en-US': "I couldn't find the album {album} in the collection.",
        'de-DE': 'Ich konnte das Album {album} nicht in der Sammlung finden.',
        'es-ES': 'No he podido encontrar el álbum {album} en la colección.',
        'fr-FR': "Je n'ai pas trouvé l'album {album} dans ta collection.",
        'it-IT': "Non riesco a trovare l'album {album} nella collezione.",
        'pt-BR': 'Não consegui encontrar o álbum {album} na coleção.',
    },
    'playing_album': {
        'en-US': 'Playing {album}',
        'de-DE': 'Ich spiele {album}',
        'es-ES': 'Reproduciendo {album}',
        'fr-FR': 'Je joue {album}',
        'it-IT': 'Riproduco {album}',
        'pt-BR': 'Tocando {album}',
    },
    'song_not_found': {
        'en-US': "I couldn't find a song called {song} by {artist} in the collection.",
        'de-DE': 'Ich konnte den Titel {song} von {artist} nicht in der Sammlung finden.',
        'es-ES': 'No he podido encontrar la canción {song} de {artist} en la colección.',
        'fr-FR': "Je n'ai pas trouvé le morceau {song} de {artist} dans ta collection.",
        'it-IT': 'Non riesco a trovare un brano chiamato {song} di {artist} nella collezione.',
        'pt-BR': 'Não consegui encontrar uma música chamada {song} de {artist} na coleção.',
    },
    'playing_song_by_artist': {
        'en-US': 'Playing {song} by {artist}',
        'de-DE': 'Ich spiele {song} von {artist}',
        'es-ES': 'Reproduciendo {song} de {artist}',
        'fr-FR': 'Je joue {song} de {artist}',
        'it-IT': 'Riproduco {song} di {artist}',
        'pt-BR': 'Tocando {song} de {artist}',
    },
    'playing_song': {
        'en-US': 'Playing {song}',
        'de-DE': 'Ich spiele {song}',
        'es-ES': 'Reproduciendo {song}',
        'fr-FR': 'Je joue {song}',
        'it-IT': 'Riproduco {song}',
        'pt-BR': 'Tocando {song}',
    },
    'playlist_not_found': {
        'en-US': "I couldn't find the playlist {playlist} in the collection.",
        'de-DE': 'Ich konnte die Playlist {playlist} nicht in der Sammlung finden.',
        'es-ES': 'No he podido encontrar la lista de reproducción {playlist} en la colección.',
        'fr-FR': "Je n'ai pas trouvé la playlist {playlist} dans ta collection.",
        'it-IT': 'Non riesco a trovare la playlist {playlist} nella collezione.',
        'pt-BR': 'Não consegui encontrar a playlist {playlist} na coleção.',
    },
    'no_genre_songs': {
        'en-US': "I couldn't find any {genre} songs in the collection.",
        'de-DE': 'Ich konnte keine {genre}-Titel in der Sammlung finden.',
        'es-ES': 'No he podido encontrar ninguna canción de {genre} en la colección.',
        'fr-FR': "Je n'ai trouvé aucun morceau de {genre} dans ta collection.",
        'it-IT': 'Non riesco a trovare brani di {genre} nella collezione.',
        'pt-BR': 'Não consegui encontrar nenhuma música de {genre} na coleção.',
    },
    'playing_genre': {
        'en-US': 'Playing {genre} music',
        'de-DE': 'Ich spiele {genre}-Musik',
        'es-ES': 'Reproduciendo música {genre}',
        'fr-FR': 'Je joue de la musique {genre}',
        'it-IT': 'Riproduco musica di {genre}',
        'pt-BR': 'Tocando música de {genre}',
    },
    'no_songs_in_collection': {
        'en-US': "I couldn't find any songs in the collection.",
        'de-DE': 'Ich konnte keine Titel in der Sammlung finden.',
        'es-ES': 'No he podido encontrar ninguna canción en la colección.',
        'fr-FR': "Je n'ai trouvé aucun morceau dans ta collection.",
        'it-IT': 'Non riesco a trovare brani nella collezione.',
        'pt-BR': 'Não consegui encontrar nenhuma música na coleção.',
    },
    'playing_random_music': {
        'en-US': 'Playing random music',
        'de-DE': 'Ich spiele zufällige Musik',
        'es-ES': 'Reproduciendo música aleatoria',
        'fr-FR': 'Je joue de la musique au hasard',
        'it-IT': 'Riproduco musica casuale',
        'pt-BR': 'Tocando música aleatória',
    },
    'no_favourite_songs': {
        'en-US': "You don't have any favourite songs in the collection.",
        'de-DE': 'Du hast keine Lieblingstitel in der Sammlung.',
        'es-ES': 'No tienes ninguna canción favorita en la colección.',
        'fr-FR': "Tu n'as aucun morceau favori dans ta collection.",
        'it-IT': 'Non hai brani preferiti nella collezione.',
        'pt-BR': 'Você não tem nenhuma música favorita na coleção.',
    },
    'playing_favourites': {
        'en-US': 'Playing your favourite tracks.',
        'de-DE': 'Ich spiele deine Lieblingstitel.',
        'es-ES': 'Reproduciendo tus canciones favoritas.',
        'fr-FR': 'Je joue tes morceaux favoris.',
        'it-IT': 'Riproduco i tuoi brani preferiti.',
        'pt-BR': 'Tocando suas músicas favoritas.',
    },
    'now_playing': {
        'en-US': 'This is {title} by {artist}, from the album {album}',
        'de-DE': 'Das ist {title} von {artist}, aus dem Album {album}',
        'es-ES': 'Esto es {title} de {artist}, del álbum {album}',
        'fr-FR': "C'est {title} de {artist}, extrait de l'album {album}",
        'it-IT': "Questo è {title} di {artist}, dall'album {album}",
        'pt-BR': 'Esta é {title}, de {artist}, do álbum {album}',
    },
    'no_radio_station': {
        'en-US': 'No radio station is configured.',
        'de-DE': 'Es ist kein Radiosender eingerichtet.',
        'es-ES': 'No hay ninguna emisora de radio configurada.',
        'fr-FR': "Aucune station de radio n'est configurée.",
        'it-IT': 'Nessuna stazione radio è configurata.',
        'pt-BR': 'Nenhuma emissora de rádio está configurada.',
    },
    'playing_radio_station': {
        'en-US': 'Playing the radio station {station}',
        'de-DE': 'Ich spiele den Radiosender {station}',
        'es-ES': 'Reproduciendo la emisora de radio {station}',
        'fr-FR': 'Je joue la station de radio {station}',
        'it-IT': 'Riproduco la stazione radio {station}',
        'pt-BR': 'Tocando a emissora de rádio {station}',
    },
    'did_not_get_that': {
        'en-US': "I didn't get that. Can you please say it again!!",
        'de-DE': 'Das habe ich nicht verstanden. Bitte sag das noch einmal!',
        'es-ES': 'No lo he entendido. ¿Puedes decirlo de nuevo, por favor?',
        'fr-FR': "Je n'ai pas compris. Peux-tu répéter ?",
        'it-IT': 'Non ho capito. Puoi ripetere, per favore!!',
        'pt-BR': 'Não entendi. Você pode repetir, por favor!!',
    },
    'nothing_found_for_query': {
        'en-US': "I couldn't find anything called {query} in the collection.",
        'de-DE': 'Ich konnte nichts mit dem Namen {query} in der Sammlung finden.',
        'es-ES': 'No he podido encontrar nada llamado {query} en la colección.',
        'fr-FR': "Je n'ai rien trouvé pour {query} dans ta collection.",
        'it-IT': 'Non riesco a trovare nulla che si chiami {query} nella collezione.',
        'pt-BR': 'Não consegui encontrar nada chamado {query} na coleção.',
    },
    'playing_description': {
        'en-US': 'Playing {description}',
        'de-DE': 'Ich spiele {description}',
        'es-ES': 'Reproduciendo {description}',
        'fr-FR': 'Je joue {description}',
        'it-IT': 'Riproduco {description}',
        'pt-BR': 'Tocando {description}',
    },
    'decade_not_understood': {
        'en-US': "I didn't understand the decade {decade}.",
        'de-DE': 'Ich habe das Jahrzehnt {decade} nicht verstanden.',
        'es-ES': 'No he entendido la década {decade}.',
        'fr-FR': "Je n'ai pas compris la décennie {decade}.",
        'it-IT': 'Non ho capito il decennio {decade}.',
        'pt-BR': 'Não entendi a década {decade}.',
    },
    'no_music_from_decade': {
        'en-US': "I couldn't find any music from the {decade} in the collection.",
        'de-DE': 'Ich konnte keine Musik aus dem {decade} in der Sammlung finden.',
        'es-ES': 'No he podido encontrar ninguna música de los años {decade} en la colección.',
        'fr-FR': "Je n'ai trouvé aucune musique des années {decade} dans ta collection.",
        'it-IT': 'Non riesco a trovare musica dagli anni {decade} nella collezione.',
        'pt-BR': 'Não consegui encontrar nenhuma música dos anos {decade} na coleção.',
    },
    'playing_decade': {
        'en-US': 'Playing music from the {decade}',
        'de-DE': 'Ich spiele Musik aus dem {decade}',
        'es-ES': 'Reproduciendo música de los años {decade}',
        'fr-FR': 'Je joue de la musique des années {decade}',
        'it-IT': 'Riproduco la musica dagli anni {decade}',
        'pt-BR': 'Tocando música dos anos {decade}',
    },
    'no_playlists': {
        'en-US': 'You do not have any play lists in the collection.',
        'de-DE': 'Du hast keine Playlists in der Sammlung.',
        'es-ES': 'No tienes ninguna lista de reproducción en la colección.',
        'fr-FR': "Tu n'as aucune playlist dans ta collection.",
        'it-IT': 'Non hai playlist nella collezione.',
        'pt-BR': 'Você não tem nenhuma playlist na coleção.',
    },
    'no_more_playlists': {
        'en-US': 'There are no more play lists.',
        'de-DE': 'Es gibt keine weiteren Playlists.',
        'es-ES': 'No hay más listas de reproducción.',
        'fr-FR': "Il n'y a plus de playlists.",
        'it-IT': 'Non ci sono altre playlist.',
        'pt-BR': 'Não há mais playlists.',
    },
    'playlist_not_found_by_query': {
        'en-US': "I couldn't find a play list about {query}.",
        'de-DE': 'Ich konnte keine Playlist zu {query} finden.',
        'es-ES': 'No he podido encontrar una lista de reproducción sobre {query}.',
        'fr-FR': "Je n'ai pas trouvé de playlist sur {query}.",
        'it-IT': 'Non riesco a trovare una playlist su {query}.',
        'pt-BR': 'Não consegui encontrar uma playlist sobre {query}.',
    },
    'nothing_to_resume': {
        'en-US': 'There is nothing to resume.',
        'de-DE': 'Es gibt nichts fortzusetzen.',
        'es-ES': 'No hay nada que reanudar.',
        'fr-FR': "Il n'y a rien à reprendre.",
        'it-IT': "Non c'è nulla da riprendere.",
        'pt-BR': 'Não há nada para retomar.',
    },
    'radio_cannot_be_skipped': {
        'en-US': 'A radio stream cannot be skipped.',
        'de-DE': 'Ein Radio-Stream kann nicht übersprungen werden.',
        'es-ES': 'No se puede saltar una emisora de radio.',
        'fr-FR': 'On ne peut pas passer une station de radio.',
        'it-IT': 'Uno streaming radio non può essere saltato.',
        'pt-BR': 'Não é possível pular uma transmissão de rádio.',
    },
    'no_more_tracks_in_queue': {
        'en-US': 'There are no more tracks in the queue.',
        'de-DE': 'Es gibt keine weiteren Titel in der Warteschlange.',
        'es-ES': 'No hay más canciones en la cola.',
        'fr-FR': "Il n'y a plus de morceaux dans la file d'attente.",
        'it-IT': 'Non ci sono altri brani in coda.',
        'pt-BR': 'Não há mais músicas na fila.',
    },
    'no_previous_track': {
        'en-US': 'There is no previous track in the history.',
        'de-DE': 'Es gibt keinen vorherigen Titel im Verlauf.',
        'es-ES': 'No hay ninguna canción anterior en el historial.',
        'fr-FR': "Il n'y a pas de morceau précédent dans l'historique.",
        'it-IT': "Non c'è alcun brano precedente nella cronologia.",
        'pt-BR': 'Não há música anterior no histórico.',
    },
    'did_you_mean': {
        'en-US': 'Did you mean {choices}?',
        'de-DE': 'Meintest du {choices}?',
        'es-ES': '¿Te refieres a {choices}?',
        'fr-FR': 'Voulais-tu dire {choices} ?',
        'it-IT': 'Intendi forse {choices}?',
        'pt-BR': 'Você quis dizer {choices}?',
    },
    'playlist_without_songs': {
        'en-US': 'The playlist {playlist} does not contain any songs.',
        'de-DE': 'Die Playlist {playlist} enthält keine Titel.',
        'es-ES': 'La lista de reproducción {playlist} no contiene ninguna canción.',
        'fr-FR': 'La playlist {playlist} ne contient aucun morceau.',
        'it-IT': 'La playlist {playlist} non contiene alcun brano.',
        'pt-BR': 'A playlist {playlist} não contém nenhuma música.',
    },
    'playing_playlist': {
        'en-US': 'Playing playlist {playlist}',
        'de-DE': 'Ich spiele die Playlist {playlist}',
        'es-ES': 'Reproduciendo la lista de reproducción {playlist}',
        'fr-FR': 'Je joue la playlist {playlist}',
        'it-IT': 'Riproduco la playlist {playlist}',
        'pt-BR': 'Tocando a playlist {playlist}',
    },
    'playlists_list': {
        'en-US': 'You have these playlists: {page}',
        'de-DE': 'Du hast diese Playlists: {page}',
        'es-ES': 'Tienes estas listas de reproducción: {page}',
        'fr-FR': 'Tu as ces playlists : {page}',
        'it-IT': 'Hai queste playlist: {page}',
        'pt-BR': 'Você tem estas playlists: {page}',
    },
    'playlists_list_more': {
        'en-US': 'Say hear more to hear the rest',
        'de-DE': 'Sag höre mehr, um den Rest zu hören',
        'es-ES': 'Di escuchar más para escuchar el resto',
        'fr-FR': 'Dis « en savoir plus » pour voir le reste',
        'it-IT': 'Dici senti altre per sentire il resto',
        'pt-BR': 'Diga ouvir mais para ouvir o resto',
    },
    'generic_error': {
        'en-US': "Sorry, I didn't get that. Can you please say it again!!",
        'de-DE': 'Entschuldigung, das habe ich nicht verstanden. Bitte sag das noch einmal!',
        'es-ES': 'Lo siento, no lo he entendido. ¿Puedes decirlo de nuevo, por favor?',
        'fr-FR': "Désolé, je n'ai pas compris. Peux-tu répéter ?",
        'it-IT': 'Scusa, non ho capito. Puoi ripetere, per favore!!',
        'pt-BR': 'Desculpe, não entendi. Você pode repetir, por favor!!',
    },
    'conjunction_and': {
        'en-US': 'and',
        'de-DE': 'und',
        'es-ES': 'y',
        'fr-FR': 'et',
        'it-IT': 'e',
        'pt-BR': 'e',
    },
    'conjunction_or': {
        'en-US': 'or',
        'de-DE': 'oder',
        'es-ES': 'o',
        'fr-FR': 'ou',
        'it-IT': 'o',
        'pt-BR': 'ou',
    },
}

# The voice commands that are sent to an Alexa device.  They are not a
# simple translation, because an Alexa device matches them against the
# utterances of its own language.
_ALEXA_COMMANDS = {
    'pause': {
        'en-US': 'ask {skill_name} to pause',
        'de-DE': 'frage {skill_name}, pausiere',
        'es-ES': 'pide a {skill_name} que pause',
        'fr-FR': 'demande à {skill_name} de mettre en pause',
        'it-IT': 'chiedi a {skill_name} di mettere in pausa',
        'pt-BR': 'peça para {skill_name} pausar',
    },
    'resume': {
        'en-US': 'ask {skill_name} to resume',
        'de-DE': 'frage {skill_name}, spiele weiter',
        'es-ES': 'pide a {skill_name} que continúe',
        'fr-FR': 'demande à {skill_name} de reprendre la lecture',
        'it-IT': 'chiedi a {skill_name} di riprendere la riproduzione',
        'pt-BR': 'peça para {skill_name} continuar a reprodução',
    },
    'stop': {
        'en-US': 'ask {skill_name} to stop',
        'de-DE': 'frage {skill_name}, stoppe die Wiedergabe',
        'es-ES': 'pide a {skill_name} que detenga la reproducción',
        'fr-FR': "demande à {skill_name} d'arrêter la lecture",
        'it-IT': 'chiedi a {skill_name} di fermare la riproduzione',
        'pt-BR': 'peça para {skill_name} parar a reprodução',
    },
    'next': {
        'en-US': 'ask {skill_name} to skip to the next song',
        'de-DE': 'frage {skill_name}, spiele den nächsten Titel',
        'es-ES': 'pide a {skill_name} que pase a la siguiente canción',
        'fr-FR': 'demande à {skill_name} de passer au morceau suivant',
        'it-IT': 'chiedi a {skill_name} di riprodurre il brano successivo',
        'pt-BR': 'peça para {skill_name} tocar a próxima música',
    },
    'previous': {
        'en-US': 'ask {skill_name} to play the previous song',
        'de-DE': 'frage {skill_name}, spiele den vorherigen Titel',
        'es-ES': 'pide a {skill_name} que reproduzca la canción anterior',
        'fr-FR': 'demande à {skill_name} de jouer le morceau précédent',
        'it-IT': 'chiedi a {skill_name} di riprodurre il brano precedente',
        'pt-BR': 'peça para {skill_name} tocar a música anterior',
    },
    'volume_up': {
        'en-US': 'volume up',
        'de-DE': 'lauter',
        'es-ES': 'sube el volumen',
        'fr-FR': 'monte le volume',
        'it-IT': 'alza il volume',
        'pt-BR': 'aumente o volume',
    },
    'volume_down': {
        'en-US': 'volume down',
        'de-DE': 'leiser',
        'es-ES': 'baja el volumen',
        'fr-FR': 'baisse le volume',
        'it-IT': 'abbassa il volume',
        'pt-BR': 'diminua o volume',
    },
    'set_volume': {
        'en-US': 'set volume to {volume}',
        'de-DE': 'setze die Lautstärke auf {volume}',
        'es-ES': 'pon el volumen al {volume}',
        'fr-FR': 'mets le volume sur {volume}',
        'it-IT': 'imposta il volume su {volume}',
        'pt-BR': 'ajuste o volume para {volume}',
    },
    'play_playlist': {
        'en-US': 'ask {skill_name} to play playlist {playlist_name}',
        'de-DE': 'frage {skill_name}, spiele die Playlist {playlist_name}',
        'es-ES': 'pide a {skill_name} que reproduzca la lista de reproducción {playlist_name}',
        'fr-FR': 'demande à {skill_name} de jouer la playlist {playlist_name}',
        'it-IT': 'chiedi a {skill_name} di riprodurre la playlist {playlist_name}',
        'pt-BR': 'peça para {skill_name} tocar a playlist {playlist_name}',
    },
    'play_random': {
        'en-US': 'ask {skill_name} to play random music',
        'de-DE': 'frage {skill_name}, spiele zufällige Musik',
        'es-ES': 'pide a {skill_name} que reproduzca música aleatoria',
        'fr-FR': 'demande à {skill_name} de jouer de la musique au hasard',
        'it-IT': 'chiedi a {skill_name} di riprodurre musica casuale',
        'pt-BR': 'peça para {skill_name} tocar música aleatória',
    },
    'play_track': {
        'en-US': 'ask {skill_name} to play the song {title} by {artist}',
        'de-DE': 'frage {skill_name}, spiele das Lied {title} von {artist}',
        'es-ES': 'pide a {skill_name} que reproduzca la canción {title} de {artist}',
        'fr-FR': 'demande à {skill_name} de jouer le morceau {title} de {artist}',
        'it-IT': 'chiedi a {skill_name} di riprodurre il brano {title} di {artist}',
        'pt-BR': 'peça para {skill_name} tocar a música {title} de {artist}',
    },
    'play_track_quiet': {
        'en-US': 'ask {skill_name} to play the song {title} by {artist} quietly',
        'de-DE': 'frage {skill_name}, spiele das Lied {title} von {artist} leise',
        'es-ES': 'pide a {skill_name} que reproduzca la canción {title} de {artist} en silencio',
        'fr-FR': 'demande à {skill_name} de jouer le morceau {title} de {artist} sans annonce',
        'it-IT': 'chiedi a {skill_name} di riprodurre il brano {title} di {artist} in silenzio',
        'pt-BR': 'peça para {skill_name} tocar a música {title} de {artist} silenciosamente',
    },
}


class _SafeFormatDict(dict):
    """A mapping that keeps unknown placeholders instead of raising."""

    def __missing__(self, key):
        return '{' + key + '}'


def normalize_locale(locale) -> str:
    """Map a locale to one of the supported locales

    A locale that only names a language, like "de", is mapped to the
    supported locale of that language.  A locale that is not supported at
    all falls back to the default locale.

    :param locale: The locale to map
    :return: The supported locale
    :rtype: str
    """

    if not locale or not isinstance(locale, str):
        return DEFAULT_LOCALE

    tag = locale.strip().replace('_', '-')

    if not tag:
        return DEFAULT_LOCALE

    for supported in SUPPORTED_LOCALES:
        if tag.lower() == supported.lower():
            return supported

    language = tag.split('-', 1)[0].lower()

    for supported in SUPPORTED_LOCALES:
        if supported.split('-', 1)[0].lower() == language:
            return supported

    logger.debug('The locale "%s" is not supported, "%s" is used instead.', locale, DEFAULT_LOCALE)

    return DEFAULT_LOCALE


def message_keys() -> list:
    """Get the keys of all the messages of the skill

    :return: The keys of the messages
    :rtype: list
    """

    return list(_MESSAGES)


def command_keys() -> list:
    """Get the keys of all the voice commands of the skill

    :return: The keys of the voice commands
    :rtype: list
    """

    return list(_ALEXA_COMMANDS)


# The key of the message that explains the skill in general
HELP_OVERVIEW_KEY = 'help_overview'

HELP_TOPIC_ALIASES = {
    'Musik abspielen': 'playing_music',
    'Playlists finden': 'finding_playlists',
    'Wiedergabe steuern': 'playback_controls',
    'Playing music': 'playing_music',
    'Finding play lists': 'finding_playlists',
    'Playback controls': 'playback_controls',
    'Reproducir música': 'playing_music',
    'Buscar listas de reproducción': 'finding_playlists',
    'Controles de reproducción': 'playback_controls',
    'Jouer de la musique': 'playing_music',
    'Trouver des playlists': 'finding_playlists',
    'Contrôles de lecture': 'playback_controls',
    'Riprodurre musica': 'playing_music',
    'Trovare le playlist': 'finding_playlists',
    'Comandi di riproduzione': 'playback_controls',
    'Tocar música': 'playing_music',
    'Encontrar playlists': 'finding_playlists',
    'Controles de reprodução': 'playback_controls',
}
"""The value of the help topic slot and the key of the message that explains it

The values are the ones of the slot type "help_topic" of the interaction
model, they are translated in every language of the skill.
"""

HELP_TOPICS = {
    'playing_music': 'help_topic_playing_music',
    'finding_playlists': 'help_topic_finding_playlists',
    'playback_controls': 'help_topic_playback_controls',
}
"""The key of the topic of a help request and the key of its message"""


def get_configured_locale() -> str:
    """Get the locale of the Alexa account from the environment

    :return: The configured locale
    :rtype: str
    """

    return normalize_locale(os.getenv('NAVI_ALEXA_LOCALE'))


class Translator:
    """Translates the messages of the skill into a language

    The messages of a locale that is not supported fall back to the
    messages of the default locale, so that a missing translation never
    breaks the skill.
    """

    def __init__(self, locale=None) -> None:
        """
        :param locale: The locale of the messages
        """

        self.locale = normalize_locale(locale)

    def t(self, key: str, **kwargs) -> str:
        """Get the translated message of a key

        :param str key: The key of the message
        :param kwargs: The values of the placeholders of the message
        :return: The translated message
        :rtype: str
        """

        template = self.template(key)

        if not kwargs:
            return template

        return template.format_map(_SafeFormatDict(kwargs))

    def template(self, key: str) -> str:
        """Get the untranslated text of a message in the language of the translator

        :param str key: The key of the message
        :return: The text of the message
        :rtype: str
        """

        messages = _MESSAGES.get(key)

        if messages is None:
            raise KeyError(f'Unknown message "{key}".')

        template = messages.get(self.locale)

        if template is None:
            template = messages.get(DEFAULT_LOCALE)

        return template

    def conjunction(self, name: str) -> str:
        """Get a conjunction of the language of the translator

        :param str name: The name of the conjunction, "and" or "or"
        :return: The conjunction
        :rtype: str
        """

        return self.t(f'conjunction_{name}')


def get_request_locale(handler_input, fallback_locale: str = None) -> str:
    """Get the locale of a request

    The locale of the request is the language that the user speaks to the
    Alexa device.  If the request does not carry one, the configured locale
    of the Alexa account is used.

    :param handler_input: The Amazon Alexa HandlerInput object
    :param str fallback_locale: The locale to use when the request has none
    :return: The locale of the request
    :rtype: str
    """

    locale = None

    try:
        locale = handler_input.request_envelope.request.locale
    except AttributeError:
        locale = None

    if not locale:
        locale = fallback_locale if fallback_locale else get_configured_locale()

    return normalize_locale(locale)


def get_translator(handler_input, fallback_locale: str = None) -> Translator:
    """Get the translator for the language of a request

    :param handler_input: The Amazon Alexa HandlerInput object
    :param str fallback_locale: The locale to use when the request has none
    :return: The translator of the request
    :rtype: Translator
    """

    return Translator(get_request_locale(handler_input, fallback_locale))


def alexa_command(key: str, locale=None, **kwargs) -> str:
    """Build the voice command of an Alexa device

    The command is built in the language of the locale, because an Alexa
    device only understands a voice command in the language that it is set
    to.

    :param str key: The key of the command
    :param locale: The locale of the command
    :param kwargs: The values of the placeholders of the command
    :return: The voice command
    :rtype: str
    """

    commands = _ALEXA_COMMANDS.get(key)

    if commands is None:
        raise ValueError('Unsupported Alexa control command.')

    template = commands.get(normalize_locale(locale)) or commands[DEFAULT_LOCALE]

    return template.format_map(_SafeFormatDict(kwargs))
