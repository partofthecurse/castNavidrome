# castNavidrome

Alexa Skill, die Alexa-Geräte mit einem Subsonic-API-kompatiblen Medienserver (z. B. Navidrome) verbindet, damit du deine eigene Musiksammlung auf deinen Echo-Geräten streamen kannst.

**castNavidrome ist ein Fork von [AskNavidrome](https://github.com/rosskouk/asknavidrome)** (Ross Stewart, MIT-Lizenz) mit lokalen Erweiterungen aus mehreren Community-Forks sowie einem eingebauten UPnP-MediaRenderer für jedes Alexa-Gerät. Siehe [Fork von AskNavidrome](#fork-von-asknavidrome) und [CREDITS.md](CREDITS.md).

## Highlights

- Musik nach Künstler, Album, Titel, Genre, Playlist, Jahrzehnt oder Freitextsuche abspielen.
- Wiedergabewarteschlange mischen, Lieder markieren/entmarkieren, Details des aktuellen Titels anzeigen.
- Radio-Streams und Playlist-Entdeckung ("spiele mehr Playlists wie diese", "finde eine Playlist").
- Hilfethemen und gesprochene Antworten in der Sprache des Echo-Geräts.
- Optionaler UPnP-MediaRenderer: jedes ausgewählte Alexa-Gerät erscheint in Navidrome als eigener Renderer, sodass DLNA-Clients (Symfonium, Supersonic, …) Titel an einzelne Echoes senden können.
- Optionaler Amazon-Login mit Benutzername, Passwort und TOTP/2FA (ersetzt das manuelle Kopieren der Cookie-Datei).
- Läuft direkt mit Python oder in einem Docker-Container (empfohlen).

## Sprachen

Dieses README: Deutsch.
- [`README.md`](README.md) — English
- [`README.es.md`](README.es.md) — Español

Die Interaktionsmodelle für die Alexa Developer Console liegen in [`alexa/`](alexa) für `de-DE`, `en-US`, `es-ES`, `fr-FR`, `it-IT`, `pt-BR`.

## Fork von AskNavidrome

castNavidrome ist ein Fork von [rosskouk/asknavidrome](https://github.com/rosskouk/asknavidrome). Die Upstream-Features (Subsonic-API-Zugriff, Alexa-Skill-Handler, MediaQueue, Scrobbling, Multi-Threading bei großen Playlists) stammen von Ross Stewart.

Weitere Features wurden aus Community-Forks von AskNavidrome (alle MIT-lizenziert) und aus der lokalen Entwicklung übernommen. Den genauen Ursprung jedes Features, den Autor, den Fork und die lokalen Änderungen finden Sie in [CREDITS.md](CREDITS.md).

Lokale Features ohne Upstream-Vorlage:

- `skill/castnavidrome/upnp/` — eigener UPnP-MediaRenderer (SSDP, Description, SOAP, DIDL) pro Alexa-Gerät.
- `skill/castnavidrome/renderer_host.py` — Renderer-Host-Prozess, Gerätefilter, UUID-Persistenz.
- `skill/castnavidrome/renderer_registry.py` — stabiles Mapping Alexa-Gerät → UPnP-UUID (`ownerId` + `serialNumber`).
- `skill/castnavidrome/alexa_device_filter.py` — Geräteauswahl nach Typ, Name, Regex und Online-Status.
- `skill/castnavidrome/alexa_remote.py` — Textbefehle an Echo-Geräte, Geräteliste über die Amazon-Geräte-API.
- `skill/castnavidrome/localization.py` — lokalisierte Skill-Antworten und sprachspezifische Sprachbefehle.
- `alexa/` — Interaktionsmodelle, eine Datei pro Sprache.

Die Software steht unter der [MIT-Lizenz](LICENSE). Der ursprüngliche Copyright-Hinweis von Ross Stewart wird beibehalten; lokale Änderungen sind urheberrechtlich geschützt von den castNavidrome-Mitwirkenden (siehe `CREDITS.md` und `LICENSE`).

## Voraussetzungen

- Eine digitale Musiksammlung, bereitgestellt von einem Subsonic-API-kompatiblen Medienserver (getestet mit Navidrome).
- Der Medienserver muss über HTTPS mit einem gültigen TLS-Zertifikat erreichbar sein (Amazon verlangt dies für das Streaming).
- Ein Echo-Gerät, dessen Locale mit der Skill-Locale übereinstimmt.
- Ein in der [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask) erstellter Alexa-Skill mit aktiviertem Audio-Player-Interface und einem HTTPS-Endpunkt, der auf diesen Webdienst zeigt.
- (Optional, für die Media-Renderer) Port `1900/udp` für die SSDP-Entdeckung verfügbar und der Container mit Host-Netzwerk oder macvlan.

## Installation

### Option 1: Docker Compose (empfohlen)

1. Beispielkonfiguration kopieren:
   ```bash
   cp .env.example .env
   ```
2. Bearbeiten Sie `.env` und tragen Sie Ihre eigenen Werte ein (Navidrome-URL, Benutzer, Passwort, Skill-ID, …).  
   `.env` wird **nicht** in die Versionskontrolle übernommen.
3. Starten Sie alles:
   ```bash
   docker compose up -d --build
   ```

Beispiel `docker-compose.yml`:

```yaml
services:
  castnavidrome:
    container_name: castnavidrome
    build:
      context: .
      dockerfile: Dockerfile
    image: castnavidrome:local
    environment:
      - NAVI_SKILL_ID=${NAVI_SKILL_ID}
      - NAVI_URL=${NAVI_URL}
      - NAVI_BASE_URL=${NAVI_BASE_URL}
      - NAVI_USER=${NAVI_USER}
      - NAVI_PASS=${NAVI_PASS}
      - NAVI_SONG_COUNT=50
      - NAVI_PORT=443
      - NAVI_API_PATH=/rest
      - NAVI_API_VER=1.16.1
      - NAVI_DEBUG=0
      - NAVI_ALEXA_API_KEY=${NAVI_ALEXA_API_KEY}
      - NAVI_ALEXA_DOMAIN=${NAVI_ALEXA_DOMAIN:-amazon.com}
      - NAVI_ALEXA_LOCALE=${NAVI_ALEXA_LOCALE:-de-DE}
      - NAVI_ALEXA_SKILL_NAME=${NAVI_ALEXA_SKILL_NAME:-castnavidrome}
      - NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
      - NAVI_AMAZON_USER=${NAVI_AMAZON_USER:-}
      - NAVI_AMAZON_PASS=${NAVI_AMAZON_PASS:-}
      - NAVI_AMAZON_TOTP_SECRET=${NAVI_AMAZON_TOTP_SECRET:-}
      - NAVI_AMAZON_SESSION_FILE=/var/lib/castnavidrome/amazon_session.json
      - NAVI_RADIO_URL=${NAVI_RADIO_URL:-}
      - NAVI_RADIO_STATIONS_URL=${NAVI_RADIO_STATIONS_URL:-}
      - NAVI_PLAYLIST_NAME_PATTERN=${NAVI_PLAYLIST_NAME_PATTERN:-}
      - NAVI_PLAYLIST_SPOKEN_FORMAT=${NAVI_PLAYLIST_SPOKEN_FORMAT:-}
      - NAVI_PLAYLIST_QUALIFIED_FORMAT=${NAVI_PLAYLIST_QUALIFIED_FORMAT:-}
    volumes:
      - ./.secrets/alexa.cookies:/run/secrets/alexa.cookies:ro
      - ./state:/var/lib/castnavidrome
    restart: unless-stopped

  # Optional: stellt jedes ausgewählte Alexa-Gerät als eigenen UPnP-MediaRenderer bereit.
  # Benötigt das Host-Netzwerk, damit SSDP (Port 1900/udp) zur Entdeckung funktioniert.
  castnavidrome-renderer:
    build:
      context: .
      dockerfile: Dockerfile
    image: castnavidrome:local
    container_name: castnavidrome-renderer
    network_mode: host
    command: ["python3", "-m", "castnavidrome.renderer_host"]
    environment:
      - NAVI_ALEXA_RENDERER_ENABLED=${NAVI_ALEXA_RENDERER_ENABLED:-yes}
      - NAVI_ALEXA_RENDERER_STATE_FILE=/var/lib/castnavidrome/renderer-devices.json
      - NAVI_ALEXA_RENDERER_ADVERTISE_HOST=${NAVI_ALEXA_RENDERER_ADVERTISE_HOST:-}
      - NAVI_ALEXA_RENDERER_PORT=${NAVI_ALEXA_RENDERER_PORT:-49443}
      - NAVI_ALEXA_RENDERER_REFRESH_SECONDS=${NAVI_ALEXA_RENDERER_REFRESH_SECONDS:-300}
      - NAVI_ALEXA_RENDERER_MIN_REFRESH_SECONDS=${NAVI_ALEXA_RENDERER_MIN_REFRESH_SECONDS:-60}
      - NAVI_ALEXA_RENDERER_NAME_PREFIX=${NAVI_ALEXA_RENDERER_NAME_PREFIX:-}
      - NAVI_ALEXA_RENDERER_DEVICE_TYPES=${NAVI_ALEXA_RENDERER_DEVICE_TYPES:-}
      - NAVI_ALEXA_RENDERER_EXCLUDED_DEVICE_TYPES=${NAVI_ALEXA_RENDERER_EXCLUDED_DEVICE_TYPES:-}
      - NAVI_ALEXA_RENDERER_NAME_INCLUDE=${NAVI_ALEXA_RENDERER_NAME_INCLUDE:-}
      - NAVI_ALEXA_RENDERER_NAME_EXCLUDE=${NAVI_ALEXA_RENDERER_NAME_EXCLUDE:-}
      - NAVI_ALEXA_RENDERER_NAME_REGEX=${NAVI_ALEXA_RENDERER_NAME_REGEX:-}
      - NAVI_ALEXA_RENDERER_ONLY_ONLINE=${NAVI_ALEXA_RENDERER_ONLY_ONLINE:-no}
      - NAVI_ALEXA_RENDERER_ANNOUNCE=${NAVI_ALEXA_RENDERER_ANNOUNCE:-explicit}
      - NAVI_ALEXA_RENDERER_LOG_LEVEL=${NAVI_ALEXA_RENDERER_LOG_LEVEL:-INFO}
      - NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
      - NAVI_ALEXA_DOMAIN=${NAVI_ALEXA_DOMAIN:-amazon.com}
      - NAVI_ALEXA_SKILL_NAME=${NAVI_ALEXA_SKILL_NAME:-castnavidrome}
      - NAVI_ALEXA_LOCALE=${NAVI_ALEXA_LOCALE:-de-DE}
      - NAVI_AMAZON_USER=${NAVI_AMAZON_USER:-}
      - NAVI_AMAZON_PASS=${NAVI_AMAZON_PASS:-}
      - NAVI_AMAZON_TOTP_SECRET=${NAVI_AMAZON_TOTP_SECRET:-}
      - NAVI_AMAZON_SESSION_FILE=/var/lib/castnavidrome/amazon_session.json
      - NAVI_URL=${NAVI_URL}
      - NAVI_USER=${NAVI_USER}
      - NAVI_PASS=${NAVI_PASS}
      - NAVI_PORT=${NAVI_PORT:-443}
      - NAVI_API_PATH=/rest
      - NAVI_API_VER=1.16.1
    volumes:
      - ./.secrets/alexa.cookies:/run/secrets/alexa.cookies:ro
      - ./state:/var/lib/castnavidrome
    restart: unless-stopped
```

Die Cookie-Datei (`.secrets/alexa.cookies`) und das State-Verzeichnis (`state/`) sind nur lokal und werden über `.gitignore` von der Versionskontrolle ausgeschlossen.

### Option 2: Direkt mit Python ausführen

```bash
cd skill
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-full.txt

NAVI_SKILL_ID=<ihre-skill-id> \
NAVI_URL=https://ihr-navidrome.test \
NAVI_USER=<benutzername> \
NAVI_PASS=<passwort> \
NAVI_PORT=443 \
NAVI_API_PATH=/rest \
NAVI_API_VER=1.16.1 \
python3 app.py
```

Alle Umgebungsvariablen siehe [Konfiguration](#konfiguration).

## Alexa-Skill einrichten

1. Erstellen Sie einen Custom Skill in der [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Legen Sie als primäre Locale die Locale Ihres Echo-Geräts fest (muss übereinstimmen).
3. Laden Sie ein Interaktionsmodell aus [`alexa/`](alexa) unter *Interaction Model → JSON Editor* hoch (z. B. `alexa/de-DE.json`) und speichern Sie das Modell.
4. Fügen Sie Ihre Playlist-Namen dem Slot-Typ `playlist_names` hinzu.
5. Aktivieren Sie unter *Interfaces* das *Audio Player*-Interface.
6. Legen Sie den Endpunkt auf die HTTPS-URL dieses Webdieners (Standard-Region) fest und speichern Sie ihn.
7. Bauen Sie das Modell und fügen Sie den Skill Ihren Echo-Geräten als Entwicklungsskill hinzu.

Der Invocation-Name ist in allen Locales identisch und wird mit `NAVI_ALEXA_SKILL_NAME` festgelegt.

## Docker-Image bauen

```bash
docker build -t castnavidrome:local .
```

Multi-Architektur-Images lassen sich mit `docker buildx` erstellen (die Dockerfile zielt auf `alpine:3.22.1` ab). Das Image wird nicht automatisch veröffentlicht; bauen und pushen Sie es vor einem Release in Ihre eigene Registry.

## Konfiguration

Der Dienst liest seine Konfiguration aus Umgebungsvariablen.

### Erforderlich

| Variable | Beschreibung | Beispiel |
|---|---|---|
| `NAVI_SKILL_ID` | ID Ihres Alexa-Skills (schränkt den Webdienst auf Ihren Skill ein) | `amzn1.ask.skill.xxxxxxxx-…` |
| `NAVI_URL` | URL des Subsonic-API-Servers (`https://`, ohne abschließenden Schrägstrich) | `https://navidrome.example.test` |
| `NAVI_USER` | Navidrome-Benutzername | `bob` |
| `NAVI_PASS` | Navidrome-Passwort | — |
| `NAVI_PORT` | Port des Subsonic-API-Servers | `443` |
| `NAVI_API_PATH` | Subsonic-API-Pfad | `/rest` |
| `NAVI_API_VER` | Subsonic-API-Version | `1.16.1` |
| `NAVI_SONG_COUNT` | Minimale Liedanzahl für Zufalls-/Genre-/Künstler-Playlists | `50` |

### Optional

| Variable | Beschreibung | Beispiel |
|---|---|---|
| `NAVI_BASE_URL` | Öffentliche URL dieses Skills (wird für Cover-Art auf Alexa-Karten verwendet) | `https://castnavidrome.example.test` |
| `NAVI_DEBUG` | Debug-Level (0–3) | `0` |
| `NAVI_DEBUG_TOKEN` | Token zum Schutz der `/debug/*`-Endpunkte | — |
| `NAVI_ALEXA_API_KEY` | API-Key im Header `X-API-Key` für `/api/alexa/*` | `openssl rand -hex 32` |
| `NAVI_ALEXA_DOMAIN` | Amazon-Domain | `amazon.com` |
| `NAVI_ALEXA_LOCALE` | Locale der Skill-Antworten und Sprachbefehle | `de-DE` |
| `NAVI_ALEXA_SKILL_NAME` | Invocation-Name des Skills | `castnavidrome` |
| `NAVI_ALEXA_COOKIE_FILE` | Pfad zu einer Alexa-Cookie-Datei (Cookie-Fallback) | `/run/secrets/alexa.cookies` |
| `NAVI_AMAZON_USER` / `NAVI_AMAZON_PASS` / `NAVI_AMAZON_TOTP_SECRET` | Amazon-Login mit TOTP/2FA (ersetzt die Cookie-Datei) | — |
| `NAVI_AMAZON_SESSION_FILE` | Gespeicherte Amazon-Session-Cookies | `/var/lib/castnavidrome/amazon_session.json` |
| `NAVI_RADIO_URL` / `NAVI_RADIO_STATIONS_URL` | Radio-Stream-URLs | — |
| `NAVI_PLAYLIST_NAME_PATTERN` / `_SPOKEN_FORMAT` / `_QUALIFIED_FORMAT` | Playlist-Namen-Gruppierung und gesprochene Formate | — |

### Media-Renderer (`castnavidrome-renderer`)

| Variable | Beschreibung | Beispiel |
|---|---|---|
| `NAVI_ALEXA_RENDERER_ENABLED` | Renderer aktivieren | `yes` |
| `NAVI_ALEXA_RENDERER_PORT` | UPnP-Beschreibungs-/Steuerungsport | `49443` |
| `NAVI_ALEXA_RENDERER_ANNOUNCE` | Welche Titel angesagt werden: `explicit`, `always`, `never` | `explicit` |
| `NAVI_ALEXA_RENDERER_STATE_FILE` | Registry, die Alexa-Geräte auf Renderer-UUIDs abbildet | `/var/lib/castnavidrome/renderer-devices.json` |
| `NAVI_ALEXA_RENDERER_NAME_PREFIX` | Präfix für Renderer-Namen | — |
| `NAVI_ALEXA_RENDERER_DEVICE_TYPES` | Erlaubte Gerätetypen (kommagetrennt) | `ECHO,FIRE_TV` |
| `NAVI_ALEXA_RENDERER_NAME_REGEX` | Regex, dem Gerätenamen entsprechen muss | `^Echo` |
| `NAVI_ALEXA_RENDERER_ONLY_ONLINE` | Nur Online-Geräte anzeigen | `no` |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | Log-Level | `INFO` |

Die Ankündigungsmodi (`explicit` = Standard: vom Nutzer gestartete Titel werden angesagt, vom Renderer selbst gestartete Titel spielen still) siehe `CREDITS.md`.

## Änderungen gegenüber AskNavidrome

castNavidrome behält das Upstream-Verhalten von AskNavidrome bei und fügt hinzu:

- UPnP-MediaRenderer pro Alexa-Gerät (neuer Container/Prozess, Host-Netzwerk).
- Lokalisierung in sechs Sprachen mit sprachspezifischen Sprachbefehlen.
- Freitextsuche (`castNavidromePlaySearch`), Musik nach Jahrzehnt, Titel nach Name, Playlist-Entdeckung, Radio-Streams, Hilfethemen.
- Amazon-Login mit TOTP/2FA (`skill/castnavidrome/amazon_login.py`).
- Geschützte Debug-Endpunkte (`NAVI_DEBUG_TOKEN`) und keine Session-Token/Stream-URIs in Protokollen oder der Debug-Tabelle.

Jedes übernommene Feature und sein Ursprung sind in [CREDITS.md](CREDITS.md) mit den vorgenommenen lokalen Änderungen aufgelistet.

### TOTP-Geheimnis (Amazon Zwei-Schritt-Verifizierung)

Um den automatischen Amazon-Login-Flow statt der manuellen Cookie-Datei zu nutzen, muss Amazon während der Anmeldung einen TOTP-Code abfragen. Das `NAVI_AMAZON_TOTP_SECRET` erhältst du so:

1. Öffne die Amazon-Kontoeinstellungen für deine Domain (z. B. https://www.amazon.de/gp/css/account/security).
2. Gehe zu **Einstellungen für die Zwei-Schritt-Verifizierung (2SV)**.
3. Füge eine **Authenticator App** hinzu oder verwalte sie.
4. Amazon zeigt einen QR-Code und in der Regel eine Option, den Geheimschlüssel als Text anzuzeigen.
5. Kopiere diesen Base32-Schlüssel (Buchstaben und Ziffern, z. B. `JBSWY3DPEHPK3PXP`) und setze ihn als `NAVI_AMAZON_TOTP_SECRET`.

Der Skill berechnet den 6-stelligen Code selbst (RFC 6238, nur Standardbibliothek, keine `pyotp`-Abhängigkeit).

## Sicherheit
- Die Alexa-Cookie-Datei sowie `NAVI_AMAZON_PASS` / `NAVI_AMAZON_TOTP_SECRET` sind sensibel. Halten Sie `.secrets/` aus der Versionskontrolle heraus (steht in `.gitignore`) und binden Sie es schreibgeschützt ein.
- Stellen Sie die Endpunkte `/api/alexa/*` und `/debug/*` nicht ohne `NAVI_ALEXA_API_KEY` und HTTPS ins öffentliche Internet.

## Lizenz

MIT-Lizenz. Copyright (c) 2022 Ross Stewart; lokale Änderungen Copyright (c) 2026 castNavidrome-Mitwirkende. Siehe [LICENSE](LICENSE) und [CREDITS.md](CREDITS.md).

## Noch nicht veröffentlicht

Dieses Repository ist für die Veröffentlichung als Fork von AskNavidrome vorbereitet, wird aber **nicht veröffentlicht**. Alles ist bereit und wartet auf Ihre ausdrückliche Freigabe.

## Disclaimer

Dieses Projekt ist vibe gecoded: es wurde schnell mit KI-Unterstützung zusammengestellt und hat keine gründliche Sicherheits- oder Code-Prüfung durchlaufen. Betrachten Sie es als Ausgangspunkt, nicht als produktionsreife Software. Secrets und persönliche Daten sind über `.gitignore` von der Versionskontrolle ausgeschlossen, aber Sie sind selbst dafür verantwortlich, alles, was Sie ausführen, zu prüfen und zu validieren.
