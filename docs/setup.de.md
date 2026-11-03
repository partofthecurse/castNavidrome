# castNavidrome - Einrichtung (Wiki)

Dieses Wiki beschreibt Schritt für Schritt, wie du castNavidrome (ein Fork von AskNavidrome) aufsetzt, sodass du deine Navidrome-Mediathek per Alexa-Sprachbefehle steuern kannst.

---

## 1. Voraussetzungen

- Ein laufender [Navidrome](https://www.navidrome.org/)-Medienserver
- Ein Amazon-Alexa-Entwicklerkonto (https://developer.amazon.com/alexa/console/ask)
- Docker und Docker Compose auf dem Host
- Optional: Ein [Tailscale](https://tailscale.com/)-Konto (für den öffentlichen Zugriff ohne Port-Forwarding)

---

## 2. Repository klonen

```bash
git clone https://github.com/partofthecurse/castNavidrome.git
cd castNavidrome
```

---

## 3. Alexa Skill anlegen (Amazon Developer Console)

1. Gehe zur [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Klicke auf **Create Skill**.
3. Wähle einen Namen (z. B. `castNavidrome`), das Modell **Custom** und die Methode **Provision your own**.
4. Wähle die gewünschte Sprache (z. B. `German (DE)` oder `English (US)`).
5. Kopiere die **Skill ID** (sieht aus wie `amzn1.ask.skill.xxxx-xxxx-...`) — du brauchst sie als `NAVI_SKILL_ID`.
6. Füge unter **Interaction Model** die Intents und Slots hinzu (siehe `skill/alexa.json` im Repository für ein fertiges de-DE/en-US-Modell).
7. Unter **Endpoint** trägst du später deine öffentliche HTTPS-Endpunkt-URL ein (über Tailscale Funnel oder eigenen Reverse Proxy).
8. Speichere und baue das Modell.

**Wichtig:** Wenn du den stillen Auto-Advance nutzen willst (Weiter zum nächsten Track ohne Ansage), muss das Interaction Model den Intent `NaviSonicPlaySongByArtistQuiet` enthalten.

---

## 4. Konfigurationsdatei `.env` erstellen

```bash
cp .env.example .env
```

Öffne `.env` und fülle die Pflichtwerte aus:

```env
# ---- Service / Tailscale ----
SERVICE=castnavidrome
SERVICEPORT=5000

# TS_AUTHKEY=dein-tailscale-authschlüssel  # nur bei Tailscale nötig

# ---- Navidrome (Subsonic API) - erforderlich ----
NAVI_SKILL_ID=amzn1.ask.skill.00000000-0000-0000-0000-000000000000
NAVI_URL=https://dein-navidrome-server.test
NAVI_BASE_URL=https://castnavidrome.deine-domain.test
NAVI_USER=dein-navidrome-benutzername
NAVI_PASS=dein-navidrome-passwort

# ---- Alexa skill ----
NAVI_ALEXA_API_KEY=ein-zufalliger-schluessel-zum-schutz-des-api

# Amazon Cookie Capture (Browser-Login, empfohlen)
NAVI_ALEXA_CAPTURE_PASSWORD=dein-capture-ui-passwort
NAVI_AMAZON_USER=deine-amazon-email
NAVI_AMAZON_PASS=dein-amazon-passwort
NAVI_AMAZON_TOTP_SECRET=dein-totp-secret-base32
NAVI_ALEXA_DOMAIN=amazon.de

# Cookie-Datei-Fallback (optional)
# NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
```

### `NAVI_ALEXA_API_KEY` generieren

```bash
openssl rand -hex 32
```

Trage den Ausgabestring als `NAVI_ALEXA_API_KEY` in `.env` ein.

---

## 5. Amazon Cookie Capture (Browser-Login, empfohlen)

castNavidrome nutzt einen browserbasierten Cookie-Capture-Proxy (aufgebaut auf `alexapy`, derselben Bibliothek wie `alexa_media_player`), um eine gültige Alexa-Session zu erhalten. Du loggst dich über deinen normalen Webbrowser bei Amazon ein; der Proxy erfasst die Session-Cookies (inklusive des erforderlichen `csrf`-Cookies) und schreibt sie atomar in `NAVI_ALEXA_COOKIE_FILE`.

### Schritt 1: Umgebungsvariablen in `.env` setzen

```env
# Amazon Login (Browser Capture Proxy)
NAVI_ALEXA_CAPTURE_PASSWORD=dein-capture-ui-passwort
NAVI_AMAZON_USER=deine-amazon-email
NAVI_AMAZON_PASS=dein-amazon-passwort
NAVI_AMAZON_TOTP_SECRET=dein-totp-secret-base32
NAVI_ALEXA_DOMAIN=amazon.de
```

| Variable | Bedeutung |
|----------|-----------|
| `NAVI_ALEXA_CAPTURE_PASSWORD` | Passwort zum Schutz der Cookie-Capture-UI unter `/api/alexa/cookie/save` |
| `NAVI_AMAZON_USER` / `NAVI_AMAZON_PASS` | Optionale Amazon-Credentials; der Proxy füllt den Login-Formular automatisch aus (ein eventueller CAPTCHA/Verifizierungsschritt kann manuell absolviert werden) |
| `NAVI_AMAZON_TOTP_SECRET` | Optionales TOTP-Secret; der Proxy füllt den 2FA-Code automatisch aus |
| `NAVI_ALEXA_DOMAIN` | Amazon-Marktplatz, z. B. `amazon.de` (DE), `amazon.com` (US) |

### Schritt 2: Container starten und per Browser einloggen

1. Baue und starte die Container:

   ```bash
   docker compose up -d --build
   ```

2. Öffne die Cookie-Login-Seite im Browser (Basic Auth; der Benutzername ist beliebig, das Passwort ist `NAVI_ALEXA_CAPTURE_PASSWORD`):

   ```
   https://castnavidrome.deine-domain.test/api/alexa/cookie/save
   ```

3. Klicke auf der Seite auf die Proxy-URL, um die Amazon-Anmeldung im Capture-Proxy zu öffnen. Melde dich mit deinen Amazon-Anmeldeinformationen an (und TOTP, falls angefordert).

4. Nach erfolgreichem Login erfasst der Proxy automatisch die Session-Cookies, validiert sie (erfragt die Alexa-Domain, damit Amazon das `csrf`-Cookie setzt) und schreibt sie in die Cookie-Datei. Der Status-Endpunkt zeigt an, ob die Session gültig ist:

   ```bash
   curl -u :dein-capture-passwort https://castnavidrome.deine-domain.test/api/alexa/cookie/proxy/status
   ```

   Achte auf `"login_success": true` und `"has_csrf": true`.

5. Der Renderer-Container (`castnavidrome-renderer`) teilt sich dasselbe `./state`-Volume und übernimmt automatisch die Cookies aus `/var/lib/castnavidrome/alexa.cookies`.

### Startup-Check

Beim Start des Haupt-Containers wird geprüft, ob die Cookie-Datei eine gültige Alexa-Session enthält. Wenn nicht, erscheint eine Warnung im Log:

```
No valid Alexa session found. Open /api/alexa/cookie/save to capture cookies.
```

Das ist nach dem ersten Start normal — erfasse die Cookies über `/api/alexa/cookie/save`.

---

## 6. Alexa-Cookie-Datei (manueller Fallback)

1. Melde dich bei https://alexa.amazon.de (oder .com) im Browser an.
2. Exportiere das Session-Cookie (z. B. mit der Browser-Erweiterung "Export Cookies" oder über die Entwicklertools).
3. Speichere die Cookies als `.secrets/alexa.cookies` im Projektordner.
4. Setze `NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies` in `.env`.

> **Hinweis:** `.secrets/`, `.env` und die Token-Datei werden nicht ins Git-Repository committet (siehe `.gitignore`).

---

## 7. Docker Compose starten

```bash
docker compose up -d --build
```

Dies baut das Image und startet drei Container:

- `castnavidrome` — die Alexa-Skill-Weboberfläche (Flask)
- `castnavidrome-renderer` (optional) — stellt jedes Alexa-Gerät als UPnP-MediaRenderer bereit (benutzt Host-Netzwerk für SSDP)
- `tailscale` — optional, für sicheren externen Zugriff per Tailscale

### Nur den Skill starten (ohne Tailscale)

```bash
docker compose up -d --build castnavidrome
```

### Nur den Renderer starten

```bash
docker compose up -d --build castnavidrome-renderer
```

---

## 8. Tailscale einrichten (empfohlen für externen Zugriff)

1. Erstelle einen [Tailscale Auth Key](https://login.tailscale.com/admin/settings/keys) (Typ "ephemeral" oder "reusable").
2. Trage ihn in `.env` ein: `TS_AUTHKEY=tskey-auth-...`
3. Erstelle eine `config/serve.json`:

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

4. Starte `docker compose up -d`.
5. Aktiviere in der Tailscale Admin-Konsole **Funnel** für den castNavidrome-Knoten.
6. Trage die Funnel-URL als `NAVI_BASE_URL` in `.env` ein und gib sie im Alexa Skill als Endpoint an.

---

## 9. Alexa Skill Endpoint verknüpfen

1. Gehe in der Alexa Developer Console zu deinem Skill → **Endpoint**.
2. Wähle **HTTPS** und trage die öffentliche URL des castNavidrome-Servers ein, z. B.:

```
https://dein-knoten.ts.net:5000
```

oder mit Funnel:

```
https://abc123-def456.tail...  # deine Funnel-URL
```

3. Wähle als Zertifikat **My development endpoint is a sub-domain of a domain that has a wildcard certificate from a certificate authority**.
4. Speichere.

---

## 10. Skill testen

1. In der Alexa Developer Console: **Test** → Skill-Entwicklung aktivieren.
2. Sage zu einem Alexa-Gerät: „Alexa, öffne castNavidrome“ (oder dein gewählter Invocation-Name).
3. Probiere Befehle wie:
   - „spiele Musik von Queen“
   - „spiele das Album Abbey Road von den Beatles“
   - „spiele meine Lieblingslieder“
   - „spiele zufällige Musik“

**Tipp:** Wähle einen Invocation-Name, der keine Musikdienst-Namen enthält (z. B. nicht "Spotify" oder "Apple Music"), um Konflikte zu vermeiden.

---

## 11. Media Renderer (UPnP) — optional

1. Setze `NAVI_ALEXA_RENDERER_ENABLED=yes` (Standard).
2. Starte den `castnavidrome-renderer`-Container mit `network_mode: host`.
3. Der Renderer meldet sich per SSDP im Netzwerk und erscheint in UPnP-Clients als separates Gerät pro Alexa-Device.

| Variable | Standard | Bedeutung |
|---|---|---|
| `NAVI_ALEXA_RENDERER_PORT` | `49443` | Port für den Renderer |
| `NAVI_ALEXA_RENDERER_REFRESH_SECONDS` | `300` | Geräte-Refresh-Intervall |
| `NAVI_ALEXA_RENDERER_DISABLE_REFRESH` | `true` | Deaktiviert periodisches Geräte-Refresh (Standard: nur einmal bei Containerstart) |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | `INFO` | Log-Level |

---

## 12. Update auf eine neuere Version

```bash
docker compose pull
docker compose up -d
```

Oder:

```bash
docker compose up -d --build
```

Der State (Amazon-Session, Renderer-Devices) liegt in `./state` und bleibt bei Updates erhalten.

---

## 13. Fehlersuche

| Problem | Lösung |
|---|---|
| Skill antwortet nicht | Prüfe `NAVI_SKILL_ID` und den Endpoint in der Alexa Console |
| 401/403 bei Alexa | Cookie abgelaufen → `.secrets/alexa.cookies` neu erfassen unter `/api/alexa/cookie/save` |
| Renderer nicht gefunden | `network_mode: host` prüfen, Firewall für SSDP (1900/udp) öffnen |
| Tailscale verbindet nicht | `TS_AUTHKEY` prüfen, `/dev/net/tun` und `cap_add: net_admin` im Compose |
| Lieder werden nicht abgespielt | Navidrome-URL und Credentials in `.env` prüfen, `docker compose logs castnavidrome` |

Logs ansehen:

```bash
docker compose logs -f castnavidrome
docker compose logs -f castnavidrome-renderer
docker compose logs -f tailscale
```

---

## 14. Fertiges Docker Image

```bash
docker pull ghcr.io/partofthecurse/castnavidrome:latest
```

Oder eine spezifische Version:

```bash
docker pull ghcr.io/partofthecurse/castnavidrome:0.10.0
```

Alternativ baust du das Image lokal selbst:

```bash
docker build -t castnavidrome:local .
```

---

## 15. Lizenz & Credits

castNavidrome basiert auf [AskNavidrome](https://github.com/rosskouk/asknavidrome) von Ross Stewart (MIT-Lizenz). Siehe `LICENSE` und `CREDITS.md` für Details.
