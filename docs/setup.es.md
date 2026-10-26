# castNavidrome - Configuración (Wiki)

Este wiki describe paso a paso cómo configurar castNavidrome (un fork de AskNavidrome) para controlar tu biblioteca de medios de Navidrome mediante comandos de voz de Alexa.

---

## 1. Requisitos previos

- Un servidor de medios [Navidrome](https://www.navidrome.org/) en funcionamiento
- Una cuenta de desarrollador de Amazon Alexa (https://developer.amazon.com/alexa/console/ask)
- Docker y Docker Compose en el host
- Opcional: Una cuenta de [Tailscale](https://tailscale.com/) (para acceso público sin port forwarding)

---

## 2. Clonar el repositorio

```bash
git clone https://github.com/partofthecurse/castNavidrome.git
cd castNavidrome
```

---

## 3. Crear la Alexa skill (Amazon Developer Console)

1. Ve a la [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Haz clic en **Create Skill**.
3. Elige un nombre (p. ej. `castNavidrome`), el modelo **Custom** y el método **Provision your own**.
4. Elige el idioma deseado (p. ej. `German (DE)` o `English (US)`).
5. Copia el **Skill ID** (tiene la forma `amzn1.ask.skill.xxxx-xxxx-...`) — lo necesitas como `NAVI_SKILL_ID`.
6. Añade los intents y slots en **Interaction Model** (consulta `skill/alexa.json` en el repositorio para un modelo de-DE/en-US listo para usar).
7. En **Endpoint** introducirás más adelante tu URL pública HTTPS (mediante Tailscale Funnel o tu propio proxy inverso).
8. Guarda y construye el modelo.

**Importante:** Para usar el avance silencioso (continuar a la siguiente pista sin confirmación hablada), el Interaction Model debe contener el intent `NaviSonicPlaySongByArtistQuiet`.

---

## 4. Crear el archivo de configuración `.env`

```bash
cp .env.example .env
```

Abre `.env` y rellena los valores obligatorios:

```env
# ---- Service / Tailscale ----
SERVICE=castnavidrome
SERVICEPORT=5000

# TS_AUTHKEY=tu-clave-de-tailscale  # solo si usas Tailscale

# ---- Navidrome (Subsonic API) - obligatorio ----
NAVI_SKILL_ID=amzn1.ask.skill.00000000-0000-0000-0000-000000000000
NAVI_URL=https://tu-servidor-navidrome.test
NAVI_BASE_URL=https://castnavidrome.tu-dominio.test
NAVI_USER=tu-usuario-navidrome
NAVI_PASS=tu-contraseña-navidrome

# ---- Alexa skill ----
NAVI_ALEXA_API_KEY=una-clave-aleatoria-para-proteger-la-api

# Login de Amazon (Login with Amazon / OAuth 2.0, recomendado)
NAVI_AMAZON_CLIENT_ID=amzn1.application-oa2-client.00000000000000000000000000000000
NAVI_AMAZON_CLIENT_SECRET=tu-client-secret
NAVI_AMAZON_REDIRECT_URI=https://castnavidrome.tu-dominio.test/api/alexa/amazon/callback
NAVI_AMAZON_TOKEN_FILE=/var/lib/castnavidrome/amazon_oauth_token.json
NAVI_ALEXA_DOMAIN=amazon.de

# Fallback de cookie (opcional)
# NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies
```

### Generar `NAVI_ALEXA_API_KEY`

```bash
openssl rand -hex 32
```

Pega la salida como `NAVI_ALEXA_API_KEY` en `.env`.

---

## 5. Login with Amazon (OAuth 2.0) — recomendado

castNavidrome usa el flujo oficial de código de autorización OAuth 2.0 de Login with Amazon (LWA). Es el método estable a largo plazo, ya que la página de inicio de sesión clásica de Amazon (`/ap/signin`) ya no funciona de forma fiable.

### Paso 1: Crear un perfil de seguridad de Login with Amazon

1. Abre la [Login with Amazon Console](https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html).
2. Inicia sesión con tu cuenta de desarrollador de Amazon.
3. Haz clic en **Create a New Security Profile**.
4. Introduce un nombre (p. ej. `castNavidrome`) y una descripción, luego haz clic en **Save**.
5. Copia los valores mostrados:
   - **Client ID** (empieza por `amzn1.application-oa2-client.`)
   - **Client Secret**

### Paso 2: Registrar la redirect URI y el origen permitido

Para que Amazon acepte el callback de OAuth, la redirect URI debe estar registrada exactamente en el perfil de seguridad:

1. Abre tu perfil de seguridad en la Login with Amazon Console → pestaña **Web Settings**.
2. En **Allowed Origins**, añade el origen público de castNavidrome, p. ej.:

   ```
   https://castnavidrome.tu-dominio.test
   ```

3. En **Allowed Return URLs**, añade:

   ```
   https://castnavidrome.tu-dominio.test/api/alexa/amazon/callback
   ```

   Sustituye `castnavidrome.tu-dominio.test` por tu dominio público de castNavidrome (p. ej. `https://castnavidrome.drake-aldebaran.ts.net`).
4. Haz clic en **Save**.

> **Importante:** La redirect URI debe coincidir exactamente con `NAVI_AMAZON_REDIRECT_URI` en tu `.env` — incluyendo una posible barra final.

### Paso 3: Establecer las variables de entorno en `.env`

Introduce los valores del Paso 1 en `.env` (ver sección 4).

| Variable | Significado |
|----------|-------------|
| `NAVI_AMAZON_CLIENT_ID` | Client ID del perfil de seguridad LWA |
| `NAVI_AMAZON_CLIENT_SECRET` | Client Secret del perfil de seguridad LWA |
| `NAVI_AMAZON_REDIRECT_URI` | Debe estar registrada exactamente bajo "Allowed Return URLs" en la Amazon Developer Console |
| `NAVI_AMAZON_TOKEN_FILE` | Ruta donde se guardan los tokens de OAuth |
| `NAVI_ALEXA_DOMAIN` | Marketplace de Amazon, p. ej. `amazon.de` (DE), `amazon.com` (US) |

### Paso 4: Iniciar el contenedor e inicializar el token de OAuth

1. Construye e inicia los contenedores:

   ```bash
   docker compose up -d --build
   ```

2. Abre en el navegador la URL de inicio de sesión:

   ```
   https://castnavidrome.tu-dominio.test/api/alexa/amazon/login
   ```

3. Inicia sesión con tu cuenta de Amazon y concede a castNavidrome permiso para acceder a tus dispositivos Alexa.
4. Serás redirigido de vuelta a castNavidrome, y los tokens de acceso se guardarán en `amazon_oauth_token.json`.
5. A partir de ahora la API de Alexa funciona automáticamente; los tokens caducados se renuevan en segundo plano.

### Comprobación de arranque

Al arrancar el contenedor principal se comprueba si hay tokens de OAuth válidos. Si no, aparece una advertencia en el log:

```
No valid Amazon OAuth tokens found. Open /api/alexa/amazon/login to authenticate before using the Alexa API.
```

Esto es normal tras el primer arranque — crea los tokens llamando a `/api/alexa/amazon/login`.

---

## 6. Fallback de archivo de cookie (opcional)

Si el inicio de sesión OAuth no funciona (p. ej. por CAPTCHA o pasos de verificación adicionales), se puede usar un archivo de cookie de Alexa estático.

1. Inicia sesión en https://alexa.amazon.com (o .de) en tu navegador.
2. Exporta la cookie de sesión (p. ej. con la extensión "Export Cookies" o las herramientas de desarrollo).
3. Guarda las cookies como `.secrets/alexa.cookies` en la carpeta del proyecto.
4. Establece `NAVI_ALEXA_COOKIE_FILE=/run/secrets/alexa.cookies` en `.env`.

> **Nota:** `.secrets/`, `.env` y el archivo de token no se suben a Git (ver `.gitignore`).

---

## 7. Iniciar Docker Compose

```bash
docker compose up -d --build
```

Esto construye la imagen e inicia tres contenedores:

- `castnavidrome` — el servicio web de la Alexa skill (Flask)
- `castnavidrome-renderer` (opcional) — expone cada dispositivo Alexa como su propio media renderer UPnP (usa red del host para SSDP)
- `tailscale` — opcional, para acceso externo seguro mediante Tailscale

### Iniciar solo la skill (sin Tailscale)

```bash
docker compose up -d --build castnavidrome
```

### Iniciar solo el renderer

```bash
docker compose up -d --build castnavidrome-renderer
```

---

## 8. Configurar Tailscale (recomendado para acceso externo)

1. Crea una [Tailscale Auth Key](https://login.tailscale.com/admin/settings/keys) (tipo "ephemeral" o "reusable").
2. Añádela a `.env`: `TS_AUTHKEY=tskey-auth-...`
3. Crea un `config/serve.json`:

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

4. Inicia `docker compose up -d`.
5. En la consola de administración de Tailscale, activa **Funnel** para el nodo castNavidrome.
6. Introduce la URL de Funnel como `NAVI_BASE_URL` en `.env` y especifícala como endpoint en la Alexa skill.

---

## 9. Vincular el endpoint de la Alexa skill

1. En la Alexa Developer Console, ve a tu skill → **Endpoint**.
2. Selecciona **HTTPS** e introduce la URL pública del servidor castNavidrome, p. ej.:

```
https://tu-nodo.ts.net:5000
```

o con Funnel:

```
https://abc123-def456.tail...  # tu URL de Funnel
```

3. Selecciona **My development endpoint is a sub-domain of a domain that has a wildcard certificate from a certificate authority**.
4. Guarda.

---

## 10. Probar la skill

1. En la Alexa Developer Console: **Test** → activa el desarrollo de la skill.
2. Di a un dispositivo Alexa: "Alexa, abre castNavidrome" (o el nombre de invocación elegido).
3. Prueba comandos como:
   - "pon música de Queen"
   - "pon el álbum Abbey Road de los Beatles"
   - "pon mis canciones favoritas"
   - "pon música aleatoria"

**Consejo:** Elige un nombre de invocación que no sea el nombre de un servicio de música (p. ej. no "Spotify" ni "Apple Music") para evitar conflictos.

---

## 11. Media renderer (UPnP) — opcional

1. Establece `NAVI_ALEXA_RENDERER_ENABLED=yes` (por defecto).
2. Inicia el contenedor `castnavidrome-renderer` con `network_mode: host`.
3. El renderer se anuncia mediante SSDP en la red y aparece en los clientes UPnP como un dispositivo separado por cada dispositivo Alexa.

| Variable | Por defecto | Significado |
|---|---|---|
| `NAVI_ALEXA_RENDERER_PORT` | `49443` | Puerto del renderer |
| `NAVI_ALEXA_RENDERER_REFRESH_SECONDS` | `300` | Intervalo de actualización de dispositivos |
| `NAVI_ALEXA_RENDERER_DISABLE_REFRESH` | `true` | Desactiva la actualización periódica de dispositivos (por defecto: solo una vez al arrancar el contenedor) |
| `NAVI_ALEXA_RENDERER_LOG_LEVEL` | `INFO` | Nivel de log |

---

## 12. Actualizar a una nueva versión

```bash
docker compose pull
docker compose up -d
```

O:

```bash
docker compose up -d --build
```

El estado (sesión de Amazon, dispositivos renderer) está en `./state` y se conserva entre actualizaciones.

---

## 13. Solución de problemas

| Problema | Solución |
|---|---|
| La skill no responde | Comprueba `NAVI_SKILL_ID` y el endpoint en la Alexa Console |
| 401/403 con Alexa | Cookie caducada → vuelve a exportar `.secrets/alexa.cookies` o repite el inicio de sesión OAuth en `/api/alexa/amazon/login` |
| Renderer no encontrado | Comprueba `network_mode: host`, abre el firewall para SSDP (1900/udp) |
| Tailscale no conecta | Comprueba `TS_AUTHKEY`, `/dev/net/tun` y `cap_add: net_admin` en Compose |
| Las canciones no se reproducen | Comprueba la URL y las credenciales de Navidrome en `.env`, `docker compose logs castnavidrome` |

Ver logs:

```bash
docker compose logs -f castnavidrome
docker compose logs -f castnavidrome-renderer
docker compose logs -f tailscale
```

---

## 14. Imagen Docker preconstruida

```bash
docker pull ghcr.io/partofthecurse/castnavidrome:latest
```

O una versión específica:

```bash
docker pull ghcr.io/partofthecurse/castnavidrome:0.10.0
```

Alternativamente, construye la imagen localmente:

```bash
docker build -t castnavidrome:local .
```

---

## 15. Licencia y créditos

castNavidrome se basa en [AskNavidrome](https://github.com/rosskouk/asknavidrome) de Ross Stewart (licencia MIT). Consulta `LICENSE` y `CREDITS.md` para más detalles.
