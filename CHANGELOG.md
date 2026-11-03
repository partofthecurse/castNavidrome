# Changelog

All notable changes to castNavidrome are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
