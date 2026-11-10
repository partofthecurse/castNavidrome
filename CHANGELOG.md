# Changelog

All notable changes to castNavidrome are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.2] - 2026-11-10

### Fixed
- Show the UPnP renderer as paused instead of stopped when the Echo leaves the skill, plays other media or
  stops the track early. DLNA clients took the stopped state for the end of the track and started the next
  one, which brought the Echo back into the skill. The renderer ignores the Echo status until a client or the
  skill plays a track again, and a stop of the client is no longer turned into a pause.
- Stop or pause the UPnP renderer when the Echo leaves the skill (another skill or music service takes over,
  or the playback is stopped or paused by voice), so that DLNA clients no longer show the track as playing.
  The renderer shows the playback again when the skill resumes the same track.
- Release the UPnP renderer when the skill starts music of its own, or when the Echo reports other media twice
  in a row, so that the renderer no longer takes the Echo over again at the end of its track.

## [0.2.1] - 2026-11-06

### Added
- Support spoken next-track commands for renderer playback through an automatically associated Echo and local bridge.

### Changed
- Prefer the next track supplied by a UPnP client over the album-derived fallback queue.
- Suppress successful local health-check access logs while retaining other request logs.

### Fixed
- Prevent stale timers and playback events from advancing or changing the wrong track.
- Reject ambiguous Echo-to-renderer associations instead of guessing.

## [0.2.0] - 2026-11-06

### Added
- Report Echo playback state changes to UPnP clients when Amazon media status is available.
- Send album cover metadata to Alexa devices, including devices without a reported display interface.

### Changed
- Reuse the Amazon session and device list for renderer commands to reduce response times.
- Use aioamazondevices for renderer authentication and text commands.
- Improve UPnP discovery, renderer descriptions and protocol compatibility.
- Upgrade the container runtime to Python 3.14.

### Fixed
- Cancel automatic queue advancement when an Echo pause or stop is detected.
- Improve Alexa cookie validation and regional text-command routing.
- Avoid a duplicate Navidrome song lookup when loading a renderer queue.

## [0.10.0] — Prepared for publication

### Added
- `README.md`, `README.de.md`, `README.es.md` — installation, Docker Compose example, configuration reference,
  changes compared to AskNavidrome, security notes.
- `CREDITS.md` — origin of every adopted feature (AskNavidrome upstream and community forks) plus local features.
- `LICENSE` — MIT, preserving the original Ross Stewart copyright and adding castNavidrome contributors.
- `.env.example` — committed configuration template with placeholder values (no secrets).
- `.gitignore` — excludes `.env`, `.secrets/`, `state/`, `ts/`, Python and Sphinx build artifacts.
- `CHANGELOG.md` — this file, with semantic versioning starting at `0.10.0`.
- `skill/castnavidrome/__init__.py` — package version (`__version__ = "0.10.0"`).
- Dockerfile builds a `castnavidrome` image (alpine:3.19); `docker compose` brings up the skill and an
  optional UPnP MediaRenderer container.
- Browser-based Amazon cookie capture proxy (`skill/castnavidrome/cookie_capture_proxy.py`) backed by `alexapy`,
  with `/api/alexa/cookie/save`, `/api/alexa/cookie/proxy/*` and `/api/alexa/cookie/proxy/status` endpoints.

### Changed
- Removed all real secrets and personal data from the repository: `.env`, `.secrets/alexa.cookies`,
  `state/renderer-devices.json` (device registry) and `ts/` (Tailscale state) are now local-only and excluded
  from version control.
- Configuration is sourced from environment variables or Docker secrets; nothing is hardcoded.
- Amazon authentication moved from the OAuth 2.0 / Login with Amazon flow (`amazon_oauth.py`) to the
  browser-based cookie capture proxy; the `NAVI_AMAZON_CLIENT_ID` / `_CLIENT_SECRET` / `_REDIRECT_URI` /
  `_TOKEN_FILE` variables are removed from the documentation, `.env.example` and the Compose examples.
  `NAVI_ALEXA_CAPTURE_PASSWORD`, `NAVI_AMAZON_USER`, `NAVI_AMAZON_PASS` and `NAVI_AMAZON_TOTP_SECRET`
  are the new configuration variables.

### Fork notice
castNavidrome is a fork of [AskNavidrome](https://github.com/rosskouk/asknavidrome) (Ross Stewart, MIT).
Upstream features are preserved; adopted features and local changes are listed in `CREDITS.md`.

This release is **not published** — everything is prepared and awaits explicit release approval.

[0.10.0]: https://github.com/castnavidrome/castnavidrome/releases/tag/0.10.0
[0.2.0]: https://github.com/partofthecurse/castNavidrome/releases/tag/v0.2.0
[0.2.1]: https://github.com/partofthecurse/castNavidrome/releases/tag/v0.2.1
[0.2.2]: https://github.com/partofthecurse/castNavidrome/releases/tag/v0.2.2
