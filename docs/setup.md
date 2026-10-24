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

# Amazon login (choose one method)

# Option A: OAuth 2.0 / Login with Amazon (recommended, stable long-term)
# NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.00000000000000000000000000000000
# NAVI_AMAZON_CLIENT_SECRET=your-client-secret
# NAVI_AMAZON_REDIRECT_URI=https://castnavidrome.your-domain.test/api/alexa/amazon/callback
# NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
# NAVI_ALEXA_DOMAIN=amazon.de

# Option B: Cookie file (manual fallback)
# NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
```

### Generate `NAVI_ALEXA_API_KEY`

The API key protects the HTTP endpoint from unauthorized access. Generate a strong key:

```bash
openssl rand -hex 32
```

Paste the output as `NAVI_ALEXA_API_KEY` in `.env`.

---

## 5. Amazon OAuth 2.0 / Login with Amazon einrichten (empfohlen)

castNavidrome nutzt den offiziellen OAuth 2.0 Authorization Code Flow von Login with Amazon (LWA), um sich bei Amazon zu authentifizieren. Das ist die stabile, langfristige Methode, da Amazons klassische Anmeldeseite (`/ap/signin`) nicht mehr zuverlässig funktioniert.

### Schritt 1: Login with Amazon Security Profile anlegen

1. Öffne die [Login with Amazon Console](https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html).
2. Melde dich mit deinem Amazon-Entwicklerkonto an.
3. Klicke auf **Create a New Security Profile**.
4. Gib einen Namen ein (z. B. `castNavidrome`) und eine Beschreibung, dann klicke auf **Save**.
5. Kopiere die angezeigten Werte:
   - **Client ID** (beginnt mit `amzn1.application-oa2-client.`)
   - **Client Secret**

### Schritt 2: Redirect URI in der Amazon Developer Console registrieren

Damit Amazon den OAuth-Callback akzeptiert, muss die Redirect URI exakt im Security Profile hinterlegt sein:

1. Öffne dein Security Profile in der Login with Amazon Console → Reiter **Web Settings**.
2. Füge bei **Allowed Return URLs** folgenden Eintrag hinzu:

   ```
   https://deine-castnavidrome-domain.test/api/alexa/amazon/callback
   ```

   Ersetze `deine-castnavidrome-domain.test` durch deine öffentliche castNavidrome-Domain (z. B. `https://castnavidrome.drake-aldebaran.ts.net`).
3. Klicke auf **Save**.

> **Wichtig:** Die Redirect URI muss exakt mit `NAVI_AMAZON_REDIRECT_URI` in deiner `.env` übereinstimmen — auch ein eventueller Trailing Slash muss identisch sein.

### Schritt 3: Umgebungsvariablen in `.env` setzen

Trage die Werte aus Schritt 1 in deine `.env` ein:

```env
# Amazon OAuth (Login with Amazon)
NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.deine-client-id
NAVI_AMAZON_CLIENT_SECRET=dein-client-secret
NAVI_AMAZON_REDIRECT_URI=https://deine-castnavidrome-domain.test/api/alexa/amazon/callback
NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
```

Zusätzlich benötigst du `NAVI_ALEXA_DOMAIN`, um festzulegen, welcher Amazon-Marktplatz verwendet wird:

```env
# Amazon-Marktplatz für den Login
NAVI_ALEXA_DOMAIN=amazon.de
```

| Variable | Bedeutung |
|----------|-----------|
| `NAVI_AMAZON_CLIENT_ID` | Client ID aus dem LWA Security Profile |
| `NAVI_AMAZON_CLIENT_SECRET` | Client Secret aus dem LWA Security Profile |
| `NAVI_AMAZON_REDIRECT_URI` | Muss exakt unter „Allowed Return URLs“ in der Amazon Developer Console eingetragen sein |
| `NAVI_AMAZON_TOKEN_FILE` | Pfad, in dem die OAuth-Tokens gespeichert werden |
| `NAVI_ALEXA_DOMAIN` | Amazon-Marktplatz, z. B. `amazon.de` (DE), `amazon.com` (US) |

### Schritt 4: Container starten und OAuth-Token initialisieren

1. Baue und starte die Container:

   ```bash
   docker compose up -d --build
   ```

   Die OAuth-Variablen werden automatisch an beide Container (`castnavidrome` und `castnavidrome-renderer`) übergeben.

2. Rufe im Browser die Login-URL auf:

   ```
   https://deine-castnavidrome-domain.test/api/alexa/amazon/login
   ```

3. Melde dich mit deinem Amazon-Konto an und erteile castNavidrome die Berechtigung, auf deine Alexa-Geräte zuzugreifen.
4. Du wirst zurück zu castNavidrome geleitet, und die Zugangstoken werden in `amazon_oauth_token.json` gespeichert.
5. Ab jetzt funktioniert die Alexa API automatisch; abgelaufene Token werden im Hintergrund neu ausgestellt.

### Startup-Check

Beim Start des Haupt-Containers wird geprüft, ob gültige OAuth-Token vorliegen. Wenn nicht, erscheint eine Warnung im Log:

```
No valid Amazon OAuth tokens found. Open /api/alexa/amazon/login to authenticate before using the Alexa API.
```

Das ist nach dem ersten Start normal — erst die Token durch den Aufruf von `/api/alexa/amazon/login` erstellen.

---

## 6. Export Alexa cookies (Fallback für die Alexa Bridge)

Wenn der OAuth-Login nicht funktioniert (z. B. wegen CAPTCHA oder zusätzlicher Verifizierungsschritte), kann stattdessen eine statische Alexa-Cookie-Datei verwendet werden.

castNavidrome needs an Alexa cookie to communicate with Amazon's Alexa servers.

### Option A: Export the cookie from the browser

1. Log in to https://alexa.amazon.com (or .de) in your browser.
2. Export the session cookie (e.g. via the "Export Cookies" browser extension or DevTools).
3. Save the cookies as `.secrets/alexa.cookies` in the project folder.

### Option B: OAuth 2.0 / Login with Amazon (recommended)

This is the stable, long-term login method. Amazon's regular sign-in page (`/ap/signin`) no longer works reliably, so castNavidrome uses the official OAuth 2.0 Authorization Code flow instead — the same way Home Assistant Skills do.

1. Go to the [Login with Amazon console](https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html) and create a security profile.
2. Note the **Client ID** and **Client Secret**.
3. Add them to `.env`:
   ```env
   NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.xxxxx
   NAVI_AMAZON_CLIENT_SECRET=your-client-secret
   NAVI_AMAZON_REDIRECT_URI=https://castnavidrome.your-domain.test/api/alexa/amazon/callback
   NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
   NAVI_ALEXA_DOMAIN=amazon.de
   ```
   Replace `https://castnavidrome.your-domain.test` with the public URL of your castNavidrome instance.
4. Start the container:
   ```bash
   docker compose up -d --build castnavidrome
   ```
5. Open in your browser:
   ```
   https://castnavidrome.your-domain.test/api/alexa/amazon/login
   ```
6. Sign in with your Amazon account and grant castNavidrome access to your Alexa devices.
7. You are redirected back to castNavidrome, and the access/refresh tokens are saved to `amazon_oauth_token.json`. From now on the Alexa API works automatically; expired tokens are refreshed in the background.

If something goes wrong, you can still fall back to Option A (cookie file).

> **Note:** `.secrets/`, `.env`, and the token file are not committed to Git (see `.gitignore`).

---

## 6. Start Docker Compose

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

## 7. Set up Tailscale (recommended for external access)

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

## 8. Link the Alexa skill endpoint

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

## 9. Test the skill

1. In the Alexa Developer Console: **Test** → enable skill development.
2. Say to an Alexa device: "Alexa, open castNavidrome" (or your chosen invocation name).
3. Try commands like:
   - "play music by Queen"
   - "play the album Abbey Road by the Beatles"
   - "play my favourite songs"
   - "play random music"

**Tip:** Choose an invocation name that is not a music service name (e.g. not "Spotify" or "Apple Music") to avoid conflicts.

---

## 10. Media renderer (UPnP) — optional

If you want to use castNavidrome as a UPnP media renderer (e.g. for Symfonium or other UPnP clients):

1. Set `NAVI_ALEXA_RENDERER_ENABLED=yes` (default).
2. Start the `castnavidrome-renderer` container with `network_mode: host`.
3. The renderer announces itself via SSDP on the network and appears in UPnP clients as a separate device per Alexa device.

Configurable renderer options (all optional, in `.env`):

| Variable | Default | Meaning |
|---|---|---|
| `NAVI_ALEXA_RENDERER_PORT` | `49443` | Renderer port |
| `NAVI_ALEXA_RENDERER_REFRESH_SECONDS` | `300` | Device refresh interval |
| `NAVI_ALEXA_RENDERER_NAME_PREFIX` | `""` | Prefix for device names |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | `INFO` | Log level |

---

## 11. Update to a new version

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

## 12. Troubleshooting

| Problem | Solution |
|---|---|
| Skill does not respond | Check `NAVI_SKILL_ID` and the endpoint in the Alexa Console |
| 401/403 with Alexa | Cookie expired → re-export `.secrets/alexa.cookies` or re-run OAuth login at `/api/alexa/amazon/login` |
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

## 13. Pre-built Docker image

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

## 14. License & credits

castNavidrome is based on [AskNavidrome](https://github.com/rosskouk/asknavidrome) by Ross Stewart (MIT license). See `LICENSE` and `CREDITS.md` for details.
