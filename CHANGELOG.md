# Changelog — Helix AI Virtual Receptionist

All versions are tagged in GitHub. Latest release is always `latest`.

---

## [latest] → v2.0.5

---

## [v2.0.5] — 2026-04-29

### Summary
Adds a Docker healthcheck for the Python agent and makes the dashboard wait for
the agent to become healthy before starting. This compose-only change is not
deployed live by itself and takes effect on the next full `docker compose up`.

### Changed
- `docker/docker-compose.yml` — adds an agent healthcheck using
  `curl -f http://localhost:8000/api/health`.
- `docker/docker-compose.yml` — changes dashboard `depends_on` to require
  `agent: condition: service_healthy`.

---

## [v2.0.4] — 2026-04-29

### Summary
Adds an operator-driven transfer control to the Dashboard active calls card and
surfaces transfer-in-progress state from the backend so duplicate transfers are
blocked while a redirect is underway.

### Added
- `agent/api.py` — `POST /api/calls/{call_id}/transfer` endpoint accepting an
  `extension` body and invoking direct `PJSIP/{extension}` redirect logic.
- `dashboard/client/src/pages/Dashboard.tsx` — per-call transfer input and
  action button for active calls.

### Changed
- `agent/ari_agent.py` — exposes `transfer_in_progress` in active call
  snapshots and adds `transfer_to_extension(...)` for direct dashboard-driven
  redirects with correct handoff/event state handling.
- `dashboard/client/src/pages/Dashboard.tsx` — disables transfer controls and
  shows a spinner label while transfer is in progress.

---

## [v2.0.3] — 2026-04-29

### Summary
Replaces the transfer/handoff polling loop with `asyncio.Event` signaling so
concurrent calls no longer wake every second waiting for handoff completion.

### Changed
- `agent/ari_agent.py` — introduces `handoff_complete` event state, uses it in
  `_wait_for_handoff_completion()`, and sets/clears the event around direct and
  translated handoff completion paths.

---

## [v2.0.2] — 2026-04-29

### Summary
Adds in-memory health history snapshots to the API and a dashboard status
history row so operators can see flapping or intermittent service degradation
instead of only the current point-in-time status.

### Added
- `agent/api.py` — module-level `deque(maxlen=60)` storing health snapshots.
- `agent/api.py` — `GET /api/health/history` endpoint returning the last 60
  status samples.
- `dashboard/client/src/pages/Dashboard.tsx` — System Status history row with
  the latest 20 samples rendered as colored dots with hover timestamps.

### Changed
- `agent/api.py` — `/api/health` now records each computed health snapshot.
- `dashboard/shared/schema.ts` — adds `checks` on `HealthStatus` and a
  `HealthHistoryEntry` type for history responses.

---

## [v2.0.1] — 2026-04-29

### Summary
Hardens `/api/calls/active` against concurrent ARI mutations by snapshotting
the active call registry before iterating it.

### Fixed
- `agent/ari_agent.py` — `get_active_calls()` now iterates over a shallow copy
  of `_active_calls` to avoid `RuntimeError: dictionary changed size during
  iteration` under call churn.

---

## [v2.0.0] — 2026-04-29

### Summary
Surfaces the existing Vtiger CRM integration settings in `/api/config` and the
dashboard so operators can enable, configure, test, and save CRM connectivity
without SSH.

### Added
- `dashboard/client/src/pages/Settings.tsx` — editable CRM section with Vtiger
  enable toggle, base URL, username, masked access key, default module
  selector, save action, and inline connection test results.

### Changed
- `agent/api.py` — `GET /api/config`, `ConfigPatch`, and `PATCH /api/config`
  now include `vtiger_enabled`, `vtiger_base_url`, `vtiger_username`,
  `vtiger_access_key`, and `vtiger_default_module`.
- `dashboard/shared/schema.ts` — `AgentConfig` now includes all Vtiger fields.

---

## [v1.9.9] — 2026-04-29

### Summary
Replaces hardcoded healthy sidebar indicators with live status derived from the
existing `/api/health` polling response.

### Changed
- `dashboard/client/src/components/Sidebar.tsx` — service dots for ARI, hold
  music, and voicemail now use live `checks.*.ok` values and expose hover
  detail strings via `title`.
- `dashboard/client/src/components/Sidebar.tsx` — top status pill now maps
  `ok`/`degraded`/`error` to green/yellow/red styling instead of always showing
  green.

---

## [v1.9.8] — 2026-04-29

### Summary
Adds a local MarianMT translation backend via CTranslate2 with automatic model
download/cache, startup prewarm, fast local language detection, and silent
fallback to Ollama when Marian is unavailable.

### Added
- `agent/llm/translate_engine.py` — MarianMT backend with lazy per-pair model
  preparation under `/opt/helix/.cache/opus-mt/`, multi-step routing via
  English when needed, and Ollama fallback on any backend failure.
- `agent/main.py` — startup prewarm for the common `es → en` translation path.
- `agent/config.py` / `agent/.env.example` — `TRANSLATION_BACKEND` setting.
- `agent/requirements.txt` — `ctranslate2`, `sentencepiece`, `transformers`,
  `huggingface-hub`, and `langdetect`.

### Changed
- `agent/llm/translate_engine.py` — language detection now prefers
  `langdetect` instead of an Ollama prompt.

---

## [v1.9.7] — 2026-04-29

### Summary
Adds optional post-call email notifications with AI summary and transcript
excerpt, triggered centrally when a call is finalized and guarded so each call
can only queue one notification.

### Added
- `agent/ari_agent.py` — `_send_call_summary_email(...)` helper and
  `_queue_call_summary_email(...)` one-shot trigger path using
  `asyncio.create_task(...)`.
- `agent/config.py` / `agent/.env.example` — `NOTIFY_EMAIL`, `SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, and `SMTP_FROM`.

### Changed
- `agent/ari_agent.py` — `_save_call()` now acts as the common finalization hook
  for notification dispatch across hangups, transfers, and voicemail paths.

---

## [v1.9.6] — 2026-04-29

### Summary
Fixes the config save path so the full dashboard/API settings surface can round
trip through `PATCH /api/config`, and aligns the shared dashboard schema with
the Kokoro TTS migration.

### Fixed
- `agent/api.py` — `ConfigPatch` now includes 13 previously missing config
  fields, and `PATCH /api/config` now maps all 13 to the correct environment
  keys instead of silently dropping them.
- `dashboard/shared/schema.ts` — removes stale `piper_model`, adds Kokoro voice
  fields, and includes the missing config properties returned by `/api/config`.

---

## [v1.9.5] — 2026-04-21

### Summary
Extends `/api/health` with live ARI connectivity and MOH/voicemail sanity
checks, and replaces the fully hardcoded System Status card in the dashboard
with one that reflects actual runtime state. Also corrects two stale labels
("Piper TTS" → live tts_engine value from health, version "v1.2" → live
version field).

### Changed
- `agent/api.py` — `/api/health` now performs three lightweight checks at
  request time: (1) HTTP GET to `ari/asterisk/info` with a 2s timeout to
  verify ARI connectivity; (2) directory listing of `/var/lib/asterisk/moh`
  to confirm at least one audio file is present; (3) `os.path.isdir` check
  on `/var/spool/asterisk/voicemail`. Results are returned as a `checks` dict
  with `ok` and `detail` fields. Overall `status` is `"ok"` / `"degraded"` /
  `"error"`. Version field updated to `"1.9.5"`.
- `dashboard/client/src/pages/Dashboard.tsx` — System Status card now reads
  live check results from `/api/health` for ARI, MOH, and voicemail spool.
  Each entry shows a live status dot and inline detail text on failure. TTS
  label reads `health.tts_engine` instead of hardcoded "Piper TTS". Version
  shows `health.version` instead of hardcoded "v1.2". Adds new "Active Calls"
  card (from v1.9.4) below System Status.

---

## [v1.9.4] — 2026-04-21

### Summary
Wires the in-memory `active_calls` registry in the ARI agent runtime to the
dashboard via a new `/api/calls/active` endpoint and a live-polling card on
the Dashboard home. Callers appear within 5 seconds of pickup and their
elapsed duration ticks up in real time using a per-row client-side timer.

### Added
- `agent/ari_agent.py` — `_active_calls` promoted from a local variable inside
  `run_ari_agent()` to a module-level dict. `get_active_calls()` accessor
  returns a snapshot list of `{call_id, channel_id, caller_id, started_at,
  elapsed_seconds}` for all in-progress non-done tasks.
- `agent/api.py` — `GET /api/calls/active` endpoint: imports and calls
  `get_active_calls()`, returns the snapshot. No DB query; reads only
  in-memory runtime state.
- `dashboard/client/src/pages/Dashboard.tsx` — `ActiveCall` interface,
  `useLiveElapsed` hook (ticks elapsed seconds every second via `setInterval`),
  `ActiveCallRow` component, and a new "Active Calls" card below System Status
  that polls `/api/calls/active` every 5 seconds. Shows "No active calls" when
  idle; shows caller ID + live ticking duration for each in-progress call.

---

## [v1.9.3] — 2026-04-21

### Summary
`_port_lock` was declared as an `asyncio.Lock()` but `_allocate_rtp_port()`
was a plain synchronous function that never acquired it. Two concurrent callers
could both read the same RTP port as unallocated and both add it to `_port_pool`
in the same event-loop tick, resulting in one-way or missing audio on one call
with no error logged.

### Fixed
- `agent/ari_agent.py` — `_allocate_rtp_port()` converted from `def` to
  `async def`. The pool scan and add are now wrapped in `async with _port_lock:`
  so the read-check-add is atomic across all concurrent coroutines.
- `agent/ari_agent.py` — Both call sites updated to `await _allocate_rtp_port()`
  (lines previously inside `_setup_media()` at two code paths).

---

## [v1.9.2] — 2026-04-19

### Summary
Replaces the full-table Python row-scan in `/api/stats` and `/api/stats/daily`
with SQL aggregate queries. Both endpoints previously loaded every `CallLog` row
into Python memory and iterated to compute totals. At scale (thousands of calls)
this caused unnecessary DB load and high memory usage. The new implementation
uses a single `SELECT COUNT / SUM(CASE...) / AVG` for `/api/stats` and a
`GROUP BY strftime('%Y-%m-%d', ...)` for `/api/stats/daily` — O(1) memory
regardless of table size.

### Fixed
- `agent/api.py` — `/api/stats`: replaced `select(CallLog)` full scan + Python
  aggregation with a single SQL `COUNT / SUM(CASE) / AVG` query via SQLAlchemy
  `func`. Memory usage is now constant regardless of call log size.
- `agent/api.py` — `/api/stats/daily`: replaced full scan + Python date bucketing
  with `GROUP BY func.strftime('%Y-%m-%d', CallLog.started_at)`. A 7-day date
  scaffold is built in Python to fill in zero-count days not returned by the DB.
  Works on both ISO string and native datetime column storage (SQLite compatible).

---

## [v1.9.1] — 2026-04-19

### Summary
`onboard.sh` now performs a CUDA preflight check when the user selects GPU mode.
On Ubuntu 24.04, `libcublas.so.12` is not automatically installed by the NVIDIA
driver or CUDA toolkit meta-packages, which caused faster-whisper to silently
fall back to CPU inference (3-5s STT latency instead of sub-second). The
installer now detects this gap, offers to install `libcublas12` automatically,
and runs a Whisper CUDA smoke-test at the end. If the smoke-test fails, it
patches `.env` to `WHISPER_DEVICE=cpu` so the service does not crash-loop, and
prints clear recovery instructions.

### Added
- `scripts/onboard.sh` — GPU mode now runs `ldconfig -p | grep libcublas.so.12`
  before proceeding. If missing, prompts the user to install `libcublas12` via
  `apt-get` and re-checks after install.
- `scripts/onboard.sh` — Post-install Whisper CUDA smoke-test (native installs
  only): loads `faster-whisper tiny` on CUDA inside the `helix` venv. If it
  passes, prints "GPU inference confirmed." If it fails, patches `.env` to
  `WHISPER_DEVICE=cpu` automatically and warns the user.
- Addresses the live server issue where the RTX 4090 was running Whisper on CPU
  because `libcublas12` was not installed on Ubuntu 24.04.

---

## [v1.9.0] — 2026-04-18

### Summary
Documentation and product-surface release for the hardened agent routing MVP.
Adds persistent human agent state, atomic claim semantics for live handoff,
PBX feature-code login/state changes, agent management API endpoints, and
dashboard controls. Also documents the live agent translation bridge path, which
now runs on the actual agent leg instead of only the older transfer-to-extension
flow.

### Added
- `agent/database.py`: `AgentProfile` persistent model for human agents — extension mapping, preferred/supported languages, assigned queues, presence state
- `agent/routing/agents.py`: atomic `claim_agent_for_call(...)` using optimistic conditional `UPDATE` with 3 retries
- `agent/routing/agents.py`: `state_changed_at` tracked on every availability transition and claim/release
- `agent/ari_agent.py`: live-agent routing precedence — agent claim wins, keyword router only runs when no agent is claimed
- `agent/ari_agent.py`: release paths cover dial failure, caller hangup, normal teardown, and agent-leg `ChannelDestroyed`
- `asterisk/etc/asterisk/extensions.conf`: `*55` login + language select, `*56` break, `*57` available, `*58` offline — all via ARI/Stasis
- `agent/api.py`: `GET /api/agents`, `POST /api/agents/register`, `PATCH /api/agents/{agent_id}`, `DELETE /api/agents/{agent_id}`
- `agent/api.py`: busy agents reject delete with `409`
- `dashboard/client/src/pages/Agents.tsx`: `/agents` page for add/register/edit agent state, language, queues
- `dashboard/`: sidebar `Agents` entry + Agent Pool summary card on the home page
- `agent/database.py`: inline SQLite startup schema patch — adds `state_changed_at` to existing `agent_profiles` tables without Alembic

### Routing behavior
- Selection order: queue match first, then preferred language, then supported language, then any available agent
- Tie-breaker: longest-idle (`last_offered_at ASC`, `NULLS FIRST` semantics via Python sort)
- Translation bridge activates automatically when caller and claimed agent speak different languages
- Same-language claims bridge directly with no relay overhead

---

## [v1.8.0] — 2026-04-18

### Summary
Batch improvement release covering the remaining post-audio-fix hardening and
dashboard features. Key items: `onboard.sh` now auto-detects the public WAN IP
and writes `external_media_address` / `external_signaling_address` into
`pjsip.conf` — the root cause of the silent-call-from-remote-softphone issue
that hit this install. Silero VAD is now prewarmed at startup alongside Whisper
and Kokoro so no model loading happens on a live call path. The dashboard gains
a Voicemail inbox page, a 7-day call volume sparkline, and a live-updating
sidebar footer that pulls version and TTS engine name from `/api/health`.

### Confirmed working on bare-metal Ubuntu 24.04 (RTX 4090)
- Dashboard through nginx port 80 → Express 3001 → FastAPI 8000
- Asterisk PJSIP registration, 1001 → 9999 dial path
- AI greeting audible to remote caller (Zoiper on WAN)
- Caller speech transcribed and responded to
- Full AI conversation loop working end-to-end

### Known live host issues (not blocking)
- Whisper running on CPU (`WHISPER_DEVICE=cpu`) — `libcublas.so.12` missing on
  this Ubuntu 24.04 install. Fix: `sudo apt install libcublas12`. STT works
  on CPU but with higher latency (~3-5s vs sub-second on GPU).
- `/opt/helix/.cache` has permission warnings — non-fatal, models load from
  cache correctly.

### Added
- `agent/api.py`: `/api/health` returns `tts_engine` + `version: "1.8.0"`
- `agent/api.py`: `/api/stats/daily` — per-day call counts for last 7 days
- `agent/main.py`: Silero VAD prewarmed at startup
- `dashboard/`: Voicemail inbox page (`Voicemails.tsx`) + sidebar nav + route
- `dashboard/`: 7-day call volume sparkline (Recharts) on Dashboard home
- `dashboard/`: Sidebar footer reads live version + TTS engine from `/api/health`
- `scripts/onboard.sh`: WAN IP auto-detection + `pjsip.conf` external address injection
- `scripts/onboard.sh`: explicit final `chown -R helix:helix /opt/helix` + `.cache` pass
- `README.md`: Remote/WAN callers section; file ownership model; Ubuntu 24.04 CUDA note

### Secret game mode (experimental, live only)
- Trigger phrase: "super secret game mode"
- Detects caller language, runs a 20-questions style guessing game
- Features: structured candidate profile, anti-repeat logic, agitation behavior
  near the end, non-repeating fallback question ladder
- Committed in `agent/llm/intent_engine.py`

---

## [v1.7.5]

---

## [v1.7.5] — 2026-04-18

### Summary
Root cause of the silent call bug found and fixed. `ChannelHangupRequest` was
cancelling the call handler task before `run()` got to execute past `Call started`.
Import-path verification confirmed the correct file was loaded, and the extra
trace logs added manually on the server confirmed `run()` never advanced beyond
the first log line despite the code being present. Cause: the Silero VAD load
(even from cache) takes ~1 event-loop tick, during which `ChannelHangupRequest`
arrives in the WebSocket buffer. The WS receive loop picks it up immediately
after `asyncio.sleep(0)` yields, calls `task.cancel()`, and the handler is dead
before it logs anything further. Fix: remove `task.cancel()` from
`ChannelHangupRequest` entirely. `ChannelDestroyed` is the authoritative hangup
signal and always follows; it remains the sole cancellation trigger.

### Fixed

**`agent/ari_agent.py` — `ChannelHangupRequest` cancels handler before it runs (true silent call root cause)**
- `run_ari_agent()` was calling `task.cancel()` on both `ChannelHangupRequest`
  and `ChannelDestroyed`. `ChannelHangupRequest` fires when the far end sends
  BYE but the channel is not yet destroyed. If the handler task hadn't had a
  chance to advance (Silero VAD cache load, initial DB task spawn), the cancel
  raced ahead of `run()` and killed it before any `_setup_media` log could fire.
- Fix: `ChannelHangupRequest` is now log-only. `task.cancel()` is removed from
  that branch entirely. `ChannelDestroyed` (which always follows) remains the
  sole place where the handler task is cancelled and cleaned up from
  `active_calls`.
- Comment block explains the race in detail for future maintainers.

---

## [v1.7.4] — 2026-04-18

### Summary
Critical fix for the silent call bug: callers heard silence and hung up before
Helix ever answered. Root cause — the initial `CallLog` DB write was on the
critical path between `Call started` and `_setup_media()`. An aiosqlite delay
(WAL flush / lock contention) was sufficient for the caller to hang up before
media setup started, causing `ChannelHangupRequest` to cancel the task first.
Fix: background the initial DB insert via `asyncio.create_task` and call
`_setup_media()` immediately. `_teardown()` gains a fallback insert so no
call record is ever lost even on very short/cancelled calls.

### Fixed

**`agent/ari_agent.py` — Initial `CallLog` insert blocks `_setup_media()` (silent call root cause)**
- `CallHandler.run()` awaited `db.commit()` for the initial call log row before
  calling `_setup_media()`. Any aiosqlite latency (WAL flush, lock contention)
  delayed media setup by the same amount. Callers heard silence during this
  window; if they hung up, `ChannelHangupRequest` cancelled the task before
  `_setup_media()` ever executed — explaining why `_setup_media: RTP socket
  bound` never appeared in logs despite v1.7.1+ code being confirmed deployed.
- Fix: wrapped the initial insert in a nested async function and fire-and-forget
  it with `asyncio.create_task()`. `_setup_media()` is now called immediately
  after `Call started` with no DB round-trip on the critical path.
- The comment block in code documents the reasoning explicitly for future
  maintainers.

**`agent/ari_agent.py` — `_teardown()` silently drops call record if background insert races**
- If a call is cancelled before the background insert task completes (very
  short call, immediate hangup), `_teardown()`'s `select(CallLog)` would find
  no row and the `if cl:` guard would silently skip the update — losing the
  call record entirely.
- Fix: added an `else` branch that inserts a minimal `CallLog` row with
  `disposition="cancelled"` and the full call path JSON so no call is ever
  dropped from history, regardless of insert timing.

---

## [v1.7.3] — 2026-04-18

### Summary
Fixes a race where `ChannelHangupRequest` could cancel the `CallHandler` task
before it executed a single line. `asyncio.create_task()` schedules the
coroutine but does not run it until the event loop gets a chance to yield.
Added `await asyncio.sleep(0)` immediately after `create_task()` in the ARI
event loop so the handler starts before the next WebSocket message is processed.

### Fixed
- `run_ari_agent`: added `await asyncio.sleep(0)` after `asyncio.create_task(handler.run())`
  so the handler coroutine begins executing before the ws receive loop processes
  the next event (which may be `ChannelHangupRequest`).

---

## [v1.7.2] — 2026-04-18

### Summary
`StasisEnd` was incorrectly cancelling the call handler task when the caller
channel was moved into a mixing bridge (a normal ARI operation). This caused
all calls to terminate at bridge setup. Fixed by making `StasisEnd` log-only;
call teardown is now exclusively driven by `ChannelDestroyed`.

### Fixed
- `run_ari_agent`: `StasisEnd` no longer calls `task.cancel()` or removes the
  handler from `active_calls`. Teardown is driven by `ChannelDestroyed` only.

---

## [v1.7.1] — 2026-04-18

### Summary
Added granular step-level logging throughout `_setup_media()` (RTP socket bound,
bridge created, caller added, ExternalMedia created, UNICASTRTP vars, both
channels in bridge) and improved ARI HTTP error logging to capture status code
and response body on any non-2xx reply.

### Added
- `agent/ari_agent.py`: `_setup_media()` now logs each step with `log.info`
  so it is possible to identify exactly which ARI call stalls or fails.
- `agent/ari_agent.py`: `ARIClient.post()` logs status code + body on error.
- `agent/ari_agent.py`: `None` guards on `bridge_id`, `ext_media_id`, and
  `rtp_sock` before use in `_setup_media()` with clear `RuntimeError` messages.

---

## [v1.7.0] — 2026-04-18

### Summary
First-call reliability release. Fixes three bugs that prevented any call from
being handled successfully on a first-boot bare-metal install: Silero VAD
blocking on stdin trust prompt (ARI crash loop), `/api/config` crashing with
AttributeError on the removed `piper_model` field, and stale obsolete `.env`
keys causing pydantic ValidationError on agent startup. Also adds two utility
scripts for safe in-place upgrades and `.env` normalization.

### Fixed

**`agent/vad/silero_engine.py` — Silero VAD blocks stdin on first load (EOFError / ARI flap)**
- `torch.hub.load()` without `trust_repo=True` prompts an interactive
  "Do you trust this repository?" question on the first call if the model
  has not been cached. In a systemd service there is no stdin, so the prompt
  blocks indefinitely and then raises `EOFError: EOF when reading a line`.
- This caused the agent to crash immediately after receiving `StasisStart`,
  producing the observed ARI WebSocket connect-disconnect flapping loop and
  silent calls from the caller's perspective.
- Fix: added `trust_repo=True` to `torch.hub.load()`. Safe for production —
  the repository is pinned by name and the model hash is validated by torch.

**`agent/api.py` — `/api/config` crashes with AttributeError after Kokoro migration**
- The `GET /api/config` endpoint still referenced `settings.piper_model`,
  which was removed from the `Settings` model when Kokoro replaced Piper in
  v1.6. Any dashboard page or API client fetching config would trigger:
  `AttributeError: 'Settings' object has no attribute 'piper_model'`.
- Fix: removed `piper_model` from the response. Added `kokoro_voice_en/es/fr/it`
  fields reflecting the current TTS engine's configuration.

**`scripts/onboard.sh` — obsolete `.env` keys cause pydantic crash on upgrade**
- Users upgrading from older installs may have `ARI_URL`, `PIPER_MODEL`,
  `PIPER_VOICE`, or `TTS_ENGINE` in their live `.env`. pydantic `Settings`
  raises `ValidationError: Extra inputs are not permitted` on any unknown key,
  crashing the agent before it starts.
- Fix: `onboard.sh` now scrubs these keys from the deployed `.env` during the
  install/upgrade step, with a warning message for each removed key.
- Also strips inline shell comments from value lines (e.g. `KEY=val  # note`)
  which python-dotenv may misparse.

### Added

**`scripts/update-live-install.sh` — safe in-place upgrade script**
- Syncs agent code, systemd units, and dashboard from the repo to `/opt/helix`
  while preserving `.env`, credentials, DB, and voicemail recordings.
- Removes stale `agent/calendar/`, clears bytecode cache, rebuilds the
  dashboard, and restarts services.
- Replaces the manual multi-step recovery sequence used during initial
  bare-metal debug sessions.

**`scripts/fix-live-env.sh` — `.env` normalization / migration script**
- Removes obsolete keys, strips inline comments, deduplicates repeated keys.
- Safe to run on any live install; backs up `.env` before modifying.

---

## [v1.6.9] — 2026-04-16

### Summary
Fixes two additional bare-metal blockers found during live deployment:
SQLite crash on first boot due to missing `agent/data/` directory, and
`chan_sip` loading alongside PJSIP causing SIP stack interference.

### Fixed

**`scripts/onboard.sh` — SQLite `data/` directory never created**
- `.env.example` sets `DATABASE_URL=sqlite+aiosqlite:///./data/pbx_assistant.db`
  but `onboard.sh` never created `/opt/helix/agent/data/`. SQLAlchemy throws
  `OperationalError: unable to open database file` on first agent startup.
- Fix: onboard.sh now creates `$INSTALL_PATH/agent/data/` (chmod 750, helix:helix)
  during the install step, before starting services.
- Also creates `/var/spool/helix/voicemail/` (used by VOICEMAIL_ENABLED=true)
  which had the same missing-directory problem.

**`asterisk/etc/asterisk/modules.conf` — chan_sip loads alongside PJSIP**
- Asterisk autoloads `chan_sip.so` by default. With Helix using PJSIP exclusively,
  chan_sip competing for port 5060 creates SIP registration ambiguity and
  complicates debugging (some clients may negotiate with the wrong driver).
- Fix: added `modules.conf` to the repo with `noload => chan_sip.so` so Helix
  installs run a clean PJSIP-only SIP stack.

---

## [v1.6.8] — 2026-04-16

### Summary
Fixes three bare-metal production blockers found during live Ubuntu 24.04
deployment: Asterisk startup failure due to wrong module path, dashboard
navigation broken due to router scope, and dashboard API calls failing from
any LAN machine due to hardcoded localhost origin.

### Fixed

**`asterisk/etc/asterisk/asterisk.conf` — hardcoded module path breaks Ubuntu 24.04**
- Repo shipped `astmoddir => /usr/lib/asterisk/modules` which does not exist
  on Ubuntu 24.04 apt installs. The real path is
  `/usr/lib/x86_64-linux-gnu/asterisk/modules` (multiarch layout).
- Asterisk exited immediately on startup: `Unable to open modules directory`.
- Fix: removed `astmoddir` from the shipped `asterisk.conf` (Asterisk uses
  its compiled-in default if the key is absent). `onboard.sh` now detects
  the correct path at install time and injects `astmoddir => <detected>` after
  copying the config, with fallback candidates for x86_64, aarch64, and legacy.

**`dashboard/client/src/lib/queryClient.ts` — hardcoded localhost:8000 breaks LAN access**
- `API_BASE` defaulted to `http://localhost:8000`. When a user opened the
  dashboard from another machine on the LAN, `localhost` resolved to the
  client machine rather than the server, causing all API calls to silently
  fail (routing rules appeared to do nothing, stats wouldn’t load, etc.).
- Fix: default is now `""` (empty string), producing same-origin relative
  paths (`/api/calls`, `/api/stats`, etc.). nginx already proxies `/api/`
  to `127.0.0.1:8000`. Override with `VITE_API_URL` for local dev only.

**`dashboard/client/src/App.tsx` — Router scope excluded Sidebar (navigation broken)**
- `<Sidebar />` was rendered outside the `<Router hook={useHashLocation}>`
  wrapper. Wouter’s `<Link>` components in the sidebar had no location
  context, so clicking any nav item stayed on the current page.
- Fix: moved `<Router>` to wrap both `<Sidebar />` and the `<Switch>` block
  so all nav links share the same hash-location context.

---

## [v1.6.7] — 2026-04-16

### Summary
Fixes a Python stdlib shadowing bug that crashes the agent on all bare-metal
installs once the Google Calendar code path is reached, adds stale-directory
cleanup to the installer so the old `calendar/` package can never survive an
upgrade rsync, and adds a pre-flight port check so dashboard port conflicts
are caught and resolved before deployment.

### Fixed

**`agent/calendar/` → `agent/gcal/` — stdlib shadowing (affects all installs)**
- The agent shipped a package directory named `calendar/` inside `agent/`.
  Python resolves local packages before stdlib, so any `import calendar` by
  the agent or its dependencies loaded the app package instead of the stdlib
  module, causing `AttributeError` or `ImportError` failures whenever a
  Google Calendar operation was attempted.
- Fix: renamed `agent/calendar/` → `agent/gcal/`.
- Updated all imports: `from calendar.gcal import …` → `from gcal.gcal import …`
  in `agent/api.py` and `agent/ari_agent.py`.

**`scripts/onboard.sh` — stale `calendar/` package survives upgrade rsync**
- `rsync` without `--delete` preserves directories that exist in the target
  but not in the source. A previous install's `agent/calendar/` would survive
  an in-place upgrade and continue shadowing the stdlib even after the rename
  landed in the repo.
- Fix: before rsync, `onboard.sh` now removes `$INSTALL_PATH/agent/calendar/`
  when the source tree contains `agent/gcal/`.

### Added

**`scripts/onboard.sh` — pre-flight dashboard port check**
- If port 3000 is already bound on the host when the systemd units are being
  installed, the installer detects this, warns the user, and prompts for an
  alternate port (default: 3001).
- It then patches `helix-dashboard.service` (`PORT=3000` → alternate) and
  `nginx-helix.conf` (upstream `127.0.0.1:3000` → alternate) before writing
  the units to `/etc/systemd/system/`.
- Eliminates the silent 502 / bind failure that occurs when another service
  (e.g. a dev server) already occupies port 3000.

---

## [v1.6.6] — 2026-04-16

### Summary
Fixes a startup crash introduced when `API_CORS_ORIGINS` is present in `.env`.
The key was used in `api.py` via `os.environ` but never declared in the pydantic
`Settings` model, causing a `ValidationError: Extra inputs are not permitted` on
every agent boot.

### Fixed

**`agent/config.py` — `api_cors_origins` missing from `Settings` model**
- `pydantic_settings` rejects any `.env` key not declared in the `Settings` class.
  `API_CORS_ORIGINS` was already written by `onboard.sh` and consumed by `api.py`,
  but the missing field declaration caused a hard crash at import time.
- Fix: added `api_cors_origins: str` field with default
  `"http://127.0.0.1,http://localhost"` matching what the installer writes.

---

## [v1.6.5] — 2026-04-16

### Summary
Fixes the dashboard build failure on first install (missing `package-lock.json`)
and a silent voicemail misconfiguration (after-hours mode set to `voicemail` but
`VOICEMAIL_ENABLED` left `false` in `.env`).

### Fixed

**`scripts/onboard.sh` — dashboard `npm ci` fails without lockfile**
- `npm ci` requires `package-lock.json` to exist and aborts if it is missing.
  Fresh clones had no lockfile, so the dashboard build step failed immediately.
- Fix A: `dashboard/package-lock.json` is now committed to the repo (313 KB);
  `npm ci` works on all fresh clones going forward.
- Fix B: `onboard.sh` now checks for the lockfile before choosing between
  `npm ci` (fast, reproducible) and `npm install` (fallback, generates lockfile).
  Either way the build completes.
- Recovery command printed in warning if `dist/index.cjs` is still missing after build.

**`scripts/onboard.sh` — voicemail mode selected but not enabled**
- Choosing `AFTER_HOURS_MODE=voicemail` in the installer did not set
  `VOICEMAIL_ENABLED=true`. The agent would hit the voicemail path and silently
  do nothing because recording was disabled.
- Fix: after writing `AFTER_HOURS_MODE` to `.env`, the installer now
  automatically sets `VOICEMAIL_ENABLED=true` when mode is `voicemail`.

### Added
- `dashboard/package-lock.json` — committed to repo; `npm ci` now works on
  all fresh installs without a network resolution step.
- `.gitignore` — `dashboard/package-lock.json` line removed (was blocking the fix).

---

## [latest] → v1.6.4

---

## [v1.6.4] — 2026-04-16

### Summary
Fixes four install blockers that would have caused a silent partial install or an
nginx config failure on a fresh native deployment. The installer can now be run
end-to-end on a clean Ubuntu 24.04 server.

### Fixed

**Critical: `scripts/onboard.sh` — wrong pjsip.conf placeholder names**
- Replaced `CHANGE_ME_EXT1001` → `CHANGE_ME_EXT_1001_PASSWORD` (and 1002, 1003)
- Replaced `CHANGE_ME_SERVER_IP` → `YOUR_SERVER_IP` (matches actual placeholder)
- LAN subnet: replaced broken `CHANGE_ME_LAN_SUBNET` token with a targeted
  `sed` that replaces `local_net=192.168.0.0/16` (the default catch-all line)
  with the user's actual CIDR; RFC-1918 fallbacks (172.16, 10.0) are preserved
- Without this fix the installer finished successfully but left all SIP
  extension passwords and the server IP as literal placeholder strings

**Critical: `scripts/onboard.sh` — missing dashboard build step**
- Added "Building dashboard (native)" section before systemd unit install
- Installs Node.js LTS via NodeSource if not present
- Runs `npm ci --ignore-scripts` then `npm run build` as the `helix` user
- Verifies `dist/index.cjs` exists after build; warns with manual fallback if not
- Without this fix `helix-dashboard.service` would start but immediately fail
  because `dist/index.cjs` does not exist in a fresh clone

**Critical: nginx `$connection_upgrade` undefined variable**
- `deploy/nginx-helix.conf` referenced `$connection_upgrade` which requires
  a `map` directive in nginx's `http` context. Without the map, `nginx -t`
  fails and nginx will not start.
- Fix: renamed variable to `$helix_connection_upgrade` (avoids collision with
  any existing nginx maps) and added new `deploy/nginx-helix-map.conf`
- `onboard.sh` now copies the map file to `/etc/nginx/conf.d/helix-map.conf`
  before running `nginx -t`. Inline fallback writes the map if the file is
  somehow missing.

**Minor: `scripts/onboard.sh` — HELIX_VERSION was v1.6.2 (stale)**
- Bumped to `v1.6.4` (shown in banner and final summary)

### Added
- `deploy/nginx-helix-map.conf` — new file; contains the `$helix_connection_upgrade`
  map directive for nginx WebSocket proxying. Must be installed in `conf.d/`.

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
