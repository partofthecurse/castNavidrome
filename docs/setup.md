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

# Amazon login (optional, ersetzt die Cookie-Datei)
# NAVI_AMAZON_USER=
# NAVI_AMAZON_PASS=
# NAVI_AMAZON_TOTP_SECRET=
```

### NAVI_ALEXA_API_KEY generieren

Der API Key schützt den HTTP-Endpoint vor unbefugtem Zugriff. Erzeugen Sie einen starken Schlüssel:

```bash
openssl rand -hex 32
```

Tragen Sie den Ausgabe-String als `NAVI_ALEXA_API_KEY` in `.env` ein.

---

## 5. Alexa-Cookies exportieren (erforderlich für Alexa-Bridge)

castNavidrome benötigt ein Alexa-Cookie, um mit den Amazon-Alexa-Servern zu kommunizieren.

### Option A: Cookie aus dem Browser exportieren

1. Melde dich bei https://alexa.amazon.de (oder .com) im Browser an.
2. Exportiere das Session-Cookie (z. B. mit der Browser-Erweiterung "Export Cookies" oder über die Entwicklertools).
3. Speichere die Cookies als `.secrets/alexa.cookies` im Projektordner.

### Option B: TOTP-Fluss (automatisch)

Wenn `NAVI_AMAZON_USER`, `NAVI_AMAZON_PASS` und `NAVI_AMAZON_TOTP_SECRET` in `.env` gesetzt sind, meldet sich castNavidrome automatisch bei Amazon ab und holt ein frisches Cookie — kein manuelles Kopieren nötig.

> **Hinweis:** `.secrets/` und `.env` werden nicht ins Git-Repository committet (siehe `.gitignore`).

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
| 401/403 bei Alexa | Cookie abgelaufen → `.secrets/alexa.cookies` neu exportieren oder TOTP-Login aktivieren |
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
