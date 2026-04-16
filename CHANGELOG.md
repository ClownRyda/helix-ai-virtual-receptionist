# Changelog — Helix AI Virtual Receptionist

All versions are tagged in GitHub. Latest release is always `latest`.

---

## [latest] → v1.6.3

---

## [v1.6.3] — 2026-04-16

### Summary
Docker path hardening — aligns the Docker compose stack with the v1.6.1 loopback
security model, fixes an RTP port overlap in the Asterisk container, and aligns
Python version between the agent Dockerfile and the native installer.

### Fixed
- `docker/docker-compose.yml` — dashboard service changed from `ports: ["3000:3000"]`
  (world-exposed) to `network_mode: host` with `HOST=127.0.0.1`. Dashboard is now
  loopback-only in Docker, consistent with native mode. nginx proxies to it.
- `docker/docker-compose.yml` — `API_BASE_URL` env var corrected from
  `http://localhost:8000` → `http://127.0.0.1:8000`
- `docker/docker-compose.yml` — RTP comment range updated 10000-20000 → 10000-19999
  to match the v1.6.1 rtp.conf fix (agent listener starts at 20000)
- `docker/Dockerfile.asterisk` — `EXPOSE 10000-20000/udp` → `EXPOSE 10000-19999/udp`;
  eliminates the port 20000 overlap with the agent RTP receiver
- `docker/Dockerfile.agent` — Python 3.12 → Python 3.11; base image updated to
  `ubuntu24.04`; aligns with `onboard.sh` native install (both now use Python 3.11)
- `deploy.sh` — final summary no longer advertises ARI (8088) and Ollama (11434) as
  public URLs. Internal services now listed under a clearly labelled
  "Loopback only — do not expose" section. Public URLs now correctly show `/` and
  `/api/` paths through nginx.
- `deploy.sh` — added explanatory comment for `COMPOSE_FILE` symlink resolution

### Changed
- `docker/docker-compose.yml` — header comment rewritten to document public vs.
  loopback-only port layout clearly

---

## [latest] → v1.6.2

---

## [v1.6.2] — 2026-04-16

### Summary
Makes `scripts/onboard.sh` a true one-shot production installer for Ubuntu bare-metal.
Two bugs fixed: the firewall step was opening internal loopback ports to the network;
the native install path left users with a manual start command instead of managed services.

### Fixed
- `scripts/onboard.sh` — firewall section no longer opens ARI (8088), Agent API (8000),
  or Dashboard (3000) in UFW/firewalld. These are loopback-only services proxied through
  nginx and must never be world-accessible. Correct ports opened: SSH 22, HTTP 80,
  HTTPS 443, SIP 5060, RTP 10000–19999, Agent RTP 20000–20100.
- `scripts/onboard.sh` — native install "next steps" no longer tells users to run
  `python main.py` in a terminal. Output now references systemd service status commands
  and log tail commands, consistent with the production service model.

### Added
- `scripts/onboard.sh` — new **Step 11: Production Services** (native mode only):
  - Creates `helix` system user (`useradd -r`, no login shell)
  - Rsyncs repo to `/opt/helix/` and sets `helix:helix` ownership
  - Installs and enables `systemd/helix-agent.service` and `systemd/helix-dashboard.service`
  - Optionally starts services immediately with pass/fail status check
  - Installs nginx, copies `deploy/nginx-helix.conf`, prompts for domain/IP,
    enables site, removes default site, runs `nginx -t` before enabling
  - Writes Ollama systemd drop-in override to bind to `127.0.0.1:11434`
  - Locks `.env` to `chmod 600 / helix:helix` ownership
- `scripts/onboard.sh` — header comment updated to document all 11 steps
- `HELIX_VERSION` bumped to `v1.6.2` (displayed in banner and summary)
- `TOTAL_STEPS` updated to 11

### Result
Running `bash scripts/onboard.sh` on a fresh Ubuntu 24.04 server now produces a
fully production-ready deployment: all services managed by systemd, public traffic
through nginx, internal services loopback-only, secrets locked down, firewall
correctly hardened.

---

## [latest] → v1.6.1

---

## [v1.6.1] — 2026-04-16

### Summary
Production bare-metal hardening — security, service management, and operational
readiness for Ubuntu 24.04 without Docker. All internal services now bind to
`127.0.0.1` only; nginx terminates public traffic; systemd manages every
process; logrotate and SQLite backups are automated.

### Security Fixes
- `agent/config.py` — `API_HOST` default changed from `0.0.0.0` → `127.0.0.1`;
  FastAPI no longer exposed to the network without nginx in front
- `agent/api.py` — CORS `allow_origins=["*"]` replaced with configurable
  `API_CORS_ORIGINS` env var (defaults to `http://127.0.0.1:3000,http://localhost:3000`)
- `asterisk/etc/asterisk/ari.conf` — `allowed_origins=*` replaced with
  `allowed_origins=http://127.0.0.1:8088,http://localhost:8088`; ARI is
  loopback-only and not proxied through nginx
- `dashboard/server/index.ts` — dashboard Express server binds to
  `process.env.HOST || "127.0.0.1"` (was hardcoded `0.0.0.0`); PORT default
  corrected from 5000 → 3000 to match documented architecture
- `agent/.env.example` — `API_HOST` updated to `127.0.0.1`; `API_CORS_ORIGINS`
  documented with safe defaults

### Bug Fixes
- `asterisk/etc/asterisk/rtp.conf` — `rtpend` changed from `20000` → `19999`;
  fixes RTP port overlap with agent's RTP listener which starts at 20000

### Added

**`asterisk/etc/asterisk/logger.conf`** (new — was missing from repo)
- Configures Asterisk log channels: `full`, `error`, and `console`
- Logs written to `/var/log/asterisk/`
- Without this file Asterisk falls back to defaults with no disk logging

**`systemd/helix-agent.service`**
- Production systemd unit for the Python agent (`uvicorn` + `ari_agent`)
- Runs as dedicated `helix` system user (not root)
- `EnvironmentFile=/opt/helix/agent/.env` for secret injection
- GPU device access via `DeviceAllow` for RTX 4090
- `Restart=on-failure`, `RestartSec=5s`, logs to journald

**`systemd/helix-dashboard.service`**
- Production systemd unit for the React/Node dashboard
- Runs as `helix` user; sets `HOST=127.0.0.1` and `PORT=3000`
- `WorkingDirectory=/opt/helix/dashboard`

**`systemd/ollama.service.reference`**
- Not a unit file — documents how to override Ollama's auto-installed service
  to bind to `127.0.0.1:11434` instead of all interfaces
- Includes exact `systemctl edit ollama` drop-in snippet

**`deploy/nginx-helix.conf`**
- nginx reverse proxy config for production
- `/` → dashboard at `127.0.0.1:3000` with WebSocket upgrade headers
- `/api/` → agent at `127.0.0.1:8000`; 120 s proxy timeout for LLM responses
- ARI (`8088`) intentionally NOT proxied — stays loopback-only
- HTTP→HTTPS redirect stub included (SSL cert path commented for Certbot)

**`deploy/logrotate-asterisk`**
- Rotates `/var/log/asterisk/*.log` daily, 14-day retention, gzip compress
- `postrotate` sends `logger reload` to live Asterisk process

**`deploy/backup-db.sh`**
- Hot SQLite backup using `sqlite3 .backup` (safe while agent is running)
- 14-day rolling retention; writes to `/opt/helix/backups/`
- Designed to be called from a daily `cron` or systemd timer

### Architecture Notes
- **Postgres not migrated**: SQLite handles single-server call volume fine.
  Migrate when: multiple agent processes, >1M call log rows, or replication required.
- **ARI stays loopback**: Never proxy ARI through nginx — it carries raw audio
  WebSocket frames and must remain internal.
- **Caddy rejected**: nginx preferred for telephony due to mature WS proxying
  and battle-tested production use in VoIP environments.
- **Agent not run as root**: dedicated `helix` system user with minimal
  permissions; Asterisk runs as `asterisk` user.

---

## [latest] → v1.6

---

## [v1.6] — 2026-04-16

### Summary
Two major improvements shipped together: the onboarding script is now a full system
installer (no more manual dependency hunting), and Piper TTS is replaced with Kokoro,
a significantly higher quality 82M-parameter neural TTS model.

### Added

**Full system installer in `scripts/onboard.sh`**
- Script now installs all dependencies from scratch — no separate install guide needed
- Step 1 asks: Docker or native Linux install?
- **Docker path**: installs Docker Engine (if missing), Docker Compose plugin, confirms
  Python for helper scripts
- **Native path**: installs `asterisk`, `python3.11`, `python3.11-venv`, `espeak-ng`,
  `libespeak-ng-dev`, `ffmpeg`, `build-essential` via apt-get; creates and populates
  agent virtualenv; pre-downloads Kokoro model weights; copies Asterisk config files;
  reloads Asterisk live
- **Ollama auto-detection**: probes `localhost:11434` before asking anything. If Ollama
  is already running, it is used directly (no reinstall). If not found, offers:
  (1) install locally, (2) use a remote Ollama URL, (3) skip and configure manually
- Firewall rules added automatically (UFW or firewalld detected, LAN ports opened)
- Validation section at the end checks Ollama, espeak-ng, Kokoro import, Asterisk,
  and Docker status; prints pass/warn for each
- Final summary shows all config values and exact next-step commands
- macOS support for native mode (Homebrew)

**Kokoro TTS replaces Piper TTS**
- `agent/tts/kokoro_engine.py` — new TTS engine using Kokoro 82M parameter model
  (`pip install kokoro>=0.9.2 misaki[en]`)
- Kokoro outputs float32 at 24 kHz; engine resamples to 16 kHz PCM16 for Asterisk
  slin16 RTP. `scipy.signal.resample_poly` used for high-quality resampling.
- Pipelines are lazily loaded per language and cached in-process (no reload overhead
  between calls)
- Audio split on sentence boundaries (`split_pattern=r'[.!?]+'`) then concatenated
  for natural prosody across long utterances
- Language routing:
  - EN → `KPipeline(lang_code='a')` voice `af_heart`
  - ES → `KPipeline(lang_code='e')` voice `ef_dora`
  - FR → `KPipeline(lang_code='f')` voice `ff_siwis`
  - IT → `KPipeline(lang_code='i')` voice `if_sara`
  - DE / RO / HE → espeak-ng (Kokoro has no native support for these)
- espeak-ng path now uses Python `wave` module to parse the WAV header properly
  (fixes the v1.4 medium bug: hardcoded 44-byte header strip)
- Voice overrides per language via `KOKORO_VOICE_EN`, `KOKORO_VOICE_ES`, etc. in `.env`
- `agent/tts/piper_engine.py` retained in repo for reference but no longer imported

### Changed
- `agent/config.py` — Piper config vars replaced with Kokoro vars (`KOKORO_VOICE_*`)
- `agent/.env.example` — Piper section replaced with Kokoro section
- `agent/requirements.txt` — `piper-tts` replaced with `kokoro>=0.9.2` + `misaki[en]`
- `agent/ari_agent.py` — import changed from `piper_engine` to `kokoro_engine`
- `docker/Dockerfile.agent` — Piper binary install + 12-model-file downloads removed;
  replaced with single comment (Kokoro downloads automatically from HF); added
  `libespeak-ng-dev` for Kokoro misaki OOD phoneme fallback
- `docker/Dockerfile.agent.windows` — same Piper removal; same Kokoro note
- `scripts/onboard-windows.ps1` — updated voice model notes; TTS engine line in
  summary updated
- `README.md` — version badge v1.6; all Piper references updated to Kokoro;
  architecture diagram, env vars table, Quick Start native section, Roadmap all updated

### Removed
- All Piper binary download steps from Dockerfiles
- All 12 Piper `.onnx` / `.onnx.json` model download `RUN` commands from Dockerfiles
  (was ~60 lines of wget; replaced with one comment line)
- `PIPER_MODEL`, `PIPER_MODEL_ES/FR/IT/DE/RO/HE`, `PIPER_MODEL_PATH` config vars

---

## [v1.5] — 2026-04-16

### Summary
Bug-fix release targeting four regressions introduced in v1.4 that together broke the
multilingual experience for every FR/IT/DE/RO/HE caller on every call.

### Fixed

**Bug 1 (Critical) — `agent/llm/intent_engine.py`**
- `lang_names` dict only mapped `"en"` and `"es"`. For the 5 new languages added in
  v1.4, the LLM received a raw 2-letter code (`"fr"`, `"it"`, etc.) in the
  `BILINGUAL_ADDENDUM` system prompt instead of the full language name. LLM compliance
  with raw codes is unreliable — it would often respond in English or mix languages.
- Fix: extended `lang_names` to cover all 7 supported languages (`en`, `es`, `fr`, `it`,
  `de`, `ro`, `he`), mirroring the `LANG_NAMES` dict already present in
  `translate_engine.py`.

**Bug 2 (Critical) — `agent/ari_agent.py` — after-hours always English**
- `_handle_after_hours()` is called before `_greet()`, meaning `caller_lang` is always
  `"en"` at that point (language detection runs inside `_greet()`). All 7-language
  after-hours message dicts existed but were unreachable — every after-hours caller
  heard English regardless of their language.
- Fix: added `_after_hours_closed_msgs_all_langs()` helper that returns the closed
  message in all 7 languages as a list of `(lang, text)` tuples. `_handle_after_hours()`
  now iterates and speaks each language sequentially before branching on mode, so every
  caller hears the announcement in their own language.

**Bug 3 (High) — `agent/ari_agent.py` — schedule confirmation EN/ES only**
- After booking a callback appointment, the confirmation message used
  `if lang == "es": ... else: English`. FR/IT/DE/RO/HE callers heard English at the
  most critical moment of the scheduling flow.
- Fix: replaced the two-branch conditional with a 7-language dict
  (`_schedule_confirm`). Confirmation now speaks in the caller's detected language.

**Bug 4 (High) — `agent/ari_agent.py` — transfer message EN/ES only**
- "Let me transfer you" message used `if lang == "es": ... else: English`. Same
  two-branch pattern affected all 5 new v1.4 languages.
- Fix: replaced with `_transfer_msgs` 7-language dict.

**Bug 5 (High) — `agent/ari_agent.py` — farewell detection EN/ES only**
- `farewell_words` contained only English and Spanish goodbye words. Callers who said
  "au revoir", "auf Wiedersehen", "arrivederci", "la revedere", or "shalom" did not
  trigger a graceful farewell — the loop ran to `max_turns` and ended abruptly with no
  closing message.
- Fix: extended `farewell_words` with common goodbye phrases for all 7 languages.
  Farewell response message also converted to a 7-language dict (`_farewell_msgs`) so
  the closing line plays in the caller's language.

### Files changed
- `agent/llm/intent_engine.py` — `lang_names` extended to 7 languages
- `agent/ari_agent.py` — after-hours multilingual broadcast, schedule confirmation
  dict, transfer message dict, farewell detection + response dict

---

## [v1.4.1] — 2026-04-15

### Summary
Documentation accuracy patch. No code changes. Fixes stale and misleading content in
README.md that would trip up a fresh Ubuntu install: GPU incorrectly listed as required,
native install steps were three bare lines with no dependencies, `deploy.sh` and
`firewall.sh` were mentioned with no explanation of what they do, Piper TTS still listed
as EN+ES only despite v1.4 adding 7 languages, and a dashboard section referenced a
v1.2 tag that was long obsolete.

### Changed (`README.md`)
- **Hardware Requirements** — GPU is now correctly described as optional; CPU-only mode
  is documented with expected latency (~3-5s STT vs sub-second on GPU); onboarding
  wizard step 2 is noted as the way to choose
- **Native install section** — expanded from 3 bare lines to a full 6-step guide
  covering: system packages (`asterisk`, `python3.11`, `espeak-ng`, `ffmpeg`), Ollama
  install + model pull, Piper binary setup, Asterisk config file placement, Python
  virtualenv + `pip install`, and service startup
- **Quick Start — Docker section** — `firewall.sh` now documents what ports it opens
  (SIP 5060, RTP 10000-20100, ARI 8088, API 8000, Dashboard 3000); `deploy.sh` explains
  what it does (builds images, starts 4 services, health-waits, prints URL summary)
- **Built with table** — Piper TTS row updated from "EN + ES neural voices" to
  "6-language neural voices (EN/ES/FR/IT/DE/RO) + espeak-ng for Hebrew"
- **7-language section** — renamed from "Bilingual EN/ES support"; added bullet
  documenting that all prompts, retry messages, DTMF menus, after-hours messages, and
  operator-fallback strings are localized in all 7 languages; TTS voice matrix noted
- **Project structure** — `piper_engine.py` comment updated from "EN + ES voices" to
  "7-language dispatch + espeak-ng Hebrew fallback"
- **Dashboard table** — Settings row removed stale "v1.2" annotation
- **Version badge** — updated to v1.4.1

---

## [v1.4] — 2026-04-15

### Summary
Full 7-language support: French, Italian, German, Romanian, and Hebrew added alongside
existing English and Spanish. Every part of the audio path is language-aware — Whisper
auto-detects the caller's language, all greetings, retry prompts, after-hours messages,
voicemail prompts, DTMF menus, and operator-fallback messages are spoken in the detected
language. Piper TTS serves FR/IT/DE/RO; Hebrew falls back to espeak-ng (no Piper voice
exists for Hebrew).

### Added
- `agent/config.py` — new Piper model settings: `PIPER_MODEL_FR`, `PIPER_MODEL_IT`,
  `PIPER_MODEL_DE`, `PIPER_MODEL_RO`, `PIPER_MODEL_HE` (empty, routes to espeak-ng)
- `agent/config.py` — `SUPPORTED_LANGUAGES` default updated from `en,es` to `en,es,fr,it,de,ro,he`
- `agent/tts/piper_engine.py` — `LANG_MODEL_ATTR` dict maps all 7 language codes to
  their settings attribute; `ESPEAK_VOICES` dict handles languages without Piper support
- `agent/tts/piper_engine.py` — `_get_model_name()` helper resolves model per language;
  `synthesize_pcm()` now routes to `_synthesize_espeak()` for Hebrew automatically
- `agent/tts/piper_engine.py` — `_synthesize_espeak()` — new function; invokes espeak-ng,
  strips WAV header, resamples to 16kHz, returns raw PCM16 for Asterisk
- `agent/llm/translate_engine.py` — `LANG_NAMES` dict covers all 7 languages;
  `DETECT_PROMPT` updated to list all 7 codes as examples; `SUPPORTED_LANGS` expanded
- `agent/ari_agent.py` — `_after_hours_closed_msg()` — new helper returns closed message in
  caller's language (7 languages)
- `agent/ari_agent.py` — all after-hours append messages (emergency/voicemail/callback/schedule)
  localized in 7 languages
- `agent/ari_agent.py` — `_build_greeting()` — main and after-hours greetings in 7 languages
- `agent/ari_agent.py` — retry prompts (first and subsequent silences) in 7 languages
- `agent/ari_agent.py` — unknown-intent rephrase prompt in 7 languages
- `agent/ari_agent.py` — voicemail "please leave a message" and "thank you" prompts in 7 languages
- `agent/ari_agent.py` — DTMF invalid-option and connecting messages in 7 languages
- `agent/ari_agent.py` — operator-fallback message in 7 languages
- `agent/.env.example` — all 5 new Piper model vars documented
- `docker/Dockerfile.agent` — `espeak-ng` added to apt packages; all 5 new Piper
  voice models downloaded at image build time (FR/IT/DE/RO)
- `docker/Dockerfile.agent.windows` — same additions
- `scripts/onboard.sh` — downloads all 6 Piper voice models (EN/ES/FR/IT/DE/RO);
  installs espeak-ng for Hebrew via apt-get
- `scripts/onboard-windows.ps1` — notes that Docker handles model downloads;
  mentions espeak-ng is pre-installed in the Docker image

### Voice model choices (Piper HuggingFace)
| Language | Model | Quality |
|---|---|---|
| English | `en_US-lessac-medium` | medium |
| Spanish | `es_MX-claude-high` | high |
| French | `fr_FR-siwis-medium` | medium |
| Italian | `it_IT-paola-medium` | medium |
| German | `de_DE-thorsten-medium` | medium |
| Romanian | `ro_RO-mihai-medium` | medium |
| Hebrew | espeak-ng `he` | fallback (no Piper voice available) |

### Notes
- Language detection is handled by Whisper's multilingual model — no configuration needed
- All new languages degrade gracefully: if a model is missing, agent logs a warning and
  falls back to English
- Translation path is unchanged: caller speech → English for LLM → back to caller's language for TTS

---

## [v1.3] — 2026-04-15

### Summary
Interactive onboarding wizard for first-time setup. New users no longer need to manually
edit any config files. Two scripts — `scripts/onboard.sh` (Linux/macOS) and
`scripts/onboard-windows.ps1` (Windows PowerShell) — walk through every required setting
in a guided, step-by-step interview, write all config files automatically, install
dependencies, pull voice models, guide Google Calendar OAuth, and validate that services
are reachable before handing off to `deploy.sh`.

### Added
- `scripts/onboard.sh` — interactive guided setup for Linux/macOS (Docker and native modes)
  - 9-step wizard: deployment mode → business identity → passwords → network → extensions → after-hours → GPU/CPU → optional features → write & validate
  - Writes `agent/.env` with all 50+ variables filled in
  - Writes ARI password to `asterisk/etc/asterisk/ari.conf`
  - Writes server IP, LAN subnet, and extension passwords to `asterisk/etc/asterisk/pjsip.conf` (and `pjsip.windows.conf` if present)
  - Downloads Piper TTS binary (native mode) and EN + ES voice models from Hugging Face
  - Pulls `llama3.1:8b` from Ollama (native mode) with progress display
  - Installs Python dependencies via pip (native mode)
  - Guides Google Calendar OAuth with option to run authorization inline
  - Validates Asterisk ARI, Ollama, and Agent API reachability
  - Prints full configuration summary and next-step checklist
  - Re-runnable: safely overwrites existing config values without duplication
- `scripts/onboard-windows.ps1` — PowerShell equivalent for Windows Docker Desktop users
  - Same step-by-step prompting with Windows-native color output
  - Reads/writes `.env` via PowerShell string replacement (no `sed` dependency)
  - Prompts for secure passwords using `Read-Host -AsSecureString`
  - Optionally launches `docker compose up` and runs Ollama model pull inline
  - Health-checks all services before printing summary
  - Includes Google Calendar credentials.json guidance

### Changed
- `README.md` — Quick Start completely rewritten: onboarding wizard is now Step 1 for all platforms
- `README.md` — File structure updated to list onboarding scripts
- `.github/CONTRIBUTING.md` — Development setup now leads with onboarding wizard; legacy manual steps retained as "after onboarding" section

### Notes
- All secrets (ARI password, extension passwords) use `read -rs` / `Read-Host -AsSecureString` — never echoed to terminal
- Server IP entered during onboarding is written only to local config files, never logged or transmitted
- Script is idempotent — safe to re-run to update any setting

---

## [v1.2] — 2026-04-15

### Summary
Major enterprise-grade upgrade. Helix AI now behaves like a real business receptionist:
it respects business hours, handles after-hours callers gracefully, recovers from silence
and confusion without dead air, optionally accepts keypress fallback, routes VIP callers
directly, and logs a full structured call path for every call. All features that require
extra infrastructure (voicemail recording, call summaries, FAQ lookup) are off by default
and degrade gracefully when disabled.

### Added — Business hours & holiday management
- `_is_business_hours()` — timezone-aware check against `BUSINESS_HOURS_START/END`
- `_today_is_config_holiday()` — checks `HOLIDAY_DATES` env var (comma-separated ISO dates)
- `_today_is_db_holiday()` — checks `Holiday` table (editable via dashboard)
- `Holiday` DB model — `date`, `name`, `active`, `created_at`
- `GET/POST/DELETE /api/holidays` — full CRUD for holiday management
- Dashboard mock data for holidays (4 US federal holidays pre-seeded)
- After-hours caller flow with four configurable modes:
  - `callback` (default) — speaks closed message, advises callback
  - `voicemail` — records message as WAV, optional Whisper transcription
  - `schedule` — continues into AI scheduling flow after-hours greeting
  - `emergency` — immediately transfers to `EMERGENCY_EXTENSION`

### Added — Retry / timeout / fallback logic
- `retry_count` and `unknown_count` on `ConversationState`
- On silence: speaks bilingual retry prompt ("I didn't catch that — could you repeat?")
- After `MAX_RETRIES` consecutive silences: graceful operator transfer with spoken message
- After 2 consecutive `unknown` intents: graceful operator transfer ("Let me connect you with someone who can help")
- `SILENCE_TIMEOUT_SEC` configurable (default 8s) — was hardcoded at 5s
- `_operator_fallback(reason)` — central method for any escalation path

### Added — DTMF fallback menu
- `DTMF_ENABLED` flag (default `false`) — callers can always speak; keypress is a secondary escape hatch
- `DTMF_MAP` — configurable JSON digit→extension map (default: 1=sales, 2=support, 0=operator)
- DTMF events delivered via `ChannelDtmfReceived` on the ARI WebSocket into a per-call `asyncio.Queue`
- `[dtmf-menu]` context added to `extensions.conf` as a dialplan safety net
- DTMF menu announced in the greeting only when `DTMF_ENABLED=true`

### Added — VIP / known-caller routing
- `VIP_CALLERS` — comma-separated list of caller IDs that bypass the AI entirely
- VIP callers go directly to `OPERATOR_EXTENSION` with a personalized welcome message
- Checked before business-hours gate so VIPs always get through

### Added — Routing improvements
- `get_vip_route(caller_id)` — checks `VIP_CALLERS`, returns `RouteResult` or `None`
- `get_after_hours_route()` — returns emergency extension when `AFTER_HOURS_MODE=emergency`
- `match_source` field on `RouteResult` — logs whether match came from `db`, `config`, `default`, `vip`, or `after_hours`
- Every routing decision now logs the matched keyword, extension, source, and priority

### Added — Structured call-path logging
- `CallPath` class — records timestamped state-transition events for every call
- Events: `call_start`, `media_ready`, `vip_detected`, `after_hours`, `greeted`, `language_detected`, `utterance`, `intent_*`, `transfer`, `dtmf`, `operator_fallback`, `scheduled`, `farewell`, `voicemail_*`, `cancelled`, `error`, `teardown`
- Stored as JSON in `CallLog.notes` (existing column — no schema migration needed)
- Available via `GET /api/calls/{id}` → `notes` field

### Added — Optional feature flags
- `VOICEMAIL_ENABLED` — records after-hours WAV to `VOICEMAIL_DIR`, transcribes with Whisper
  - `VoicemailMessage` DB model — `call_id`, `caller_id`, `recorded_at`, `duration_sec`, `audio_path`, `transcript`, `status`
  - `GET/PATCH /api/voicemails`, `GET /api/voicemails/{id}`
- `CALL_SUMMARY_ENABLED` — LLM generates 2-3 sentence post-call summary, stored in `CallLog.summary`
  - `generate_call_summary()` added to `intent_engine.py`
  - Returned via `GET /api/calls/{id}` → `summary` field
- `FAQ_ENABLED` — keyword-matches caller utterance against `FAQ_FILE` (plain text, one entry per line)
  - Matching chunks injected into LLM system prompt — no vector DB required
  - `_load_faq()` cached at startup; `_find_faq_chunks()` does simple word overlap scoring
  - `faq` intent variant added to intent prompt when enabled

### Added — Admin / config API
- `PATCH /api/config` — writes selected settings back to `.env` at runtime
  - Writable fields: agent_name, business_name, hours, timezone, after_hours_mode, operator/emergency extensions, retries, DTMF, VIP callers, feature flags
  - Returns list of updated keys + restart reminder
- `GET /api/config` now returns all v1.2 settings
- `GET /api/health` now returns version + feature flag status
- Dashboard mock server updated with all new endpoints (`/api/holidays`, `/api/voicemails`, `PATCH /api/config`)

### Changed
- `ConversationState` — added `retry_count`, `unknown_count`
- `CallHandler.__init__` — added `dtmf_queue: asyncio.Queue` parameter
- `CallHandler.run()` — VIP check → business hours gate → normal flow
- `_greet()` — accepts `after_hours: bool` param; announces DTMF menu when enabled
- `_conversation_loop()` — replaced bare `no_data_count` with `retry_count` + proper retry/escalation branches
- `_listen()` — uses `SILENCE_TIMEOUT_SEC` instead of hardcoded 5s
- `run_ari_agent()` — routes `ChannelDtmfReceived` events into per-call queues; `active_calls` stores `(CallHandler, Task)` tuples
- `database.py` — `CallLog` gains `summary` column; `CallLog.notes` semantics formalized as call-path JSON
- `api.py` — version bumped to 1.2.0
- `.env.example` — fully documents all 15 new settings with explanations
- Improvement type: Multi-feature enterprise upgrade

### Files changed
- `agent/config.py` — 15 new settings
- `agent/database.py` — `Holiday`, `VoicemailMessage` models; `CallLog.summary` column
- `agent/ari_agent.py` — business hours gate, after-hours handler, retry/fallback, DTMF, VIP, structured logging, voicemail recording
- `agent/api.py` — holiday CRUD, config PATCH, voicemail endpoints
- `agent/routing/router.py` — VIP route, after-hours route, priority logging
- `agent/llm/intent_engine.py` — FAQ loader, `generate_call_summary`, `faq` intent, `retry_count`/`unknown_count` on state
- `asterisk/etc/asterisk/extensions.conf` — `[dtmf-menu]` context
- `agent/.env.example` — all new settings documented
- `dashboard/server/routes.ts` — holidays, voicemails, config PATCH mock endpoints

---

## [v1.1] — 2026-04-15

### Added
- `CHANGELOG.md` — version history tracking from this point forward
- GitHub release tags (`v1.0`, `v1.1`) for every improvement going forward

### Improvement type
Ops / project hygiene

---

## [v1.0] — 2026-04-15 (baseline)

Full initial feature set as built. Summarized below.

### Core
- Asterisk PBX with PJSIP — NAT-aware, softphone-ready (Zoiper tested)
- ARI WebSocket agent — real-time call control via Stasis
- ExternalMedia RTP bridge — bidirectional audio between Asterisk and Python agent
- SQLite database — call logs, appointments, routing rules

### AI Stack (fully local, no cloud)
- **STT:** faster-whisper with Silero VAD (replaced basic RMS energy VAD)
- **LLM:** Ollama `llama3.1:8b` — intent detection, conversation, translation
- **TTS:** Piper TTS — `en_US-lessac-medium` (English), `es_MX-claude-high` (Spanish)

### Bilingual Support (EN / ES)
- Greets in English; detects caller language from first response
- Replays greeting in Spanish if caller responds in Spanish — no double greeting
- Greeting tells caller "no buttons to press, speak naturally"
- All AI responses generated in the caller's detected language
- `TranslationRelay` for transferred calls — two isolated snoop channels (one per participant), bidirectional real-time translation so both parties hear their own language

### Smart Transfer Routing
- Each routing rule stores `agent_lang` (language spoken by the person at that extension)
- On transfer: `caller_lang == agent_lang` → plain transfer, no overhead
- On transfer: `caller_lang != agent_lang` → `TranslationRelay` starts automatically
- No hardcoded assumptions — fully data-driven per routing rule

### Scheduling
- Google Calendar integration — free/busy lookup, slot generation, event booking
- Caller can book a callback in natural conversation without pressing any keys

### Dashboard
- React + Express + Tailwind + shadcn/ui
- Pages: Dashboard (stats), Call Logs (searchable), Call Detail (transcript), Routing (CRUD), Appointments, Settings
- Dark telecom aesthetic

### Deployment
- Docker Compose for Linux (GPU / host networking)
- Docker Compose for Windows Docker Desktop (CPU / bridge networking)
- PowerShell deploy script (`deploy-windows.ps1`) — auto-detects Windows host IP
- Bash deploy script (`deploy.sh`) with pre-flight checks
- UFW firewall script for Ubuntu server

---

## Roadmap (planned)

- Barge-in / interrupt AI mid-sentence
- SMS callback confirmation
- SIP trunk integration (Twilio, VoIP.ms) for external calls
- PostgreSQL for production (replace SQLite)
- Faster translation model (Helsinki-NLP opus-mt, ~100ms vs ~2–4s)
- Additional languages (FR, DE, PT)
