# Credits

Dieses Projekt ist ein Fork von [rosskouk/asknavidrome](https://github.com/rosskouk/asknavidrome)
(Ross Stewart, MIT-Lizenz) mit lokalen Erweiterungen.

Die Upstream-Features (Subsonic-API-Zugriff, Alexa-Skill-Handler, MediaQueue,
Scrobbling, Multi-Threading bei großen Playlists) stammen von Ross Stewart.

## Übernommene Features aus Forks

Alle folgenden Forks stehen unter derselben MIT-Lizenz wie das Upstream-Projekt
(`Copyright (c) 2022 Ross Stewart`). Die übernommenen Codebausteine wurden
an unsere Codebasis und unsere Bedürfnisse angepasst; die Anpassungen sind in
der Spalte „Lokale Änderungen" dokumentiert.

| ID | Feature | Autor | Fork | Lizenz | Lokale Änderungen | Status |
|----|---------|-------|------|--------|-------------------|--------|
| A1 | Kein Absturz bei Playlists mit 0 oder 1 Titel | Nigel | [nigelg/asknavidrome](https://github.com/nigelg/asknavidrome) | MIT | Als gemeinsamer Helper `enqueue_initial_tracks()` in `skill/app.py` umgesetzt, deckt alle 7 Aufrufstellen ab | übernommen |
| A2 | Kein Absturz bei leerem Buffer | Locqust / John Paul Gosling | [locqust/asknavidrome](https://github.com/locqust/asknavidrome), [johnpaulgosling/asknavidrome](https://github.com/johnpaulgosling/asknavidrome) | MIT | `enqueue_next_track()` liefert `None` statt `IndexError`, Aufrufer prüfen den Wert | übernommen |
| A3 | Queue-Erschöpfung sauber behandeln | Locqust | [locqust/asknavidrome](https://github.com/locqust/asknavidrome) | MIT | Ergänzt um sprechbare Rückmeldung „keine weiteren Titel" | übernommen |
| A4 | Debug-Endpunkte per Token schützen | John Paul Gosling | [johnpaulgosling/asknavidrome](https://github.com/johnpaulgosling/asknavidrome) | MIT | `NAVI_DEBUG_TOKEN` + `hmac.compare_digest`, 404 statt 403, damit die Endpunkte nicht existieren | übernommen |
| A5 | Session-Token nicht ins Log schreiben | John Paul Gosling | [johnpaulgosling/asknavidrome](https://github.com/johnpaulgosling/asknavidrome) | MIT | Nur noch Metadaten (Request-Typ, Intent-Name) statt des kompletten Request-Objekts | übernommen |
| A6 | Keine Stream-URIs in der Debug-Tabelle | John Paul Gosling | [johnpaulgosling/asknavidrome](https://github.com/johnpaulgosling/asknavidrome) | MIT | Spalte aus `skill/templates/table.html` entfernt | übernommen |
| A7 | ENQUEUE previous_token korrekt setzen | bickns | [bickns/asknavidrome](https://github.com/bickns/asknavidrome) | MIT | `MediaQueue.set_first_previous_id()` ergänzt, Mutation erfolgt im Manager-Prozess | übernommen |
| B1 | Echtes Album-Cover in Alexa | Locqust | [locqust/asknavidrome](https://github.com/locqust/asknavidrome) | MIT | Proxy-Variante bevorzugt (keine Navidrome-Credentials in der Bild-URL), `NAVI_BASE_URL` ergänzt | übernommen |
| B2 | Now-Playing pro Echo an Navidrome melden | Mike (mpdeglau) | [mpdeglau/asknavidrome](https://github.com/mpdeglau/asknavidrome) | MIT | Auf unsere `renderer`-Namensgebung und den lokalen Gerätebegriff abgestimmt | übernommen |
| B3 | Präzisere Titelsuche | djh20 | [djh20/asknavidrome](https://github.com/djh20/asknavidrome) | MIT | Filter als eigenständige Hilfsfunktion, False-Negative-Risiko dokumentiert | übernommen |
| B4 | Fuzzy-Matching für Artists/Genres | Gurjot Sidhu | [gsidhu/asknavidrome](https://github.com/gsidhu/asknavidrome) | MIT | Eigenes Modul `fuzzy_match.py`, `rapidfuzz` als neue Abhängigkeit | übernommen |
| B5 | Subsonic-API-Härtung | bickns | [bickns/asknavidrome](https://github.com/bickns/asknavidrome) | MIT | Defensives `.get()`, Ping-Diagnose, `count`-Parameter | übernommen |
| B6 | Exception-Handler für Alexa-Fehler | bickns | [bickns/asknavidrome](https://github.com/bickns/asknavidrome) | MIT | Eigenes Modul `exception_handlers.py`, verhindert Endlos-Speech-Loops | übernommen |
| B7 | Slot-Synonyme korrekt auflösen | Julien Fagnan | [jfagn/asknavidrome](https://github.com/jfagn/asknavidrome) | MIT | Modul `utils.py`, Fallback auf den Rohwert, wenn keine Auflösung vorliegt | übernommen |
| C1 | Shuffle-Playlist | krimil / John Paul Gosling | [krimil/asknavidrome](https://github.com/krimil/asknavidrome), [johnpaulgosling/asknavidrome](https://github.com/johnpaulgosling/asknavidrome) | MIT | Leere-Playlist-Fall und Per-Device-Queue berücksichtigt | übernommen |
| C2 | Song per Titel ohne Artist | djh20 / Nick Campion / John Paul Gosling / Locqust | [djh20/asknavidrome](https://github.com/djh20/asknavidrome), [greeninja/asknavidrome](https://github.com/greeninja/asknavidrome), [johnpaulgosling/asknavidrome](https://github.com/johnpaulgosling/asknavidrome), [locqust/asknavidrome](https://github.com/locqust/asknavidrome) | MIT | Nutzt die Titel-Filterung aus B3 | übernommen |
| C3 | Musik nach Jahrzehnt | bickns | [bickns/asknavidrome](https://github.com/bickns/asknavidrome) | MIT | Jahrzehnt-Filter über das Subsonic-API | übernommen |
| C4 | Eigenes Playback je Echo | bickns / Mike (mpdeglau) | [bickns/asknavidrome](https://github.com/bickns/asknavidrome), [mpdeglau/asknavidrome](https://github.com/mpdeglau/asknavidrome) | MIT | Modul `state.py` nach bickns, Manager aus dem bestehenden `app.py` wiederverwendet, Fallback-Gerät ohne Gerätekontext | übernommen |
| C5 | Playlist-Discovery (Liste, „hör mehr", Stimmung) | Mike (mpdeglau) | [mpdeglau/asknavidrome](https://github.com/mpdeglau/asknavidrome) | MIT | Modul `playlist_names.py`, Gruppen und gesprochene Namen konfigurierbar | übernommen |
| C6 | Radio-/Stream-Wiedergabe | Mike (mpdeglau) | [mpdeglau/asknavidrome](https://github.com/mpdeglau/asknavidrome) | MIT | Stream-URLs ausschließlich aus der Umgebung, kein Scrobbling von Streams | übernommen |
| C7 | Hilfethemen | Mike (mpdeglau) | [mpdeglau/asknavidrome](https://github.com/mpdeglau/asknavidrome) | MIT | Themen konfigurierbar, deutschsprachige Texte | übernommen |
| C8 | Freitext-Suche „spiel {query}" | bickns / Gurjot Sidhu | [bickns/asknavidrome](https://github.com/bickns/asknavidrome), [gsidhu/asknavidrome](https://github.com/gsidhu/asknavidrome) | MIT | Modul `search.py` mit Scoring, integriert die B4-Fuzzy-Suche | übernommen |

## Lokale Features ohne Upstream-Vorlage

| Feature | Beschreibung |
|---------|--------------|
| `skill/castnavidrome/upnp/` | Eigener UPnP-MediaRenderer (SSDP, Description, SOAP, DIDL) je Alexa-Gerät |
| `skill/castnavidrome/renderer_host.py` | Host-Prozess des Renderers, Gerätefilter, Persistenz der UUIDs |
| `skill/castnavidrome/renderer_registry.py` | Stabile Zuordnung Alexa-Gerät → UPnP-UUID über `ownerId` + `serialNumber` |
| `skill/castnavidrome/alexa_device_filter.py` | Geräteauswahl über Typ, Name, Regex und Online-Status |
| `skill/castnavidrome/alexa_remote.py` | Textbefehle an Echo-Geräte, Geräteliste über die Amazon-Geräte-API |
| `skill/castnavidrome/localization.py` | Lokalisierung: übersetzte Antworten des Skills und Sprachbefehle in der Sprache des Geräts |
| `alexa/` | Interaction Models, eine Datei je Sprache (`de-DE`, `en-US`, `es-ES`, `fr-FR`, `it-IT`, `pt-BR`) |
