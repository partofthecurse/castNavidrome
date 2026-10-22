# castNavidrome

Alexa skill that bridges Alexa devices to a Subsonic API compatible media server (for example Navidrome), so you can stream your own music collection to your Echo devices.

**castNavidrome is a fork of [AskNavidrome](https://github.com/rosskouk/asknavidrome)** (Ross Stewart, MIT License) with local extensions from several community forks plus a built-in UPnP MediaRenderer for every Alexa device. See [Fork of AskNavidrome](#fork-of-asknavidrome) and [CREDITS.md](CREDITS.md).

## Highlights

- Play music by artist, album, song, genre, playlist, decade, or free-text query.
- Shuffle the play queue, star/unstar songs, show details of the current track.
- Radio streams and playlist discovery ("play more playlists like this", "find a playlist").
- Help topics and spoken answers in the language of the Echo device.
- Optional UPnP MediaRenderer: every selected Alexa device appears as its own renderer in Navidrome, so DLNA clients (Symfonium, Supersonic, …) can send tracks to individual Echoes.
- Optional Amazon login with username, password and TOTP/2FA (replaces manual cookie copying).
- Runs directly with Python or in a Docker container (recommended).

## Languages

This README: English.
- [`README.de.md`](README.de.md) — Deutsch
- [`README.es.md`](README.es.md) — Español

Interaction models for the Alexa Developer Console are in [`alexa/`](alexa) for `de-DE`, `en-US`, `es-ES`, `fr-FR`, `it-IT`, `pt-BR`.

## Fork of AskNavidrome

castNavidrome is a fork of [rosskouk/asknavidrome](https://github.com/rosskouk/asknavidrome). The upstream features (Subsonic API access, Alexa skill handler, MediaQueue, scrobbling, multi-threading for large playlists) originate from Ross Stewart.

Additional features were adopted from community forks of AskNavidrome (all MIT licensed) and from local development. The exact origin of every feature, the author, the fork and the local changes are documented in [CREDITS.md](CREDITS.md).

Local features without an upstream template:

- `skill/castnavidrome/upnp/` — own UPnP MediaRenderer (SSDP, Description, SOAP, DIDL) per Alexa device.
- `skill/castnavidrome/renderer_host.py` — renderer host process, device filter, UUID persistence.
- `skill/castnavidrome/renderer_registry.py` — stable mapping Alexa device → UPnP UUID (`ownerId` + `serialNumber`).
- `skill/castnavidrome/alexa_device_filter.py` — device selection by type, name, regex and online status.
- `skill/castnavidrome/alexa_remote.py` — text commands to Echo devices, device list via the Amazon devices API.
- `skill/castnavidrome/localization.py` — localized skill responses and language-specific voice commands.
- `alexa/` — interaction models, one file per language.

The software is distributed under the [MIT License](LICENSE). The original copyright notice of Ross Stewart is preserved; local modifications are copyrighted by the castNavidrome contributors (see `CREDITS.md` and `LICENSE`).

## Requirements

- A digital music collection served by a Subsonic API compatible media server (tested with Navidrome).
- The media server must be reachable over HTTPS with a valid TLS certificate (Amazon requires this for streaming).
- An Amazon Echo device whose locale matches the skill locale.
- An Alexa skill created in the [Amazon Alexa Developer Console](https://developer.amazon.com/alexa/console/ask), with the Audio Player interface enabled and the HTTPS endpoint pointing to this web service.
- (Optional, for the media renderers) port `1900/udp` available for SSDP discovery and the container able to use the host network or a macvlan.

## Installation

### Option 1: Docker Compose (recommended)

1. Copy the example configuration:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and fill in your own values (Navidrome URL, user, password, skill ID, …).  
   `.env` is **not** committed to version control.
3. Start everything:
   ```bash
   docker compose up -d --build
   ```

Example `docker-compose.yml`:

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
      - NAVI_ALEXA_LOCALE=${NAVI_ALEXA_LOCALE:-en-US}
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

  # Optional: exposes every selected Alexa device as its own UPnP media renderer.
  # Requires the host network so SSDP (port 1900/udp) works for discovery.
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
      - NAVI_ALEXA_LOCALE=${NAVI_ALEXA_LOCALE:-en-US}
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

The cookie file (`.secrets/alexa.cookies`) and the state directory (`state/`) are local only and are excluded from version control via `.gitignore`.

### Option 2: Run directly with Python

```bash
cd skill
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-full.txt

NAVI_SKILL_ID=<your-skill-id> \
NAVI_URL=https://your-navidrome.test \
NAVI_USER=<username> \
NAVI_PASS=<password> \
NAVI_PORT=443 \
NAVI_API_PATH=/rest \
NAVI_API_VER=1.16.1 \
python3 app.py
```

See [Configuration](#configuration) for all environment variables.

## Alexa skill setup

1. Create a custom skill in the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Set the primary locale to the locale of your Echo device (this must match).
3. Upload one of the interaction models from [`alexa/`](alexa) into the *Interaction Model → JSON Editor* (for example `alexa/en-US.json`) and save the model.
4. Add your playlist names to the `playlist_names` slot type.
5. Enable the *Audio Player* interface under *Interfaces*.
6. Set the endpoint to the HTTPS URL of this web service (default region) and save.
7. Build the model and add the skill to your Echo devices as a development skill.

### Skill ID

The `NAVI_SKILL_ID` is the unique identifier of your Alexa skill. You find it in the [Amazon Alexa Developer Console](https://developer.amazon.com/alexa/console/ask):

1. Open your skill in the Developer Console.
2. Go to **Skill → Information** (or the **Usage** tab in some consoles).
3. Copy the **Skill ID** (looks like `amzn1.ask.skill.xxxxxxxx-…`).
4. Set it as `NAVI_SKILL_ID` in your `.env`.

If `NAVI_SKILL_ID` is not set, the web service responds to any skill request.

### External URL with Tailscale Funnel

For Alexa to reach your skill and for Navidrome to stream covers, both need a public HTTPS URL. You can create one with [Tailscale Funnel](https://tailscale.com/kb/1216/funnel) without opening ports on your router:

1. Install Tailscale on the host running castNavidrome and Navidrome.
2. Expose the castNavidrome web service:
   ```bash
   tailscale funnel on 443
   ```
   (or the port your container listens on, for example `8000`).
3. Expose Navidrome the same way if it is not already reachable from the internet:
   ```bash
   tailscale funnel on 443
   ```
4. Tailscale gives you a DNS name like `yourdevice.tailxxxxyyyy.ts.net`. Use it as:
   - `NAVI_URL` — the Navidrome server URL, for example `https://yourdevice.tailxxxxyyyy.ts.net`
   - `NAVI_BASE_URL` — the public URL of this skill, for example `https://yourdevice.tailxxxxyyyy.ts.net`
   - The HTTPS endpoint in the Alexa Developer Console, pointing to your castNavidrome service.

Tailscale Funnel terminates TLS at the Tailscale edge, so Alexa's HTTPS requirement is satisfied without you managing certificates.

The invocation name is the same in every locale and is set with `NAVI_ALEXA_SKILL_NAME`.

**Tip:** Choose an invocation name that has nothing to do with a music service (not "Spotify", "Apple Music", "Amazon Music", "Navidrome", …). Otherwise Alexa may try to route your request to another music skill instead of castNavidrome, and your own music collection will not be played.

## Docker image build

```bash
docker build -t castnavidrome:local .
```

Multi-architecture images can be built with `docker buildx` when required (the Dockerfile targets `alpine:3.22.1`). The image is not published automatically; build and push it to your own registry before releasing.

## Configuration

The service reads its configuration from environment variables.

### Required

| Variable | Description | Example |
|---|---|---|
| `NAVI_SKILL_ID` | ID of your Alexa skill (limits the web service to your skill) | `amzn1.ask.skill.xxxxxxxx-…` |
| `NAVI_URL` | URL of the Subsonic API server (`https://`, no trailing slash) | `https://navidrome.example.test` |
| `NAVI_USER` | Navidrome user name | `bob` |
| `NAVI_PASS` | Navidrome password | — |
| `NAVI_PORT` | Port of the Subsonic API server | `443` |
| `NAVI_API_PATH` | Subsonic API path | `/rest` |
| `NAVI_API_VER` | Subsonic API version | `1.16.1` |
| `NAVI_SONG_COUNT` | Minimum number of songs for random/genre/artist playlists | `50` |

### Optional

| Variable | Description | Example |
|---|---|---|
| `NAVI_BASE_URL` | Public URL of this skill (used for cover art on Alexa cards) | `https://castnavidrome.example.test` |
| `NAVI_DEBUG` | Debug level (0–3) | `0` |
| `NAVI_DEBUG_TOKEN` | Token protecting the `/debug/*` endpoints | — |
| `NAVI_ALEXA_API_KEY` | API key sent in `X-API-Key` for `/api/alexa/*`. Generate it yourself, for example with `openssl rand -hex 32`. | `openssl rand -hex 32` |
| `NAVI_ALEXA_DOMAIN` | Amazon domain | `amazon.com` |
| `NAVI_ALEXA_LOCALE` | Locale of the skill answers and voice commands | `en-US` |
| `NAVI_ALEXA_SKILL_NAME` | Invocation name of the skill | `castnavidrome` |
| `NAVI_ALEXA_COOKIE_FILE` | Path to an Alexa cookie file (cookie fallback) | `/run/secrets/alexa.cookies` |
| `NAVI_AMAZON_USER` / `NAVI_AMAZON_PASS` / `NAVI_AMAZON_TOTP_SECRET` | Amazon login with TOTP/2FA (replaces the cookie file) | — |
| `NAVI_AMAZON_SESSION_FILE` | Persisted Amazon session cookies | `/var/lib/castnavidrome/amazon_session.json` |
| `NAVI_RADIO_URL` / `NAVI_RADIO_STATIONS_URL` | Radio stream URLs | — |
| `NAVI_PLAYLIST_NAME_PATTERN` / `_SPOKEN_FORMAT` / `_QUALIFIED_FORMAT` | Playlist name grouping and spoken format | — |

### Media renderer (`castnavidrome-renderer`)

| Variable | Description | Example |
|---|---|---|
| `NAVI_ALEXA_RENDERER_ENABLED` | Enable the renderers | `yes` |
| `NAVI_ALEXA_RENDERER_PORT` | UPnP description/control port | `49443` |
| `NAVI_ALEXA_RENDERER_ANNOUNCE` | Which tracks are announced: `explicit`, `always`, `never` | `explicit` |
| `NAVI_ALEXA_RENDERER_STATE_FILE` | Registry mapping Alexa devices → renderer UUIDs | `/var/lib/castnavidrome/renderer-devices.json` |
| `NAVI_ALEXA_RENDERER_NAME_PREFIX` | Prefix for renderer names | — |
| `NAVI_ALEXA_RENDERER_DEVICE_TYPES` | Allowed device types (comma separated) | `ECHO,FIRE_TV` |
| `NAVI_ALEXA_RENDERER_NAME_REGEX` | Regex device names must match | `^Echo` |
| `NAVI_ALEXA_RENDERER_ONLY_ONLINE` | Expose only online devices | `no` |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | Log level | `INFO` |

See `CREDITS.md` for the announcement modes (`explicit` = default: user-started tracks are announced, renderer-started tracks play silently).

## Changes compared to AskNavidrome

castNavidrome keeps the upstream AskNavidrome behaviour intact and adds:

- UPnP MediaRenderer per Alexa device (new containers/process, host networking).
- Localization into six languages with language-specific voice commands.
- Free-text search (`castNavidromePlaySearch`), music by decade, song by title, playlist discovery, radio streams, help topics.
- Amazon login with TOTP/2FA (`skill/castnavidrome/amazon_login.py`).
- Protected debug endpoints (`NAVI_DEBUG_TOKEN`) and no session tokens / stream URIs in logs or the debug table.

Every adopted feature and its origin is listed in [CREDITS.md](CREDITS.md) with the local changes applied.

### TOTP secret (Amazon two-step verification)

To use the automatic Amazon login flow instead of the manual cookie file, Amazon has to ask for a TOTP code during sign-in. To obtain the `NAVI_AMAZON_TOTP_SECRET`:

1. Open the Amazon account settings for your domain (for example https://www.amazon.de/gp/css/account/security).
2. Go to **Two-Step Verification (2SV) Settings**.
3. Add or manage an **Authenticator App**.
4. Amazon shows a QR code and, typically, an option to reveal the secret key as text.
5. Copy that Base32 secret (letters and digits only, for example `JBSWY3DPEHPK3PXP`) and set it as `NAVI_AMAZON_TOTP_SECRET`.

The skill computes the 6-digit code itself (RFC 6238, standard library only, no `pyotp` dependency).

### Alexa Cookie File (manual fallback)

If you prefer not to use the automatic Amazon login (or it fails because of CAPTCHA or an extra verification step), you can provide an existing Alexa session cookie file instead.

1. Open your Amazon domain (for example https://www.amazon.de) in the browser and sign in.
2. Open the Developer Tools (F12), go to **Application → Cookies** and select your Amazon domain.
3. Copy the cookies as `name=value` pairs, one per line. Make sure the `csrf` cookie is included.
4. Save the file as `.secrets/alexa.cookies` (or any path you like) and set `NAVI_ALEXA_COOKIE_FILE` to that path.
5. Mount the file read-only into the container (see the `docker-compose.yml` example).

![Alexa cookie export](https://github.com/user-attachments/assets/bf641182-8e06-404d-9d8d-abb9341dbcf0)

## Security
- The Alexa cookie file and any `NAVI_AMAZON_PASS` / `NAVI_AMAZON_TOTP_SECRET` are sensitive. Keep `.secrets/` out of version control (it is in `.gitignore`) and mount it read-only.
- Do not expose the `/api/alexa/*` or `/debug/*` endpoints to the public internet without `NAVI_ALEXA_API_KEY` and HTTPS.

## License

MIT License. Copyright (c) 2022 Ross Stewart; local modifications copyright (c) 2026 castNavidrome contributors. See [LICENSE](LICENSE) and [CREDITS.md](CREDITS.md).

## Disclaimer

This project is vibe coded: it was assembled quickly with AI assistance and has not undergone a thorough security or code review. Treat it as a starting point, not production-ready software. Secrets and personal data are excluded from version control via `.gitignore`, but you are responsible for reviewing and validating anything you run.
