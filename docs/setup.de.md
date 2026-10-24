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
3. Wähle einen Namen (z. B. `castNavidrome`), das Standard-Modell **Custom** und die Methode **Provision your own**.
4. Wähle als Sprache die gewünschte Sprache (z. B. `Deutsch (DE)` oder `English (US)`).
5. Kopiere den **Skill ID** (sieht aus wie `amzn1.ask.skill.xxxx-xxxx-...`) — du brauchst ihn als `NAVI_SKILL_ID`.
6. Füge unter **Interaction Model** die Intents und Slots hinzu (siehe `skill/alexa.json` im Repository für ein fertiges de-DE/en-US-Modell).
7. Unter **Endpoint** wählst du später deine HTTPS-Endpunkt-URL (über Tailscale Funnel oder eigenen Reverse Proxy).
8. Speichere und baue das Modell.

**Wichtig:** Wenn du den stillen Auto-Advance (Weiter zum nächsten Track ohne Ansage) nutzen willst, muss das Interaction Model den Intent `NaviSonicPlaySongByArtistQuiet` enthalten.

---

## 4. Konfigurationsdatei `.env` erstellen

Kopiere die Beispiel-Datei und passe die Werte an:

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

# Amazon login (eine Methode auswählen)

# Option A: OAuth 2.0 / Login with Amazon (empfohlen, langfristig stabil)
# NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.00000000000000000000000000000000
# NAVI_AMAZON_CLIENT_SECRET=Ihr-Client-Secret
# NAVI_AMAZON_REDIRECT_URI=https://castnavidrome.ihr-domain.test/api/alexa/amazon/callback
# NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
# NAVI_ALEXA_DOMAIN=amazon.de

# Option B: Cookie-Datei (manueller Fallback)
# NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
```

### NAVI_ALEXA_API_KEY generieren

Der API Key schützt den HTTP-Endpoint vor unbefugtem Zugriff. Erzeugen Sie einen starken Schlüssel:

```bash
openssl rand -hex 32
```

Tragen Sie den Ausgabe-String als `NAVI_ALEXA_API_KEY` in `.env` ein.

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

## 6. Alexa-Cookies exportieren (Fallback)

castNavidrome benötigt ein Alexa-Cookie, um mit den Amazon-Alexa-Servern zu kommunizieren.

### Option A: Cookie aus dem Browser exportieren

1. Melde dich bei https://alexa.amazon.de (oder .com) im Browser an.
2. Exportiere das Session-Cookie (z. B. mit der Browser-Erweiterung "Export Cookies" oder über die Entwicklertools).
3. Speichere die Cookies als `.secrets/alexa.cookies` im Projektordner.

### Option B: TOTP-Fluss (automatisch)

Wenn `NAVI_AMAZON_USER`, `NAVI_AMAZON_PASS` und `NAVI_AMAZON_TOTP_SECRET` in `.env` gesetzt sind, meldet sich castNavidrome automatisch bei Amazon ab und holt ein frisches Cookie — kein manuelles Kopieren nötig.

### Option C: OAuth 2.0 / Login with Amazon (empfohlen)

Das ist die stabilen, langfristige Anmeldemethode. Die normale Amazon-Anmeldeseite (`/ap/signin`) funktioniert nicht mehr zuverlässig, deshalb nutzt castNavidrome den offiziellen OAuth-Fluss — genauso wie die Home Assistant Skills.

1. Gehen Sie zur [Login with Amazon Console](https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html) und legen Sie ein Sicherheitsprofil an.
2. Notieren Sie sich die **Client ID** und den **Client Secret**.
3. Tragen Sie beides in `.env` ein:
   ```env
   NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.xxxxx
   NAVI_AMAZON_CLIENT_SECRET=Ihr-Client-Secret
   NAVI_AMAZON_REDIRECT_URI=https://castnavidrome.ihr-domain.test/api/alexa/amazon/callback
   ```
   Ersetzen Sie `https://castnavidrome.ihr-domain.test` durch die öffentliche URL Ihrer castNavidrome-Instanz.
4. Starten Sie den Container neu:
   ```bash
   docker compose up -d --build castnavidrome
   ```
5. Öffnen Sie im Browser:
   ```
   https://castnavidrome.ihr-domain.test/api/alexa/amazon/login
   ```
6. Melden Sie sich mit Ihrem Amazon-Konto an und erlauben Sie castNavidrome den Zugriff auf Ihre Alexa-Geräte.
7. Sie werden zurück zu castNavidrome weitergeleitet, und die Zugriffs- und Refresh-Token werden in `amazon_oauth_token.json` gespeichert. Ab sofort funktioniert die Alexa-API automatisch; abgelaufene Token werden im Hintergrund erneuert.

Falls etwas nicht funktioniert, können Sie weiterhin auf Option A (Cookie-Datei) oder Option B (TOTP) ausweichen.

> **Hinweis:** `.secrets/`, `.env` und die Token-Datei werden nicht ins Git-Repository committet (siehe `.gitignore`).

---

## 6. Docker Compose starten

```bash
docker compose up -d --build
```

Das baut das Image und startet drei Container:

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

## 7. Tailscale einrichten (empfohlen für externen Zugriff)

Tailscale ermöglicht es, den Skill ohne Port-Forwarding im Router über eine stabile HTTPS-URL erreichbar zu machen.

1. Erstelle einen [Tailscale Auth Key](https://login.tailscale.com/admin/settings/keys) (typ "ephemeral" oder "reusable").
2. Trage ihn in `.env` ein: `TS_AUTHKEY=tskey-auth-...`
3. Erstelle eine `config/serve.json` für den Tailscale-Webserver:

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
5. In der Tailscale Admin-Konsole aktiviere **Funnel** für den castNavidrome-Knoten, sodass die Tailscale-IP öffentlich über HTTPS erreichbar ist.
6. Trage die Funnel-URL als `NAVI_BASE_URL` in `.env` ein und gib sie im Alexa Skill als Endpoint an.

### Tailscale Sidecar-Ansatz

Alternativ kann Tailscale als Sidecar-Container neben castNavidrome laufen (bereits in der `docker-compose.yml` enthalten). Die `tailscale/tailscale:latest`-Image stellt das VPN bereit, castNavidrome erreicht es über `http://tailscale-castnavidrome:41234`.

---

## 8. Alexa Skill Endpoint verknüpfen

1. Gehe in der Alexa Developer Console zu deinem Skill → **Endpoint**.
2. Wähle **HTTPS** und trage die öffentliche URL des castNavidrome-Servers ein, z. B.:

```
https://dein-knoten.ts.net:5000
```

oder mit Funnel:

```
https://abc123-def456.tail...  # deine Funnel-URL
```

3. Wähle als Zertifikat **My development endpoint is a sub-domain of a domain that has a wildcard certificate from a certificate authority** (wenn du Tailscale Funnel nutzt, ist das Zertifikat bereits gültig).
4. Speichere.

---

## 9. Skill testen

1. In der Alexa Developer Console: **Test** → Skill-Entwicklung aktivieren.
2. Sage zu einem Alexa-Gerät: „Alexa, öffne castNavidrome“ (oder dein gewählter Invocation-Name).
3. Probiere Befehle wie:
   - „spiele Musik von Queen“
   - „spiele das Album Abbey Road von den Beatles“
   - „spiele meine Lieblingslieder“
   - „spiele zufällige Musik“

**Tipp:** Wähle einen Invocation-Name, der keine Musikdienst-Namen enthält (z. B. nicht "Spotify" oder "Apple Music"), um Konflikte zu vermeiden.

---

## 10. Media Renderer (UPnP) aktivieren (optional)

Wenn du castNavidrome als UPnP-MediaRenderer nutzen möchtest (z. B. für Symfonium oder andere UPnP-Clients):

1. Setze `NAVI_ALEXA_RENDERER_ENABLED=yes` (Standard).
2. Starte den `castnavidrome-renderer`-Container mit `network_mode: host`.
3. Der Renderer meldet sich per SSDP im Netzwerk und erscheint in UPnP-Clients als separates Gerät pro Alexa-Device.

Konfigurierbare Renderer-Optionen (alle optional, in `.env`):

| Variable | Standard | Bedeutung |
|---|---|---|
| `NAVI_ALEXA_RENDERER_PORT` | `49443` | Port für den Renderer |
| `NAVI_ALEXA_RENDERER_REFRESH_SECONDS` | `300` | Geräte-Refresh-Intervall |
| `NAVI_ALEXA_RENDERER_NAME_PREFIX` | `""` | Präfix für Gerätenamen |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | `INFO` | Log-Level |

---

## 11. Update auf eine neuere Version

```bash
docker compose pull
docker compose up -d
```

Oder, wenn du das Image selbst baust:

```bash
docker compose up -d --build
```

Der State (Amazon-Session, Renderer-Devices) liegt in `./state` und bleibt bei Updates erhalten.

---

## 12. Fehlersuche

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

## 13. Fertiges Docker Image

Ein vorgebautes Image wird bei jedem Release auf [GitHub Container Registry (GHCR)](https://github.com/partofthecurse/castNavidrome/pkgs/container/castnavidrome) bereitgestellt:

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

## 14. Lizenz & Credits

castNavidrome basiert auf [AskNavidrome](https://github.com/rosskouk/asknavidrome) von Ross Stewart (MIT-Lizenz). Siehe `LICENSE` und `CREDITS.md` für Details.
