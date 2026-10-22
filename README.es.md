# castNavidrome

Skill de Alexa que conecta dispositivos Alexa a un servidor multimedia compatible con la API Subsonic (por ejemplo Navidrome), para que puedas transmitir tu propia colección de música a tus dispositivos Echo.

**castNavidrome es un fork de [AskNavidrome](https://github.com/rosskouk/asknavidrome)** (Ross Stewart, licencia MIT) con extensiones locales de varios forks comunitarios además de un MediaRenderer UPnP integrado para cada dispositivo Alexa. Consulta [Fork de AskNavidrome](#fork-de-asknavidrome) y [CREDITS.md](CREDITS.md).

## Puntos destacados

- Reproduce música por artista, álbum, canción, género, lista de reproducción, década o consulta de texto libre.
- Mezcla la cola de reproducción, marca/desmarca canciones, muestra detalles de la pista actual.
- Emisiones de radio y descubrimiento de listas de reproducción ("reproduce más listas como esta", "encuentra una lista").
- Temas de ayuda y respuestas habladas en el idioma del dispositivo Echo.
- MediaRenderer UPnP opcional: cada dispositivo Alexa seleccionado aparece como su propio renderer en Navidrome, para que clientes DLNA (Symfonium, Supersonic, …) puedan enviar pistas a Echos individuales.
- Inicio de sesión de Amazon opcional con nombre de usuario, contraseña y TOTP/2FA (reemplaza la copia manual de cookies).
- Se ejecuta directamente con Python o en un contenedor Docker (recomendado).

## Idiomas

Este README: Español.
- [`README.md`](README.md) — English
- [`README.de.md`](README.de.md) — Deutsch

Los modelos de interacción para la consola para desarrolladores de Alexa están en [`alexa/`](alexa) para `de-DE`, `en-US`, `es-ES`, `fr-FR`, `it-IT`, `pt-BR`.

## Fork de AskNavidrome

castNavidrome es un fork de [rosskouk/asknavidrome](https://github.com/rosskouk/asknavidrome). Las características upstream (acceso a la API Subsonic, controlador de skill de Alexa, MediaQueue, scrobbling, multi-hilo para listas grandes) provienen de Ross Stewart.

Las características adicionales se adoptaron de forks comunitarios de AskNavidrome (todos con licencia MIT) y del desarrollo local. El origen exacto de cada característica, el autor, el fork y los cambios locales están documentados en [CREDITS.md](CREDITS.md).

Características locales sin plantilla upstream:

- `skill/castnavidrome/upnp/` — propio MediaRenderer UPnP (SSDP, Description, SOAP, DIDL) por dispositivo Alexa.
- `skill/castnavidrome/renderer_host.py` — proceso host del renderer, filtro de dispositivos, persistencia de UUID.
- `skill/castnavidrome/renderer_registry.py` — mapeo estable dispositivo Alexa → UUID UPnP (`ownerId` + `serialNumber`).
- `skill/castnavidrome/alexa_device_filter.py` — selección de dispositivos por tipo, nombre, regex y estado en línea.
- `skill/castnavidrome/alexa_remote.py` — comandos de texto a dispositivos Alexa, lista de dispositivos a través de la API de dispositivos de Amazon.
- `skill/castnavidrome/localization.py` — respuestas localizadas del skill y comandos de voz específicos del idioma.
- `alexa/` — modelos de interacción, un archivo por idioma.

El software se distribuye bajo la [licencia MIT](LICENSE). El aviso de copyright original de Ross Stewart se conserva; las modificaciones locales son copyright de los contribuyentes de castNavidrome (consulta `CREDITS.md` y `LICENSE`).

## Requisitos

- Una colección de música digital servida por un servidor multimedia compatible con la API Subsonic (probado con Navidrome).
- El servidor multimedia debe ser accesible mediante HTTPS con un certificado TLS válido (Amazon lo requiere para la transmisión).
- Un dispositivo Echo cuya configuración regional coincida con la configuración regional del skill.
- Un skill de Alexa creado en la [Consola para desarrolladores de Alexa](https://developer.amazon.com/alexa/console/ask), con la interfaz de reproductor de audio habilitada y el punto de conexión HTTPS apuntando a este servicio web.
- (Opcional, para los media renderers) el puerto `1900/udp` disponible para el descubrimiento SSDP y el contenedor capaz de usar la red de host o una macvlan.

## Instalación

### Opción 1: Docker Compose (recomendado)

1. Copia la configuración de ejemplo:
   ```bash
   cp .env.example .env
   ```
2. Edita `.env` y completa tus propios valores (URL de Navidrome, usuario, contraseña, ID del skill, …).  
   `.env` **no** se confirma en el control de versiones.
3. Inicia todo:
   ```bash
   docker compose up -d --build
   ```

Ejemplo `docker-compose.yml`:

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

  # Opcional: expone cada dispositivo Alexa seleccionado como su propio MediaRenderer UPnP.
  # Requiere la red de host para que SSDP (puerto 1900/udp) funcione para el descubrimiento.
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

El archivo de cookies (`.secrets/alexa.cookies`) y el directorio de estado (`state/`) son solo locales y se excluyen del control de versiones mediante `.gitignore`.

### Opción 2: Ejecutar directamente con Python

```bash
cd skill
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-full.txt

NAVI_SKILL_ID=<tu-id-de-skill> \
NAVI_URL=https://tu-navidrome.test \
NAVI_USER=<usuario> \
NAVI_PASS=<contraseña> \
NAVI_PORT=443 \
NAVI_API_PATH=/rest \
NAVI_API_VER=1.16.1 \
python3 app.py
```

Todas las variables de entorno en [Configuración](#configuración).

## Configurar el skill de Alexa

1. Crea un skill personalizado en la [Consola para desarrolladores de Alexa](https://developer.amazon.com/alexa/console/ask).
2. Establece como configuración regional principal la de tu dispositivo Echo (debe coincidir).
3. Sube uno de los modelos de interacción de [`alexa/`](alexa) en *Modelo de interacción → Editor JSON* (por ejemplo `alexa/es-ES.json`) y guarda el modelo.
4. Agrega los nombres de tus listas de reproducción al tipo de ranura `playlist_names`.
5. Activa la interfaz *Reproductor de audio* en *Interfaces*.
6. Establece el punto de conexión en la URL HTTPS de este servicio web (región predeterminada) y guárdalo.
7. Compila el modelo y agrega el skill a tus dispositivos Echo como skill de desarrollo.

El nombre de invocación es el mismo en todos los idiomas y se establece con `NAVI_ALEXA_SKILL_NAME`.

## Construir la imagen Docker

```bash
docker build -t castnavidrome:local .
```

Las imágenes de múltiples arquitecturas se pueden construir con `docker buildx` cuando sea necesario (el Dockerfile apunta a `alpine:3.22.1`). La imagen no se publica automáticamente; compílala y súbela a tu propio registro antes de lanzar un release.

## Configuración

El servicio lee su configuración de variables de entorno.

### Obligatorias

| Variable | Descripción | Ejemplo |
|---|---|---|
| `NAVI_SKILL_ID` | ID de tu skill de Alexa (limita el servicio web a tu skill) | `amzn1.ask.skill.xxxxxxxx-…` |
| `NAVI_URL` | URL del servidor de la API Subsonic (`https://`, sin barra final) | `https://navidrome.example.test` |
| `NAVI_USER` | Nombre de usuario de Navidrome | `bob` |
| `NAVI_PASS` | Contraseña de Navidrome | — |
| `NAVI_PORT` | Puerto del servidor de la API Subsonic | `443` |
| `NAVI_API_PATH` | Ruta de la API Subsonic | `/rest` |
| `NAVI_API_VER` | Versión de la API Subsonic | `1.16.1` |
| `NAVI_SONG_COUNT` | Número mínimo de canciones para listas aleatorias/género/artista | `50` |

### Opcionales

| Variable | Descripción | Ejemplo |
|---|---|---|
| `NAVI_BASE_URL` | URL pública de este skill (se usa para las portadas en las tarjetas de Alexa) | `https://castnavidrome.example.test` |
| `NAVI_DEBUG` | Nivel de depuración (0–3) | `0` |
| `NAVI_DEBUG_TOKEN` | Token que protege los puntos finales `/debug/*` | — |
| `NAVI_ALEXA_API_KEY` | Clave API enviada en el encabezado `X-API-Key` para `/api/alexa/*` | `openssl rand -hex 32` |
| `NAVI_ALEXA_DOMAIN` | Dominio de Amazon | `amazon.com` |
| `NAVI_ALEXA_LOCALE` | Configuración regional de las respuestas y comandos de voz del skill | `de-DE` |
| `NAVI_ALEXA_SKILL_NAME` | Nombre de invocación del skill | `castnavidrome` |
| `NAVI_ALEXA_COOKIE_FILE` | Ruta a un archivo de cookies de Alexa (fallback de cookies) | `/run/secrets/alexa.cookies` |
| `NAVI_AMAZON_USER` / `NAVI_AMAZON_PASS` / `NAVI_AMAZON_TOTP_SECRET` | Inicio de sesión de Amazon con TOTP/2FA (reemplaza el archivo de cookies) | — |
| `NAVI_AMAZON_SESSION_FILE` | Cookies de sesión de Amazon persistidas | `/var/lib/castnavidrome/amazon_session.json` |
| `NAVI_RADIO_URL` / `NAVI_RADIO_STATIONS_URL` | URL de emisiones de radio | — |
| `NAVI_PLAYLIST_NAME_PATTERN` / `_SPOKEN_FORMAT` / `_QUALIFIED_FORMAT` | Agrupación y formato hablado de nombres de listas de reproducción | — |

### MediaRenderer (`castnavidrome-renderer`)

| Variable | Descripción | Ejemplo |
|---|---|---|
| `NAVI_ALEXA_RENDERER_ENABLED` | Habilitar los renderers | `yes` |
| `NAVI_ALEXA_RENDERER_PORT` | Puerto de descripción/control UPnP | `49443` |
| `NAVI_ALEXA_RENDERER_ANNOUNCE` | Qué pistas se anuncian: `explicit`, `always`, `never` | `explicit` |
| `NAVI_ALEXA_RENDERER_STATE_FILE` | Registro que mapea dispositivos Alexa a UUID de renderer | `/var/lib/castnavidrome/renderer-devices.json` |
| `NAVI_ALEXA_RENDERER_NAME_PREFIX` | Prefijo para nombres de renderer | — |
| `NAVI_ALEXA_RENDERER_DEVICE_TYPES` | Tipos de dispositivo permitidos (separados por comas) | `ECHO,FIRE_TV` |
| `NAVI_ALEXA_RENDERER_NAME_REGEX` | Expresión regular que debe cumplir el nombre del dispositivo | `^Echo` |
| `NAVI_ALEXA_RENDERER_ONLY_ONLINE` | Exponer solo dispositivos en línea | `no` |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | Nivel de registro | `INFO` |

Los modos de anuncio (`explicit` = predeterminado: las pistas iniciadas por el usuario se anuncian, las que inicia el renderer se reproducen en silencio) se describen en `CREDITS.md`.

## Cambios respecto a AskNavidrome

castNavidrome conserva el comportamiento upstream de AskNavidrome y agrega:

- MediaRenderer UPnP por dispositivo Alexa (nuevo contenedor/proceso, red de host).
- Localización en seis idiomas con comandos de voz específicos del idioma.
- Búsqueda de texto libre (`castNavidromePlaySearch`), música por década, canción por título, descubrimiento de listas, emisiones de radio, temas de ayuda.
- Inicio de sesión de Amazon con TOTP/2FA (`skill/castnavidrome/amazon_login.py`).
- Puntos finales de depuración protegidos (`NAVI_DEBUG_TOKEN`) y ningún token de sesión / URI de transmisión en los registros ni en la tabla de depuración.

Cada característica adoptada y su origen están listados en [CREDITS.md](CREDITS.md) con los cambios locales aplicados.

### Secreto TOTP (verificación en dos pasos de Amazon)

Para usar el flujo automático de inicio de sesión de Amazon en lugar del archivo de cookies manual, Amazon debe solicitar un código TOTP durante el inicio de sesión. Para obtener el `NAVI_AMAZON_TOTP_SECRET`:

1. Abra la configuración de la cuenta de Amazon para su dominio (por ejemplo https://www.amazon.de/gp/css/account/security).
2. Vaya a **Configuración de verificación en dos pasos (2SV)**.
3. Agregue o administre una **aplicación de autenticación**.
4. Amazon muestra un código QR y, por lo general, una opción para revelar la clave secreta como texto.
5. Copie ese secreto Base32 (solo letras y dígitos, por ejemplo `JBSWY3DPEHPK3PXP`) y configúrelo como `NAVI_AMAZON_TOTP_SECRET`.

El skill calcula el código de 6 dígitos por sí mismo (RFC 6238, solo biblioteca estándar, sin dependencia de `pyotp`).

## Seguridad
- El archivo de cookies de Alexa y cualquier `NAVI_AMAZON_PASS` / `NAVI_AMAZON_TOTP_SECRET` son sensibles. Mantén `.secrets/` fuera del control de versiones (está en `.gitignore`) y montalo de solo lectura.
- No expongas los puntos finales `/api/alexa/*` o `/debug/*` a Internet público sin `NAVI_ALEXA_API_KEY` y HTTPS.

## Licencia

Licencia MIT. Copyright (c) 2022 Ross Stewart; modificaciones locales copyright (c) 2026 colaboradores de castNavidrome. Consulta [LICENSE](LICENSE) und [CREDITS.md](CREDITS.md).

## Disclaimer

Este proyecto está vibe coded: se ensambló rápidamente con asistencia de IA y no ha pasado por una revisión de seguridad o de código exhaustiva. Trátalo como un punto de partida, no como software listo para producción. Los secretos y los datos personales están excluidos del control de versiones mediante `.gitignore`, pero eres responsable de revisar y validar todo lo que ejecutes.
