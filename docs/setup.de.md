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

# Amazon-Login (Login with Amazon / OAuth 2.0, empfohlen)
NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.00000000000000000000000000000000
NAVI_AMAZON_CLIENT_SECRET=dein-client-secret
NAVI_AMAZON_REDIRECT_URI=https://castnavidrome.deine-domain.test/api/alexa/amazon/callback
NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
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

## 5. Login with Amazon (OAuth 2.0) — empfohlen

castNavidrome nutzt den offiziellen OAuth 2.0 Authorization Code Flow von Login with Amazon (LWA). Das ist die stabile, langfristige Methode, da Amazons klassische Anmeldeseite (`/ap/signin`) nicht mehr zuverlässig funktioniert.

### Schritt 1: Login with Amazon Security Profile anlegen

1. Öffne die [Login with Amazon Console](https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html).
2. Melde dich mit deinem Amazon-Entwicklerkonto an.
3. Klicke auf **Create a New Security Profile**.
4. Gib einen Namen ein (z. B. `castNavidrome`) und eine Beschreibung, dann klicke auf **Save**.
5. Kopiere die angezeigten Werte:
   - **Client ID** (beginnt mit `amzn1.application-oa2-client.`)
   - **Client Secret**

### Schritt 2: Redirect URI und Allowed Origin registrieren

Damit Amazon den OAuth-Callback akzeptiert, muss die Redirect URI exakt im Security Profile hinterlegt sein:

1. Öffne dein Security Profile in der Login with Amazon Console → Reiter **Web Settings**.
2. Unter **Allowed Origins** füge deine öffentliche castNavidrome-Origin hinzu, z. B.:

   ```
   https://castnavidrome.deine-domain.test
   ```

3. Unter **Allowed Return URLs** füge hinzu:

   ```
   https://castnavidrome.deine-domain.test/api/alexa/amazon/callback
   ```

   Ersetze `castnavidrome.deine-domain.test` durch deine öffentliche castNavidrome-Domain (z. B. `https://castnavidrome.drake-aldebaran.ts.net`).
4. Klicke auf **Save**.

> **Wichtig:** Die Redirect URI muss exakt mit `NAVI_AMAZON_REDIRECT_URI` in deiner `.env` übereinstimmen — auch ein eventueller Trailing Slash muss identisch sein.

### Schritt 3: Umgebungsvariablen in `.env` setzen

Trage die Werte aus Schritt 1 in `.env` ein (siehe Abschnitt 4).

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

2. Rufe im Browser die Login-URL auf:

   ```
   https://castnavidrome.deine-domain.test/api/alexa/amazon/login
   ```

3. Melde dich mit deinem Amazon-Konto an und erteile castNavidrome die Berechtigung, auf deine Alexa-Geräte zuzugreifen.
4. Du wirst zurück zu castNavidrome geleitet, und die Zugangstoken werden in `amazon_oauth_token.json` gespeichert.
5. Ab jetzt funktioniert die Alexa API automatisch; abgelaufene Token werden im Hintergrund neu ausgestellt.

### Startup-Check

Beim Start des Haupt-Containers wird geprüft, ob gültige OAuth-Token vorliegen. Wenn nicht, erscheint eine Warnung im Log:

```
No valid Amazon OAuth tokens found. Open /api/alexa/amazon/login to authenticate before using the Alexa API.
```

Das ist nach dem ersten Start normal — erstelle die Token durch den Aufruf von `/api/alexa/amazon/login`.

---

## 6. Cookie-Datei-Fallback (optional)

Falls der OAuth-Login nicht funktioniert (z. B. wegen CAPTCHA oder zusätzlicher Verifizierungsschritte), kann eine statische Alexa-Cookie-Datei verwendet werden.

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
| 401/403 bei Alexa | Cookie abgelaufen → `.secrets/alexa.cookies` neu exportieren oder OAuth-Login unter `/api/alexa/amazon/login` neu durchführen |
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
