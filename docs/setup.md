# castNavidrome - Setup (Wiki)

This wiki describes step by step how to set up castNavidrome (a fork of AskNavidrome) so you can control your Navidrome media library via Alexa voice commands.

---

## 1. Prerequisites

- A running [Navidrome](https://www.navidrome.org/) media server
- An Amazon Alexa developer account (https://developer.amazon.com/alexa/console/ask)
- Docker and Docker Compose on the host
- Optional: A [Tailscale](https://tailscale.com/) account (for public access without port forwarding)

---

## 2. Clone the repository

```bash
git clone https://github.com/partofthecurse/castNavidrome.git
cd castNavidrome
```

---

## 3. Create the Alexa skill (Amazon Developer Console)

1. Go to the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Click **Create Skill**.
3. Choose a name (e.g. `castNavidrome`), the **Custom** model, and **Provision your own** as the method.
4. Choose the desired language (e.g. `German (DE)` or `English (US)`).
5. Copy the **Skill ID** (looks like `amzn1.ask.skill.xxxx-xxxx-...`) — you need it as `NAVI_SKILL_ID`.
6. Add the intents and slots under **Interaction Model** (see `skill/alexa.json` in the repository for a ready-made de-DE/en-US model).
7. Under **Endpoint**, you will later enter your public HTTPS endpoint URL (via Tailscale Funnel or your own reverse proxy).
8. Save and build the model.

**Important:** To use the silent auto-advance (continue to the next track without spoken confirmation), the Interaction Model must contain the intent `NaviSonicPlaySongByArtistQuiet`.

---

## 4. Create the `.env` configuration file

Copy the example file and adjust the values:

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
# ---- Service / Tailscale ----
SERVICE=castnavidrome
SERVICEPORT=5000

# TS_AUTHKEY=your-tailscale-auth-key  # only needed for Tailscale

# ---- Navidrome (Subsonic API) - required ----
NAVI_SKILL_ID=amzn1.ask.skill.00000000-0000-0000-0000-000000000000
NAVI_URL=https://your-navidrome-server.test
NAVI_BASE_URL=https://castnavidrome.your-domain.test
NAVI_USER=your-navidrome-username
NAVI_PASS=your-navidrome-password

# ---- Alexa skill ----
NAVI_ALEXA_API_KEY=a-random-secret-to-protect-the-api

# Amazon cookie capture (browser login, recommended)
NAVI_ALEXA_CAPTURE_PASSWORD=your-capture-ui-password
NAVI_AMAZON_USER=your-amazon-email
NAVI_AMAZON_PASS=your-amazon-password
NAVI_AMAZON_TOTP_SECRET=your-totp-secret-base32
NAVI_ALEXA_DOMAIN=amazon.de

# Cookie file fallback (optional)
# NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
```

### Generate `NAVI_ALEXA_API_KEY`

The API key protects the HTTP endpoint from unauthorized access. Generate a strong key:

```bash
openssl rand -hex 32
```

Paste the output as `NAVI_ALEXA_API_KEY` in `.env`.

---

## 5. Amazon cookie capture (browser login, recommended)

castNavidrome uses a browser-based cookie capture proxy (built on `alexapy`, the same library as `alexa_media_player`) to obtain a valid Alexa session. You log in to Amazon through your normal web browser; the proxy captures the session cookies (including the required `csrf` cookie) and writes them atomically to `NAVI_ALEXA_COOKIE_FILE`.

### Step 1: Set the environment variables in `.env`

```env
# Amazon login (browser capture proxy)
NAVI_ALEXA_CAPTURE_PASSWORD=your-capture-ui-password
NAVI_AMAZON_USER=your-amazon-email
NAVI_AMAZON_PASS=your-amazon-password
NAVI_AMAZON_TOTP_SECRET=your-totp-secret-base32
NAVI_ALEXA_DOMAIN=amazon.de
```

| Variable | Meaning |
|----------|---------|
| `NAVI_ALEXA_CAPTURE_PASSWORD` | Password protecting the cookie capture UI at `/api/alexa/cookie/save` |
| `NAVI_AMAZON_USER` / `NAVI_AMAZON_PASS` | Optional Amazon credentials; the proxy pre-fills the login form (you can still complete any CAPTCHA/verification step manually) |
| `NAVI_AMAZON_TOTP_SECRET` | Optional TOTP secret; the proxy auto-fills the 2FA code |
| `NAVI_ALEXA_DOMAIN` | Amazon marketplace, e.g. `amazon.de` (DE), `amazon.com` (US) |

### Step 2: Start the container and log in through the browser

1. Build and start the containers:

   ```bash
   docker compose up -d --build
   ```

2. Open the cookie login page in your browser (Basic Auth; the username can be anything, the password is `NAVI_ALEXA_CAPTURE_PASSWORD`):

   ```
   https://castnavidrome.your-domain.test/api/alexa/cookie/save
   ```

3. Click the proxy URL shown on the page to open the Amazon sign-in in the capture proxy. Log in with your Amazon credentials (and TOTP if prompted).

4. After a successful login, the proxy automatically captures the session cookies, validates them (it requests the Alexa domain so Amazon sets the `csrf` cookie) and writes them to the cookie file. The status endpoint shows whether the session is valid:

   ```bash
   curl -u :your-capture-password https://castnavidrome.your-domain.test/api/alexa/cookie/proxy/status
   ```

   Look for `"login_success": true` and `"has_csrf": true`.

5. The renderer container (`castnavidrome-renderer`) shares the same `./state` volume and automatically picks up the cookies from `/var/lib/castnavidrome/alexa.cookies`.

### Startup check

When the main container starts it checks whether the cookie file contains a valid Alexa session. If not, a warning appears in the log:

```
No valid Alexa session found. Open /api/alexa/cookie/save to capture cookies.
```

This is normal after the first start — capture the cookies by calling `/api/alexa/cookie/save`.

---

## 6. Alexa cookie file (manual fallback)

If the browser capture does not work (e.g. due to a CAPTCHA or an additional verification step that the proxy cannot complete), you can provide an existing Alexa session cookie file instead.

1. Log in to your Amazon domain (for example https://www.amazon.de) in the browser.
2. Open the Developer Tools (F12), go to **Application → Cookies** and select your Amazon domain.
3. Copy the cookies as `name=value` pairs, one per line. Make sure the `csrf` cookie is included.
4. Save the file as `.secrets/alexa.cookies` (or any path you like) and set `NAVI_ALEXA_COOKIE_FILE` to that path.
5. Mount the file read-only in the container (see the `docker-compose.yml` example).

> **Note:** `.secrets/`, `.env`, and the cookie/token files are not committed to Git (see `.gitignore`).

---

## 7. Start Docker Compose

```bash
docker compose up -d --build
```

This builds the image and starts three containers:

- `castnavidrome` — the Alexa skill web service (Flask)
- `castnavidrome-renderer` (optional) — exposes each Alexa device as its own UPnP media renderer (uses host network for SSDP)
- `tailscale` — optional, for secure external access via Tailscale

### Start only the skill (without Tailscale)

```bash
docker compose up -d --build castnavidrome
```

### Start only the renderer

```bash
docker compose up -d --build castnavidrome-renderer
```

---

## 8. Set up Tailscale (recommended for external access)

Tailscale lets you reach the skill without port forwarding in your router, via a stable HTTPS URL.

1. Create a [Tailscale Auth Key](https://login.tailscale.com/admin/settings/keys) (type "ephemeral" or "reusable").
2. Add it to `.env`: `TS_AUTHKEY=tskey-auth-...`
3. Create a `config/serve.json` for the Tailscale web server:

```json
{
  "http": [
    {
      "port": 5000,
      "protocol": "http",
      "accept": "100.64.0.0/10"
    }
  ]
}
```

4. Start `docker compose up -d`.
5. In the Tailscale admin console, enable **Funnel** for the castNavidrome node so it is reachable publicly over HTTPS.
6. Enter the Funnel URL as `NAVI_BASE_URL` in `.env` and specify it as the endpoint in the Alexa skill.

### Tailscale sidecar approach

Alternatively, Tailscale can run as a sidecar container next to castNavidrome (already included in `docker-compose.yml`). The `tailscale/tailscale:latest` image provides the VPN; castNavidrome reaches it via `http://tailscale-castnavidrome:41234`.

---

## 9. Link the Alexa skill endpoint

1. In the Alexa Developer Console, go to your skill → **Endpoint**.
2. Select **HTTPS** and enter the public URL of the castNavidrome server, e.g.:

```
https://your-node.ts.net:5000
```

or with Funnel:

```
https://abc123-def456.tail...  # your Funnel URL
```

3. Select **My development endpoint is a sub-domain of a domain that has a wildcard certificate from a certificate authority** (with Tailscale Funnel, the certificate is already valid).
4. Save.

---

## 10. Test the skill

1. In the Alexa Developer Console: **Test** → enable skill development.
2. Say to an Alexa device: "Alexa, open castNavidrome" (or your chosen invocation name).
3. Try commands like:
   - "play music by Queen"
   - "play the album Abbey Road by the Beatles"
   - "play my favourite songs"
   - "play random music"

**Tip:** Choose an invocation name that is not a music service name (e.g. not "Spotify" or "Apple Music") to avoid conflicts.

---

## 11. Media renderer (UPnP) — optional

If you want to use castNavidrome as a UPnP media renderer (e.g. for Symfonium or other UPnP clients):

1. Set `NAVI_ALEXA_RENDERER_ENABLED=yes` (default).
2. Start the `castnavidrome-renderer` container with `network_mode: host`.
3. The renderer announces itself via SSDP on the network and appears in UPnP clients as a separate device per Alexa device.

Configurable renderer options (all optional, in `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `NAVI_ALEXA_RENDERER_PORT` | `49443` | Renderer port |
| `NAVI_ALEXA_RENDERER_REFRESH_SECONDS` | `300` | Device refresh interval |
| `NAVI_ALEXA_RENDERER_DISABLE_REFRESH` | `true` | Disable periodic device refresh (default: only once at container start) |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | `INFO` | Log level |

---

## 12. Update to a new version

```bash
docker compose pull
docker compose up -d
```

Or, if you build the image yourself:

```bash
docker compose up -d --build
```

The state (Amazon session, renderer devices) is in `./state` and is preserved across updates.

---

## 13. Troubleshooting

| Problem | Solution |
|---|---|
| Skill does not respond | Check `NAVI_SKILL_ID` and the endpoint in the Alexa Console |
| 401/403 with Alexa | Cookie expired → re-capture `.secrets/alexa.cookies` at `/api/alexa/cookie/save` |
| Renderer not found | Check `network_mode: host`, open firewall for SSDP (1900/udp) |
| Tailscale does not connect | Check `TS_AUTHKEY`, `/dev/net/tun` and `cap_add: net_admin` in Compose |
| Songs do not play | Check Navidrome URL and credentials in `.env`, `docker compose logs castnavidrome` |

View logs:

```bash
docker compose logs -f castnavidrome
docker compose logs -f castnavidrome-renderer
docker compose logs -f tailscale
```

---

## 14. Pre-built Docker image

A pre-built image is published to [GitHub Container Registry (GHCR)](https://github.com/partofthecurse/castNavidrome/pkgs/container/castnavidrome) on every release:

```bash
docker pull ghcr.io/partofthecurse/castnavidrome:latest
```

Or a specific version:

```bash
docker pull ghcr.io/partofthecurse/castnavidrome:0.10.0
```

Alternatively, build the image locally:

```bash
docker build -t castnavidrome:local .
```

---

## 15. License & credits

castNavidrome is based on [AskNavidrome](https://github.com/rosskouk/asknavidrome) by Ross Stewart (MIT license). See `LICENSE` and `CREDITS.md` for details.
