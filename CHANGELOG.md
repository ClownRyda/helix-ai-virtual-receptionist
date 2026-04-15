# Changelog — Helix AI Virtual Receptionist

All versions are tagged in GitHub. Latest release is always `latest`.

---

## [latest] → v1.2

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
