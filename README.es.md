![castNavidrome logo](/docs/images/cast_navidrome_logo.jpg)

# castNavidrome

castNavidrome convierte cada dispositivo Alexa en su propio MediaRenderer UPnP/DLNA, para que clientes DLNA (Symfonium, Supersonic, …) puedan enviar música a Echos individuales. También conecta dispositivos Alexa a un servidor multimedia compatible con la API Subsonic (por ejemplo Navidrome) para reproducción controlada por voz de tu propia colección de música.

![symfonium screenshot](./docs/images/symfonium-screenshot.jpeg)

**castNavidrome es un fork de [AskNavidrome](https://github.com/rosskouk/asknavidrome)** (Ross Stewart, licencia MIT) con extensiones locales de varios forks comunitarios además de un MediaRenderer UPnP integrado para cada dispositivo Alexa. Consulta [Fork de AskNavidrome](#fork-de-asknavidrome) y [CREDITS.md](CREDITS.md).

## Puntos destacados

- **MediaRenderer UPnP/DLNA:** cada dispositivo Alexa seleccionado aparece como su propio renderer en Navidrome, para que clientes DLNA (Symfonium, Supersonic, …) puedan enviar pistas a Echos individuales.
- Reproduce música por artista, álbum, canción, género, lista de reproducción, década o consulta de texto libre.
- Mezcla la cola de reproducción, marca/desmarca canciones, muestra detalles de la pista actual.
- Emisiones de radio y descubrimiento de listas de reproducción ("reproduce más listas como esta", "encuentra una lista").
- Temas de ayuda y respuestas habladas en el idioma del dispositivo Echo.
- Inicio de sesión opcional de Amazon OAuth 2.0 / Login with Amazon (recomendado, reemplaza la copia manual de cookies y el inicio de sesión TOTP).
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
      - NAVI_ALEXA_API_KEY=${NAVI_ALEXA_API_KEY}
      - NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
      - NAVI_AMAZON_SESSION_FILE=/var/lib/castnavidrome/amazon_session.json
    volumes:
      - ./.secrets/alexa.cookies:/run/secrets/alexa.cookies:ro
      - ./state:/var/lib/castnavidrome
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "1"
    depends_on:
      tailscale:
        condition: service_healthy
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
      - NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
    volumes:
      - ./.secrets/alexa.cookies:/run/secrets/alexa.cookies:ro
      - ./state:/var/lib/castnavidrome
    restart: unless-stopped

  tailscale:
    image: tailscale/tailscale:latest
    container_name: tailscale-${SERVICE}
    hostname: ${SERVICE}
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_SERVE_CONFIG=/config/serve.json
      - TS_USERSPACE=false
      - TS_ENABLE_HEALTH_CHECK=true
      - TS_LOCAL_ADDR_PORT=127.0.0.1:41234
      - TS_AUTH_ONCE=true
    volumes:
      - ./config:/config
      - ./ts/state:/var/lib/tailscale
    devices:
      - /dev/net/tun:/dev/net/tun
    cap_add:
      - net_admin
    ports:
      - 0.0.0.0:${SERVICEPORT}:${SERVICEPORT}
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://127.0.0.1:41234/healthz"]
      interval: 1m
      timeout: 10s
      retries: 3
      start_period: 10s
    restart: unless-stopped
```

Solo las variables requeridas y las rutas fijas están en el archivo Compose. Todos los demás valores tienen un valor predeterminado razonable en el código y se pueden agregar a `.env` cuando sea necesario (consulte [Configuración](#configuración)). El archivo de cookies (`.secrets/alexa.cookies`) y el directorio de estado (`state/`) son solo locales y se excluyen del control de versiones mediante `.gitignore`.

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

### ID del skill

El `NAVI_SKILL_ID` es el identificador único de tu skill de Alexa. Lo encuentras en la [Consola para desarrolladores de Alexa](https://developer.amazon.com/alexa/console/ask):

1. Abre tu skill en la Consola para desarrolladores.
2. Ve a **Skill → Información** (o la pestaña **Usage** en algunas consolas).
3. Copia el **ID del skill** (se ve como `amzn1.ask.skill.xxxxxxxx-…`).
4. Configúralo como `NAVI_SKILL_ID` en tu `.env`.

Si `NAVI_SKILL_ID` no está configurado, el servicio web responde a cualquier solicitud de skill.

### URL externa con Tailscale Funnel

Para que Alexa pueda alcanzar tu skill y Navidrome pueda transmitir carátulas, ambos necesitan una URL HTTPS pública. Puedes crear una con [Tailscale Funnel](https://tailscale.com/kb/1216/funnel) sin abrir puertos en tu router:

1. Instala Tailscale en el host donde se ejecutan castNavidrome y Navidrome.
2. Expón el servicio web de castNavidrome:
   ```bash
   tailscale funnel on 443
   ```
   (o el puerto en el que el contenedor escucha, por ejemplo `8000`).
3. Expón Navidrome de la misma manera si no está ya accesible desde internet:
   ```bash
   tailscale funnel on 443
   ```
4. Tailscale te da un nombre DNS como `yourdevice.tailxxxxyyyy.ts.net`. Úsalo como:
   - `NAVI_URL` — la URL del servidor Navidrome, por ejemplo `https://yourdevice.tailxxxxyyyy.ts.net`
   - `NAVI_BASE_URL` — la URL pública de este skill, por ejemplo `https://yourdevice.tailxxxxyyyy.ts.net`
   - El punto de conexión HTTPS en la Consola para desarrolladores de Alexa, que apunta a tu servicio castNavidrome.

Tailscale Funnel termina TLS en el borde de Tailscale, por lo que se cumple el requisito HTTPS de Alexa sin que tengas que gestionar certificados.

### Alternativa: Tailscale como contenedor sidecar

Si no quieres instalar Tailscale en el host, ejecútalo como contenedor sidecar. castNavidrome comparte entonces el espacio de nombres de red del contenedor de Tailscale (`network_mode: service:tailscale`), por lo que es accesible a través de la dirección de Tailscale Funnel sin necesidad de Tailscale en el host.

Añade un servicio `tailscale` a tu `docker-compose.yml`:

```yaml
services:
  tailscale:
    image: tailscale/tailscale:latest
    container_name: tailscale
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
    cap_add:
      - NET_ADMIN
    volumes:
      - tailscale-state:/var/lib/tailscale
    restart: unless-stopped

  castnavidrome:
    container_name: castnavidrome
    build:
      context: .
      dockerfile: Dockerfile
    image: castnavidrome:local
    network_mode: service:tailscale
    environment:
      - NAVI_SKILL_ID=${NAVI_SKILL_ID}
      - NAVI_URL=https://yourdevice.tailxxxxyyyy.ts.net
      - NAVI_BASE_URL=https://yourdevice.tailxxxxyyyy.ts.net
      - NAVI_USER=${NAVI_USER}
      - NAVI_PASS=${NAVI_PASS}
      - NAVI_PORT=443
      - NAVI_API_PATH=/rest
      - NAVI_API_VER=1.16.1
      - NAVI_SONG_COUNT=50
      - NAVI_DEBUG=0
      - NAVI_ALEXA_API_KEY=${NAVI_ALEXA_API_KEY}
      - NAVI_ALEXA_DOMAIN=${NAVI_ALEXA_DOMAIN:-amazon.com}
      - NAVI_ALEXA_LOCALE=${NAVI_ALEXA_LOCALE:-en-US}
      - NAVI_ALEXA_SKILL_NAME=${NAVI_ALEXA_SKILL_NAME:-castnavidrome}
      - NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
      - NAVI_AMAZON_CLIENT_ID=${NAVI_AMAZON_CLIENT_ID:-}
      - NAVI_AMAZON_CLIENT_SECRET=${NAVI_AMAZON_CLIENT_SECRET:-}
      - NAVI_AMAZON_REDIRECT_URI=${NAVI_AMAZON_REDIRECT_URI:-}
      - NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
    volumes:
      - ./.secrets/alexa.cookies:/run/secrets/alexa.cookies:ro
      - ./state:/var/lib/castnavidrome
    restart: unless-stopped

volumes:
  tailscale-state:
```

Autoriza el dispositivo Tailscale (a través de la consola de administración de Tailscale o `docker exec tailscale tailscale up --authkey=...`) y activa Funnel:

```bash
docker exec tailscale tailscale funnel on 443
```

El resto de la configuración (`NAVI_URL`, `NAVI_BASE_URL`, punto de conexión de Alexa) permanece igual que en el enfoque basado en el host descrito anteriormente.

El nombre de invocación es el mismo en todos los idiomas y se establece con `NAVI_ALEXA_SKILL_NAME`.

**Consejo:** Elige un nombre de invocación que no tenga nada que ver con un servicio de música (no "Spotify", "Apple Music", "Amazon Music", "Navidrome", …). De lo contrario, Alexa podría intentar enrutar tu solicitud a otra skill de música en lugar de castNavidrome, y no se reproducirá tu propia colección de música.

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
| `NAVI_ALEXA_API_KEY` | Clave API enviada en el encabezado `X-API-Key` para `/api/alexa/*`. Générala tú mismo, por ejemplo con `openssl rand -hex 32`. | `openssl rand -hex 32` |
| `NAVI_ALEXA_DOMAIN` | Dominio de Amazon | `amazon.com` |
| `NAVI_ALEXA_LOCALE` | Configuración regional de las respuestas y comandos de voz del skill | `en-US` |
| `NAVI_ALEXA_SKILL_NAME` | Nombre de invocación del skill | `castnavidrome` |
| `NAVI_ALEXA_COOKIE_FILE` | Ruta a un archivo de cookies de Alexa (fallback de cookies) | `/run/secrets/alexa.cookies` |
| `NAVI_AMAZON_CLIENT_ID` / `NAVI_AMAZON_CLIENT_SECRET` / `NAVI_AMAZON_REDIRECT_URI` | Inicio de sesión de Amazon OAuth 2.0 / Login with Amazon | `amzn1.application-oa2-client.xxx` / `secreto` / `https://...` |
| `NAVI_AMAZON_SESSION_FILE` | Cookies de sesión de Amazon persistidas | `/var/lib/castnavidrome/amazon_session.json` |
| `NAVI_RADIO_URL` / `NAVI_RADIO_STATIONS_URL` | URL de emisiones de radio | — |
| `NAVI_PLAYLIST_NAME_PATTERN` / `_SPOKEN_FORMAT` / `_QUALIFIED_FORMAT` | Agrupación y formato hablado de nombres de listas de reproducción | — |

### MediaRenderer (`castnavidrome-renderer`)

| Variable | Descripción | Ejemplo |
|---|---|---|
| `NAVI_ALEXA_RENDERER_ENABLED` | Habilitar los renderers | `yes` |
| `NAVI_ALEXA_RENDERER_PORT` | Puerto de descripción/control UPnP | `49443` |
| `NAVI_ALEXA_RENDERER_ANNOUNCE` | Qué pistas se anuncian: `explicit`, `always`, `never` | `explicit` |
| `NAVI_ALEXA_RENDERER_ANNOUNCE_INTERVAL` | Segundos entre los anuncios periódicos SSDP `ssdp:alive` (`<= 0` deshabilita el bucle) | `60` |
| `NAVI_ALEXA_RENDERER_DISABLE_ANNOUNCE` | Deshabilitar anuncios SSDP periódicos (`true`/`false`) | `false` |
| `NAVI_ALEXA_RENDERER_NOTIFY_COUNT` | Número de veces que se repiten `ssdp:alive`/`ssdp:byebye` (`0` = sin repeticiones) | `3` |
| `NAVI_ALEXA_RENDERER_NOTIFY_DELAY` | Segundos entre repeticiones de notificaciones SSDP (`0` = sin retraso) | `0.4` |
| `NAVI_ALEXA_RENDERER_CLIENT_TIMEOUT` | Segundos de inactividad del cliente tras los cuales se detiene la reproducción (`0` = deshabilitado) | `0` |
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
- Inicio de sesión de Amazon OAuth 2.0 / Login with Amazon (`skill/castnavidrome/amazon_oauth.py`).
- Puntos finales de depuración protegidos (`NAVI_DEBUG_TOKEN`) y ningún token de sesión / URI de transmisión en los registros ni en la tabla de depuración.

Cada característica adoptada y su origen están listados en [CREDITS.md](CREDITS.md) con los cambios locales aplicados.

### Amazon OAuth 2.0 / Login with Amazon (recomendado)

Este es el método de inicio de sesión estable a largo plazo. La página de inicio de sesión normal de Amazon (`/ap/signin`) ya no funciona de manera confiable, por lo que castNavidrome utiliza el flujo oficial de código de autorización OAuth 2.0, igual que las habilidades de Home Assistant.

#### A. Crear un perfil de seguridad de Login with Amazon

1. Abra la [consola de Login with Amazon](https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html) e inicie sesión con su cuenta de desarrollador de Amazon.
2. Haga clic en **Create a New Security Profile** (o seleccione un perfil existente).
3. Ingrese un nombre (por ejemplo `castNavidrome`) y una descripción, luego haga clic en **Save**.
4. Copie los valores mostrados:
   - **Client ID** (comienza con `amzn1.application-oa2-client.`)
   - **Client Secret**

#### B. Registrar la Redirect URI en la Amazon Developer Console

Para que Amazon acepte el callback de OAuth, la Redirect URI debe estar registrada exactamente en el perfil de seguridad:

1. Abra su perfil de seguridad en la consola de Login with Amazon → pestaña **Web Settings**.
2. Agregue la siguiente entrada en **Allowed Return URLs**:

   ```
   https://su-dominio-castnavidrome.test/api/alexa/amazon/callback
   ```

   Reemplace `su-dominio-castnavidrome.test` por su dominio público de castNavidrome (por ejemplo `https://castnavidrome.drake-aldebaran.ts.net`).
3. Haga clic en **Save**.

> **Importante:** La Redirect URI debe coincidir exactamente con `NAVI_AMAZON_REDIRECT_URI` en su `.env`, incluyendo cualquier barra final.

#### C. Configurar variables de entorno en `.env`

```env
# Amazon OAuth (Login with Amazon)
NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.su-client-id
NAVI_AMAZON_CLIENT_SECRET=su-client-secret
NAVI_AMAZON_REDIRECT_URI=https://su-dominio-castnavidrome.test/api/alexa/amazon/callback
NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
```

Además, necesita `NAVI_ALEXA_DOMAIN` para especificar el mercado de Amazon:

```env
# Mercado de Amazon para el inicio de sesión
NAVI_ALEXA_DOMAIN=amazon.de
```

| Variable | Significado |
|----------|-------------|
| `NAVI_AMAZON_CLIENT_ID` | Client ID del perfil de seguridad LWA |
| `NAVI_AMAZON_CLIENT_SECRET` | Client Secret del perfil de seguridad LWA |
| `NAVI_AMAZON_REDIRECT_URI` | Debe coincidir exactamente con „Allowed Return URLs“ en la Amazon Developer Console |
| `NAVI_AMAZON_TOKEN_FILE` | Ruta donde se guardan los tokens OAuth |
| `NAVI_ALEXA_DOMAIN` | Mercado de Amazon, por ejemplo `amazon.de` (DE), `amazon.com` (US) |

#### D. Iniciar los contenedores e inicializar el token OAuth

1. Construya e inicie los contenedores:

   ```bash
   docker compose up -d --build
   ```

   Las variables OAuth se envían automáticamente a ambos contenedores (`castnavidrome` y `castnavidrome-renderer`).

2. Abra en el navegador la URL de inicio de sesión:

   ```
   https://su-dominio-castnavidrome.test/api/alexa/amazon/login
   ```

3. Inicie sesión con su cuenta de Amazon y conceda a castNavidrome permiso para acceder a sus dispositivos Alexa.
4. Será redirigido de vuelta a castNavidrome, y los tokens de acceso se guardarán en `amazon_oauth_token.json`. A partir de ahora la API de Alexa funciona automáticamente; los tokens expirados se refrescan en segundo plano.

#### Comprobación de inicio

Al iniciar el contenedor principal se comprueba si existen tokens OAuth válidos. Si no, aparece una advertencia en el log:

```
No valid Amazon OAuth tokens found. Open /api/alexa/amazon/login to authenticate before using the Alexa API.
```

Esto es normal después del primer inicio – primero cree los tokens accediendo a `/api/alexa/amazon/login`.

#### Archivo de cookies como fallback

Si el inicio de sesión de OAuth no funciona (por ejemplo, debido a un CAPTCHA o un paso de verificación adicional), aún se puede utilizar un archivo de cookies de Alexa estático como fallback.

### Archivo de cookies de Alexa (fallback manual)

Si prefieres no usar el inicio de sesión automático de Amazon (o falla debido a un CAPTCHA o un paso de verificación adicional), puedes proporcionar un archivo de cookies de sesión de Alexa existente en su lugar.

1. Abre tu dominio de Amazon (por ejemplo https://www.amazon.de) en el navegador e inicia sesión.
2. Abre las Herramientas de desarrollo (F12), ve a **Aplicación → Cookies** y selecciona tu dominio de Amazon.
3. Copia las cookies como pares `name=value`, una por línea. Asegúrate de incluir la cookie `csrf`.
4. Guarda el archivo como `.secrets/alexa.cookies` (o cualquier ruta que prefieras) y configura `NAVI_ALEXA_COOKIE_FILE` a esa ruta.
5. Monta el archivo de solo lectura en el contenedor (ver el ejemplo de `docker-compose.yml`).

![Exportación de cookies de Alexa](https://github.com/user-attachments/assets/bf641182-8e06-404d-9d8d-abb9341dbcf0)

## Seguridad
- El archivo de cookies de Alexa y `NAVI_AMAZON_CLIENT_SECRET` son sensibles. Mantén `.secrets/` y `.env` fuera del control de versiones (están en `.gitignore`) y monta `.secrets/` de solo lectura.
- No expongas los puntos finales `/api/alexa/*` o `/debug/*` a Internet público sin `NAVI_ALEXA_API_KEY` y HTTPS.

## Licencia

Licencia MIT. Copyright (c) 2022 Ross Stewart; modificaciones locales copyright (c) 2026 colaboradores de castNavidrome. Consulta [LICENSE](LICENSE) und [CREDITS.md](CREDITS.md).

## Disclaimer

Este proyecto está vibe coded: se ensambló rápidamente con asistencia de IA y no ha pasado por una revisión de seguridad o de código exhaustiva. Trátalo como un punto de partida, no como software listo para producción. Los secretos y los datos personales están excluidos del control de versiones mediante `.gitignore`, pero eres responsable de revisar y validar todo lo que ejecutes.
