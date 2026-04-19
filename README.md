# Helix AI Virtual Receptionist

![Version](https://img.shields.io/badge/version-v1.8.0-cyan)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Asterisk](https://img.shields.io/badge/asterisk-20+-orange)
![Ollama](https://img.shields.io/badge/LLM-ollama%20local-purple)
![Stars](https://img.shields.io/github/stars/BB-AI-Arena/helix-ai-virtual-receptionist?style=flat)

See [CHANGELOG.md](CHANGELOG.md) for full version history. · [Contributing](.github/CONTRIBUTING.md) · [Report a bug](../../issues/new?template=bug_report.md)

A fully local, self-hosted AI phone receptionist. Answers calls, respects your business hours, handles after-hours callers gracefully, detects intent, schedules callbacks via Google Calendar, transfers calls to the right person, speaks 7 languages (EN, ES, FR, IT, DE, RO, HE) — all without any cloud APIs.

**Server:** Ubuntu 22.04 + RTX 4090 GPU  
**Testing:** Docker Desktop on Windows or native install on Ubuntu  
**No subscriptions. No cloud. Everything runs on your hardware.**

---

## What It Does

```
Caller dials in
      ↓
VIP caller? → direct to operator (no AI)
      ↓
Business hours / holiday check
  ├── Open → normal AI greeting
  └── Closed → after-hours message
           ├── callback  → speak hours, say goodbye
           ├── voicemail → record + transcribe message
           ├── schedule  → book callback via Calendar
           └── emergency → transfer to emergency ext
      ↓
AI greets caller in English
      ↓
Whisper detects language (EN, ES, FR, IT, DE, RO, HE)
If Spanish → replay greeting in Spanish
      ↓
DTMF menu announced (if enabled) — press 1/2/0 or just speak
      ↓
Llama 3.1 determines intent
      ↓
   ┌──────────────┬──────────────────────┐
   ▼              ▼                      ▼
Schedule      Transfer              Answer info
   │              │                      │
Calendar      Route to ext         Kokoro TTS reply
books slot    (DB rules)           in caller's lang
                   │
          caller_lang ≠ agent_lang?
          TranslationRelay starts
          (both parties hear own language)
      ↓
On silence or confusion → retry prompts → operator fallback
Structured call-path log written to database
Optional: LLM call summary saved
```

---

## Architecture

```
Caller ──SIP/RTP──▶ Asterisk PBX (PJSIP + ARI)
                         │
              ARI WebSocket + ExternalMedia RTP
                         │
                         ▼
               Python Agent (FastAPI :8000)
               ├── Business hours / holiday gate
               ├── VIP caller bypass
               ├── SileroVAD              voice activity detection
               ├── faster-whisper         speech → text (GPU)
               ├── Ollama llama3.1:8b     intent + conversation + FAQ
               ├── translate_engine       EN ↔ ES via Ollama (local)
               ├── Kokoro TTS             text → speech (EN/ES/FR/IT) + espeak-ng (DE/RO/HE)
               ├── Google Calendar        scheduling
               ├── SQLite                 call logs + routing rules + holidays + voicemail
               └── CallPath logger        structured per-call event log
                         │
                    REST API
                         │
               React Dashboard (:3000)
               call logs · routing · appointments · holidays · settings
```

---

## Capabilities

### Business hours & holiday management
- Timezone-aware business hours check (configurable start/end hour)
- Weekend detection (automatically closed Sat/Sun)
- Holiday table in the database — add/remove via dashboard or API (`GET/POST/DELETE /api/holidays`)
- Hard-override holiday list in `.env` (`HOLIDAY_DATES=2026-12-25,2027-01-01`)
- Four after-hours modes: **callback**, **voicemail**, **schedule**, **emergency**

### 7-language support
- Greeting plays in English; Whisper detects language from caller's first response
- If a non-English language is detected (ES, FR, IT, DE, RO, HE) → greeting replays in that language; full conversation continues in the caller's language
- All prompts, retry messages, DTMF menus, after-hours messages, and operator fallback are localized in all 7 languages
- Greeting tells caller "no buttons to press — just speak naturally"
- All AI responses generated directly in the caller's detected language
- TTS voices: Kokoro neural voices for EN/ES/FR/IT — espeak-ng for DE/RO/HE (no Kokoro voice available)

### Live translation relay (during transfers)
After a call is transferred to a live person, if the caller and the agent speak different languages, a **TranslationRelay** starts automatically — both parties just speak normally:

```
Caller (ES) ──speaks──▶ caller_snoop channel
                              │ Whisper ES → translate ES→EN → Kokoro EN
                              ▼
                      Agent hears English

Agent (EN) ──speaks──▶ agent_snoop channel
                              │ Whisper EN → translate EN→ES → Kokoro ES
                              ▼
                      Caller hears Spanish
```

Two isolated snoop channels prevent audio mixing. Relay only starts when `caller_lang ≠ agent_lang` — same-language transfers have zero overhead.

### Retry / fallback logic
- Silence → localized retry prompt in caller's language ("I didn't catch that…" in EN/ES/FR/IT/DE/RO/HE)
- After `MAX_RETRIES` consecutive silences → graceful transfer to operator
- After 2 consecutive unknown/unclear intents → graceful transfer to operator
- No dead air — the caller always hears a spoken handoff

### DTMF fallback menu (optional)
- Off by default (`DTMF_ENABLED=false`)
- When on, the greeting adds "or press 1 for sales, 2 for support, 0 for operator"
- Callers can always speak naturally — keypress is a secondary escape hatch
- Digits delivered via ARI WebSocket into a per-call queue; `[dtmf-menu]` dialplan context is a safety net

### VIP / known-caller routing
- Set `VIP_CALLERS=+15125550100,+19725550199`
- Those numbers bypass the AI entirely → direct to `OPERATOR_EXTENSION` with a personalized welcome
- Checked before the business-hours gate so VIPs always get through

### Structured call-path logging
Every call records a timestamped JSON event log covering every state transition:
`call_start → media_ready → vip_check → greeted → language_detected → utterance → intent → transfer/schedule → teardown`
Stored in `CallLog.notes`, returned by `GET /api/calls/{id}`.

### Scheduling
Google Calendar free/busy lookup, slot generation, and event booking — all in natural conversation, no keypress menus.

### Extension routing
Rules stored in SQLite, editable live via the dashboard. Each rule stores the language of the agent at that extension — relay activates automatically on mismatch.

### Optional feature flags (all off by default)

| Flag | What it does |
|---|---|
| `VOICEMAIL_ENABLED` | Records after-hours messages as WAV; optional Whisper transcription; stored in DB |
| `CALL_SUMMARY_ENABLED` | LLM writes a 2-3 sentence post-call summary into `CallLog.summary` |
| `FAQ_ENABLED` | Keyword-matches caller utterances against `FAQ_FILE` (plain text); matching lines injected into LLM context |

All three degrade gracefully when disabled — no errors, no changed behavior.

---

## Quick Start

> **New install? Run the onboarding wizard first.** It prompts for every required value, writes all config files, and validates your setup — no manual editing needed.

### Step 0 — Clone the repo

```bash
git clone https://github.com/ClownRyda/helix-ai-virtual-receptionist.git
cd helix-ai-virtual-receptionist
```

### Step 1 — Run the onboarding wizard

**Linux / macOS (Docker or native):**
```bash
bash scripts/onboard.sh
```

**Windows (Docker Desktop):**
```powershell
# Allow running local scripts (one-time)
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

.\scripts\onboard-windows.ps1
```

The wizard will:
- Prompt for business name, timezone, hours, passwords, IP, extensions
- Write `agent/.env`, `ari.conf`, and `pjsip.conf` automatically
- Installs Kokoro TTS and all dependencies; detects and reuses existing Ollama
- Guide you through Google Calendar OAuth
- Validate that all services are reachable

### Step 2 — Start (if not already running)

**Linux (Docker):**
```bash
# One-time: open required firewall ports (SIP 5060, RTP 10000-20100, ARI 8088, API 8000, Dashboard 3000)
bash scripts/firewall.sh YOUR_LAN_SUBNET   # e.g. 192.168.1.0/24

./deploy.sh --pull   # first run: builds containers + pulls Ollama model (takes a few minutes)
./deploy.sh          # subsequent runs
```

`deploy.sh` handles: building Docker images, starting all 4 services (Asterisk, Ollama, agent, dashboard), waiting for each to become healthy, and printing a summary of URLs and extensions when ready.

**Windows (Docker Desktop):**
```powershell
.\deploy-windows.ps1 -Pull   # first run
.\deploy-windows.ps1         # subsequent runs
```

**Linux (Native — no Docker):**
```bash
# 1. System dependencies
sudo apt-get update
sudo apt-get install -y asterisk python3.11 python3.11-venv python3-pip espeak-ng libespeak-ng-dev ffmpeg

# 2. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b

# 3. Install Kokoro TTS (via pip — model weights download automatically on first use)
#    Run the onboarding wizard — it installs everything for you:
bash scripts/onboard.sh

# 4. Copy Asterisk config files
sudo cp -r asterisk/etc/asterisk/* /etc/asterisk/
sudo asterisk -rx "core reload"   # or: sudo systemctl restart asterisk

# 5. Python virtualenv + dependencies
cd agent
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 6. Start services
sudo systemctl start asterisk
ollama serve &
python main.py
```

### Step 3 — Register a softphone and dial 9999

See **[docs/zoiper-setup.md](docs/zoiper-setup.md)** for step-by-step Zoiper instructions.

### Useful commands

```bash
./deploy.sh --logs   # tail all service logs
./deploy.sh --down   # stop everything
docker exec -it pbx-asterisk asterisk -rvvv   # Asterisk CLI
```

---

## Configuration

### Step 1 — Copy and edit `.env`

```bash
cp agent/.env.example agent/.env
```

### Step 2 — Required changes

| Variable | What to set |
|---|---|
| `ASTERISK_ARI_PASSWORD` | Must match `password` in `asterisk/etc/asterisk/ari.conf` |
| `BUSINESS_NAME` | Your business name (spoken in every greeting) |
| `AGENT_NAME` | Receptionist name (default: Alex) |
| `BUSINESS_TIMEZONE` | e.g. `America/Chicago`, `America/New_York` |
| `BUSINESS_HOURS_START` | Opening hour in 24h format (default: 9) |
| `BUSINESS_HOURS_END` | Closing hour in 24h format (default: 17) |

### Full configuration reference

#### Asterisk / ARI
| Variable | Default | Description |
|---|---|---|
| `ASTERISK_HOST` | `localhost` | Asterisk IP (`asterisk` in Docker) |
| `ASTERISK_ARI_PORT` | `8088` | ARI HTTP port |
| `ASTERISK_ARI_USER` | `pbx-agent` | ARI username |
| `ASTERISK_ARI_PASSWORD` | `CHANGE_ME` | **Change this** — must match ari.conf |

#### RTP
| Variable | Default | Description |
|---|---|---|
| `AGENT_RTP_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` in Docker) |
| `AGENT_RTP_PORT_START` | `20000` | Start of agent RTP port pool |
| `AGENT_RTP_PORT_END` | `20100` | End of agent RTP port pool |
| `AGENT_RTP_ADVERTISE_HOST` | _(empty)_ | Advertise address for Asterisk (set to `agent` in Docker bridge) |

#### Voice / STT / TTS / LLM
| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `base.en` | English-only model |
| `WHISPER_MODEL_MULTILINGUAL` | `base` | Multilingual model — must not be a `.en` variant |
| `WHISPER_DEVICE` | `cuda` | `cuda` or `cpu`. If CUDA fails with `libcublas.so.12 not found`, set to `cpu` or run `sudo apt install libcublas12`. |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model for intent, conversation, translation |
| `KOKORO_VOICE_EN` | `af_heart` | Kokoro voice — English |
| `KOKORO_VOICE_ES` | `ef_dora` | Kokoro voice — Spanish |
| `KOKORO_VOICE_FR` | `ff_siwis` | Kokoro voice — French |
| `KOKORO_VOICE_IT` | `if_sara` | Kokoro voice — Italian |
| _(DE/RO/HE)_ | _(espeak-ng)_ | espeak-ng handles DE, RO, HE automatically |
| `KOKORO_VOICE_EN` | `af_heart` | Kokoro voice for English |
| `KOKORO_VOICE_ES` | `ef_dora` | Kokoro voice for Spanish |
| `KOKORO_VOICE_FR` | `ff_siwis` | Kokoro voice for French |
| `KOKORO_VOICE_IT` | `if_sara` | Kokoro voice for Italian |
| `AUTO_DETECT_LANGUAGE` | `true` | Auto-detect caller language via Whisper |

#### Business hours & after-hours
| Variable | Default | Description |
|---|---|---|
| `BUSINESS_HOURS_START` | `9` | Opening hour (24h) |
| `BUSINESS_HOURS_END` | `17` | Closing hour (24h) |
| `BUSINESS_TIMEZONE` | `America/Chicago` | tz database string |
| `HOLIDAY_DATES` | _(empty)_ | Comma-separated ISO dates: `2026-12-25,2027-01-01` |
| `AFTER_HOURS_MODE` | `callback` | `callback` \| `voicemail` \| `schedule` \| `emergency` |
| `OPERATOR_EXTENSION` | `1001` | Operator extension for fallbacks |
| `EMERGENCY_EXTENSION` | `1001` | Extension for `after_hours_mode=emergency` |

#### Retry / DTMF / VIP
| Variable | Default | Description |
|---|---|---|
| `MAX_RETRIES` | `3` | Consecutive silence events before operator transfer |
| `SILENCE_TIMEOUT_SEC` | `8` | Seconds of no audio before counting as silence |
| `DTMF_ENABLED` | `false` | Announce keypress menu in greeting |
| `DTMF_MAP` | `{"1":"1002","2":"1003","0":"1001"}` | Digit → extension mapping |
| `VIP_CALLERS` | _(empty)_ | Comma-separated caller IDs → bypass AI, direct to operator |

#### Google Calendar
| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` | OAuth2 client credentials |
| `GOOGLE_TOKEN_FILE` | `token.json` | Auto-created on first auth |
| `GOOGLE_CALENDAR_ID` | `primary` | Calendar for appointments |
| `APPOINTMENT_SLOT_MINUTES` | `30` | Duration of each slot |
| `AVAILABILITY_LOOKAHEAD_DAYS` | `7` | Days ahead to offer slots |

#### Optional feature flags
| Variable | Default | Description |
|---|---|---|
| `VOICEMAIL_ENABLED` | `false` | Record and transcribe after-hours messages |
| `VOICEMAIL_DIR` | `/var/spool/helix/voicemail` | Where WAV files are saved |
| `VOICEMAIL_TRANSCRIBE` | `true` | Transcribe with Whisper after recording |
| `CALL_SUMMARY_ENABLED` | `false` | LLM generates post-call summary |
| `FAQ_ENABLED` | `false` | Inject FAQ entries into LLM context |
| `FAQ_FILE` | `faq.txt` | Path to plain-text FAQ file (one entry per line) |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/calls` | List call logs |
| `GET` | `/api/calls/{id}` | Call detail + transcript + call-path JSON + summary |
| `GET` | `/api/stats` | Aggregate call stats |
| `GET` | `/api/rules` | List routing rules |
| `POST` | `/api/rules` | Create/update routing rule |
| `PUT` | `/api/rules/{id}` | Update routing rule |
| `DELETE` | `/api/rules/{id}` | Delete routing rule |
| `GET` | `/api/appointments` | List scheduled callbacks |
| `GET` | `/api/calendar/slots` | Available calendar slots |
| `GET` | `/api/holidays` | List holidays |
| `POST` | `/api/holidays` | Add a holiday |
| `DELETE` | `/api/holidays/{id}` | Remove a holiday |
| `GET` | `/api/config` | Current configuration |
| `PATCH` | `/api/config` | Write selected settings to `.env` |
| `GET` | `/api/voicemails` | List voicemail messages |
| `GET` | `/api/voicemails/{id}` | Voicemail detail + transcript |
| `PATCH` | `/api/voicemails/{id}` | Update voicemail status (unread/read/archived) |
| `GET` | `/api/health` | Health check + version + feature flags |

---

## Extension Routing

Default routing (editable live via the dashboard Routing page):

| Keyword | Routes to | Extension | Agent Language |
|---|---|---|---|
| sales, pricing, billing | Sales | 1002 | `en` |
| support, technical, help | Support | 1003 | `en` |
| operator, person, anyone | Operator | 1001 | `en` |

To add a Spanish-speaking agent at ext 1004:
1. Add rule: keyword `soporte` → extension `1004` → agent_lang `es`
2. Spanish caller → routes to 1004 → same language → no relay
3. English caller → routes to 1004 → different language → relay starts automatically

---

## Google Calendar Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Google Calendar API**
3. Create **OAuth 2.0 credentials** → Desktop app type
4. Download `credentials.json` → place in `agent/`
5. First run opens a browser for OAuth consent → creates `token.json`
6. Both files are in `.gitignore` — never committed

---

## Softphone Setup (Zoiper)

See **[docs/zoiper-setup.md](docs/zoiper-setup.md)** for full instructions.

| Field | Value |
|---|---|
| SIP Server | `YOUR_SERVER_IP` (or your Windows IP for Docker Desktop) |
| Port | `5060 / UDP` |
| Extension 1 | `1001` / password `test1001` |
| Extension 2 | `1002` / password `test1002` |
| Extension 3 | `1003` / password `test1003` |
| AI Receptionist | Dial **`9999`** |

---

## Dashboard

Access at `http://YOUR_SERVER_IP:3000` (server) or `http://localhost:3000` (Docker Desktop).

| Page | What it shows |
|---|---|
| Dashboard | Live stats: total calls, scheduled, transferred, after-hours, avg duration |
| Call Logs | Searchable call history with intent and disposition badges |
| Call Detail | Full transcript + structured call-path events + LLM summary |
| Routing | Keyword → extension rules with agent language (inline CRUD) |
| Appointments | Scheduled callbacks with Google Calendar status |
| Settings | Current agent configuration — all feature flags, business hours, TTS, LLM settings |

---

## Project Structure

```
helix-ai-virtual-receptionist/
├── agent/
│   ├── main.py                  Entry point — FastAPI + ARI agent
│   ├── ari_agent.py             Core call handler, business hours gate, retries,
│   │                            DTMF, VIP routing, CallPath logger, voicemail,
│   │                            TranslationRelay
│   ├── api.py                   REST API — calls, routing, holidays, config, voicemails
│   ├── config.py                All settings (Pydantic + .env), 15 new v1.2 settings
│   ├── database.py              SQLAlchemy models: CallLog, Appointment, RoutingRule,
│   │                            Holiday, VoicemailMessage
│   ├── .env.example             Fully documented template — copy to .env and edit
│   ├── stt/
│   │   └── whisper_engine.py    faster-whisper STT, returns text + detected language
│   ├── tts/
│   │   └── kokoro_engine.py     Kokoro TTS (EN/ES/FR/IT) + espeak-ng (DE/RO/HE)
│   ├── llm/
│   │   ├── intent_engine.py     Ollama intent detection, FAQ loader, call summary
│   │   └── translate_engine.py  EN ↔ ES translation via Ollama (local)
│   ├── vad/
│   │   └── silero_engine.py     Silero VAD for real-time speech detection
│   ├── calendar/
│   │   └── gcal.py              Google Calendar free/busy + booking
│   └── routing/
│       └── router.py            DB-backed routing + VIP route + after-hours route
├── asterisk/
│   └── etc/asterisk/
│       ├── pjsip.conf           SIP extensions + NAT config
│       ├── extensions.conf      Dialplan: 9999 → AI, internal ext-to-ext, [dtmf-menu]
│       ├── ari.conf             ARI credentials
│       ├── http.conf            ARI HTTP server
│       └── rtp.conf             RTP port range (10000–20000)
├── dashboard/
│   ├── client/src/pages/        React pages (Dashboard, CallLogs, Routing, Appointments, Settings)
│   └── server/                  Express API proxy + mock data (holidays, voicemails, config PATCH)
├── docker/
│   ├── docker-compose.yml       Linux/Ubuntu (GPU, host networking)
│   ├── docker-compose.windows.yml  Windows Docker Desktop (bridge networking)
│   ├── Dockerfile.agent         CUDA base for GPU Whisper
│   ├── Dockerfile.agent.windows CPU-only agent for Windows testing
│   ├── Dockerfile.asterisk      Asterisk on Ubuntu 22.04
│   └── Dockerfile.dashboard     Node.js dashboard
├── docs/
│   └── zoiper-setup.md          Step-by-step Zoiper softphone guide
├── scripts/
│   ├── onboard.sh               Interactive first-time setup wizard (Linux/macOS)
│   ├── onboard-windows.ps1      Interactive first-time setup wizard (Windows PowerShell)
│   ├── setup.sh                 Legacy bare-metal install helper
│   └── firewall.sh              UFW rules for Ubuntu server
├── deploy.sh                    One-shot Linux deploy script
└── deploy-windows.ps1           One-shot Windows PowerShell deploy script
```

---

## Hardware Requirements

**GPU is optional.** Helix AI runs on CPU-only hardware — Whisper is slower (~3-5s per utterance vs sub-second on GPU) but fully functional. The onboarding wizard asks which mode you want.

| Component | Minimum | Recommended |
|---|---|---|
| GPU | None required (CPU mode works) | NVIDIA RTX 3080+ (CUDA) |
| RAM | 8 GB | 16 GB+ |
| OS | Ubuntu 22.04 | Ubuntu 24.04 (tested/proven) |
| Disk | 10 GB | 20 GB (models + voicemail recordings) |

**Model VRAM footprint (GPU mode):**

| Component | Model | VRAM |
|---|---|---|
| STT | faster-whisper base (multilingual) | ~150 MB |
| LLM | llama3.1:8b | ~5 GB |
| TTS | Kokoro TTS (runs on CPU — no GPU needed) | 0 |
| **Total** | | **~5.2 GB** |

RTX 4090 (24 GB) handles everything with room to spare. RTX 3080 (10 GB) works fine.  
CPU-only mode: set `WHISPER_DEVICE=cpu` in `.env` (or choose option 2 in the onboarding wizard). Expect 3-5 second STT latency instead of sub-second.

**CUDA on Ubuntu 24.04:** If Whisper fails with `libcublas.so.12: cannot open shared object file`, install the missing library: `sudo apt install libcublas12`. This is a known gap between the CUDA toolkit and the Ubuntu 24.04 package split.  
Windows Docker Desktop testing always runs on CPU — slower but functional for development.

---

## Built with

| Layer | Technology |
|---|---|
| Telephony | [Asterisk 20](https://www.asterisk.org/) + PJSIP + ARI WebSocket |
| Call control | Python asyncio + `aiohttp` ARI client |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (multilingual, GPU) |
| Voice activity | [Silero VAD](https://github.com/snakers4/silero-vad) |
| LLM | [Ollama](https://ollama.com/) — `llama3.1:8b` (local, no cloud) |
| Text-to-speech | [Kokoro TTS](https://github.com/hexgrad/kokoro) — 82M parameter neural voices (EN/ES/FR/IT) + espeak-ng for DE/RO/HE |
| Scheduling | Google Calendar API (OAuth2) |
| Database | SQLite + SQLAlchemy async |
| API | FastAPI |
| Dashboard | React + Tailwind + shadcn/ui + Express |

---

## Roadmap

### ✅ Shipped

| Version | Feature |
|---|---|
| v1.0 | Asterisk PBX + ARI WebSocket integration |
| v1.0 | Whisper STT + Silero VAD |
| v1.0 | Ollama LLM (llama3.1:8b) intent detection + conversation |
| v1.0 | Neural TTS voice synthesis |
| v1.0 | Google Calendar scheduling (OAuth2) |
| v1.0 | SQLite call log + routing rules |
| v1.0 | React dashboard (calls, routing, appointments) |
| v1.0 | Docker (Linux GPU) + Docker Desktop (Windows CPU) |
| v1.1 | Bilingual EN/ES — auto language detection + replay greeting |
| v1.1 | Live translation relay during transfers (both parties hear own language) |
| v1.1 | CHANGELOG baseline + v1.0/v1.1 tags |
| v1.2 | Business hours gate + timezone-aware scheduling |
| v1.2 | Holiday management (DB + `.env` override + dashboard CRUD) |
| v1.2 | After-hours modes: callback / voicemail / schedule / emergency |
| v1.2 | Retry logic — localized silence prompts, max-retry operator fallback |
| v1.2 | DTMF keypress fallback menu |
| v1.2 | VIP caller routing (bypass AI → direct to operator) |
| v1.2 | Structured call-path logging (JSON stored per call) |
| v1.2 | Optional voicemail recording + Whisper transcription |
| v1.2 | Optional LLM post-call summary |
| v1.2 | Optional FAQ / knowledge-base lookup |
| v1.2 | Dashboard overhaul — 12+ panels (stats, routing, holidays, voicemails, config, health) |
| v1.3 | Interactive onboarding wizard — `scripts/onboard.sh` (Linux/macOS) |
| v1.3 | Interactive onboarding wizard — `scripts/onboard-windows.ps1` (Windows) |
| v1.3 | Wizard writes `.env`, `ari.conf`, `pjsip.conf` automatically |
| v1.4 | 7-language support: EN, ES, FR, IT, DE, RO, HE |
| v1.4 | Multilingual TTS voices for FR / IT / DE / RO |
| v1.4 | espeak-ng fallback for Hebrew |
| v1.6 | Kokoro TTS (82M parameter neural model) replaces Piper TTS |
| v1.6 | onboard.sh is now a full system installer (Docker + native) |
| v1.6 | Automatic Ollama detection — reuses existing local instance |
| v1.4 | All prompts, greetings, after-hours messages, DTMF menus localized in 7 languages |
| v1.6.1 | Production bare-metal hardening — all services bind to 127.0.0.1 |
| v1.6.1 | systemd units for agent, dashboard, and Ollama service override reference |
| v1.6.1 | nginx reverse proxy config (/, /api/ — ARI stays loopback-only) |
| v1.6.1 | logrotate config for Asterisk logs (14-day retention) |
| v1.6.1 | SQLite online backup script with 14-day rolling retention |
| v1.6.2 | `onboard.sh` true one-shot installer with full system setup |
| v1.6.3 | Docker hardening |
| v1.6.4 | pjsip.conf placeholder fixes, dashboard build, nginx `$connection_upgrade` map |
| v1.6.5 | `package-lock.json` committed, `npm ci` fallback, `VOICEMAIL_ENABLED` auto-set |
| v1.6.6 | `api_cors_origins` added to Settings |
| v1.6.7 | `agent/calendar/` → `agent/gcal/` (fixes Python stdlib shadow crash) |
| v1.6.7 | `onboard.sh`: rsync stale-dir cleanup, port conflict check (3000/Open WebUI) |
| v1.6.8 | Asterisk module path auto-detected for Ubuntu 24.04 multiarch layout |
| v1.6.8 | Dashboard API base changed to same-origin `/api/` — LAN browser access fixed |
| v1.6.8 | Dashboard Router scope fix — sidebar navigation works correctly |
| v1.6.9 | SQLite data dir, voicemail spool dir, `chan_sip` disabled |
| v1.7.0 | Silero VAD `trust_repo=True` — no more interactive trust prompt crash |
| v1.7.0 | `/api/config` returns Kokoro voices (was returning stale Piper fields) |
| v1.7.0 | `.env` migration script + `ARI_URL` obsolete key warning |
| v1.7.0 | `update-live-install.sh` — safe in-place upgrade script |
| v1.7.1 | `_setup_media()` step-level logging; ARI HTTP error logging |
| v1.7.2 | `StasisEnd` no longer cancels call handler during bridge transition |
| v1.7.3 | `asyncio.sleep(0)` after `create_task` — handler starts before next WS message |
| v1.7.4 | Initial `CallLog` DB insert backgrounded — `_setup_media()` no longer blocked |
| v1.7.5 | `ChannelHangupRequest` no longer cancels handler — true silent call root cause fixed |
| v1.8.0 | ExternalMedia codec switched to PCMU/ulaw; PCM16↔ulaw transcode helpers |
| v1.8.0 | RTP streamed at real-time 20 ms pacing (was burst-then-sleep) |
| v1.8.0 | `UnicastRTP/...` StasisStart events ignored (were spawning fake call handlers) |
| v1.8.0 | Whisper + Kokoro + Silero VAD all prewarmed at startup |
| v1.8.0 | `onboard.sh`: WAN IP auto-detection → `external_media_address` in `pjsip.conf` |
| v1.8.0 | `onboard.sh`: explicit final `chown -R helix:helix /opt/helix` pass |
| v1.8.0 | Dashboard: Voicemail inbox page with status badges, transcript, archive actions |
| v1.8.0 | Dashboard: 7-day call volume sparkline on home page |
| v1.8.0 | Dashboard: sidebar footer pulls live version + TTS engine from `/api/health` |
| v1.8.0 | `/api/stats/daily` endpoint: per-day call counts for last 7 days |
| v1.8.0 | README: Remote/WAN callers section; file ownership model documented |
| v1.8.0 | Secret game mode: 20-questions style guessing game with structured profile, candidate tracking, anti-repeat logic, agitation behavior |
| v1.6.1 | CORS hardened — configurable `API_CORS_ORIGINS` env var (no more wildcard) |
| v1.6.1 | RTP port overlap fix: Asterisk 10000-19999, Agent 20000-20100 |
| v1.6.1 | `asterisk/etc/asterisk/logger.conf` added (was missing — no disk logs without it) |
| v1.6.2 | `onboard.sh` Step 11: creates helix user, installs systemd units, nginx, locks .env |
| v1.6.2 | Firewall fix: no longer opens ARI/API/dashboard ports (loopback-only, behind nginx) |
| v1.6.2 | Native install next-steps updated to reference systemd + log tail commands |
| v1.6.3 | Docker dashboard no longer exposes port 3000 to network (loopback + nginx) |
| v1.6.3 | Dockerfile.asterisk + docker-compose RTP range fixed: 10000-19999 (no overlap) |
| v1.6.3 | Dockerfile.agent: Python 3.12 → 3.11, Ubuntu 24.04 (matches native installer) |
| v1.6.3 | deploy.sh no longer advertises ARI/Ollama as public URLs in post-start summary |
| v1.6.4 | onboard.sh: pjsip.conf placeholder names corrected (silent SIP config failure fixed) |
| v1.6.4 | onboard.sh: dashboard npm ci + npm run build added before systemd enable |
| v1.6.4 | nginx: $connection_upgrade map extracted to deploy/nginx-helix-map.conf (nginx -t fix) |
| v1.6.4 | onboard.sh installs nginx-helix-map.conf to conf.d/ before nginx config test |
| v1.6.5 | dashboard/package-lock.json committed — npm ci now works on fresh clones |
| v1.6.5 | onboard.sh: npm ci with lockfile fallback to npm install if lockfile absent |
| v1.6.5 | onboard.sh: VOICEMAIL_ENABLED=true auto-set when after-hours mode is voicemail |
| v1.6.6 | agent/config.py: api_cors_origins field added — pydantic crash on startup fixed |
| v1.7.0 | agent/calendar/ renamed to agent/gcal/ — Python stdlib shadowing bug fixed |
| v1.7.0 | onboard.sh: removes stale agent/calendar/ before rsync so shadow cannot survive upgrades |
| v1.7.0 | onboard.sh: pre-flight port check — detects port 3000 conflict and prompts for alternate |
| v1.7.0 | onboard.sh: creates agent/data/ and /var/spool/helix/voicemail/ — SQLite/voicemail crash fixed |
| v1.7.0 | asterisk/modules.conf: chan_sip disabled — PJSIP-only stack, no SIP port conflict |
| v1.7.0 | agent/vad/silero_engine.py: trust_repo=True — EOFError/ARI flap on first call fixed |
| v1.7.0 | agent/api.py: piper_model removed, Kokoro voices exposed in /api/config |
| v1.7.0 | scripts/onboard.sh: obsolete .env keys (ARI_URL, PIPER_MODEL) auto-removed on upgrade |
| v1.7.0 | scripts/update-live-install.sh: safe in-place upgrade script added |
| v1.7.0 | scripts/fix-live-env.sh: .env normalization/migration script added |
| v1.7.0 | asterisk.conf: hardcoded astmoddir removed — onboard.sh auto-detects correct module path |
| v1.7.0 | dashboard: API base changed to same-origin /api/ — LAN access now works correctly |
| v1.7.0 | dashboard: Router wrapper moved to include Sidebar — navigation fixed |
| v1.7.1 | agent/ari_agent.py: granular _setup_media() step logging + ARI HTTP error logging |
| v1.7.1 | agent/ari_agent.py: None guards on bridge_id/ext_media_id/rtp_sock in _setup_media() |
| v1.7.2 | agent/ari_agent.py: StasisEnd no longer cancels call handler (bridge transition fix) |
| v1.7.3 | agent/ari_agent.py: asyncio.sleep(0) after create_task so handler starts immediately |
| v1.7.4 | agent/ari_agent.py: initial CallLog insert backgrounded — _setup_media() no longer blocked |
| v1.7.4 | agent/ari_agent.py: _teardown() fallback insert prevents lost records on short calls |
| v1.7.5 | agent/ari_agent.py: ChannelHangupRequest no longer cancels handler — true silent call fix |
| v1.8.0 | scripts/onboard.sh: WAN IP auto-detection + external_media_address injection |
| v1.8.0 | scripts/onboard.sh: explicit /opt/helix chown pass + .cache dir creation |
| v1.8.0 | agent/api.py: /api/health returns tts_engine + version; /api/stats/daily added |
| v1.8.0 | agent/main.py: Silero VAD prewarm at startup |
| v1.8.0 | dashboard: Sidebar footer pulls version + TTS engine from /api/health |
| v1.8.0 | dashboard: Voicemail inbox page (Voicemails.tsx) + sidebar nav entry |
| v1.8.0 | dashboard: 7-day call volume sparkline on Dashboard home |
| v1.8.0 | README: Remote/WAN callers section |

---


## Remote / WAN Callers (Zoiper, External Softphones)

If your softphone is on a different network (mobile data, remote office, VPN),
Asterisk must advertise your **public WAN IP** in SDP — not your LAN IP.
Without this, the remote phone receives `c=IN IP4 192.168.x.x` and media
never arrives (silent call from both sides).

### Symptom
- Call connects (SIP 200 OK), agent appears to answer
- Both sides hear nothing
- Asterisk and Helix logs show no errors

### Fix — `pjsip.conf`

```ini
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060
local_net=192.168.1.0/24      ; your LAN CIDR
local_net=172.16.0.0/12
local_net=10.0.0.0/8
external_media_address=YOUR.WAN.IP.HERE
external_signaling_address=YOUR.WAN.IP.HERE
```

Find your WAN IP:
```bash
curl -s https://ifconfig.me
```

Reload Asterisk after editing:
```bash
sudo asterisk -rx "module reload res_pjsip.so"
```

**`onboard.sh` (v1.8.0+) auto-detects your WAN IP and prompts you to confirm
it before writing `pjsip.conf`.**  For existing installs, edit `pjsip.conf`
manually and reload.

### Firewall
Ensure UDP 10000–20000 (RTP) and UDP 5060 (SIP) are open to the internet:
```bash
sudo ufw allow 5060/udp
sudo ufw allow 10000:20000/udp
```

---
## File Ownership After Manual Deploys

When copying files into `/opt/helix/` manually, always restore service-critical
ownership afterward. The `helix` system user must own `.env`, the SQLite data
directory, and the model cache — or the agent crashes on startup with
`PermissionError` / `sqlite3.OperationalError`.

**Post-deploy fixup (run after every manual `cp`):**

```bash
sudo chown helix:helix /opt/helix/agent/.env \
                       /opt/helix/agent/data \
                       /opt/helix/agent/data/pbx_assistant.db \
                       /opt/helix/.cache
sudo systemctl restart helix-agent
```

**Ownership model:**

| Path | Owner | Why |
|---|---|---|
| `/opt/helix/` (dir) | `bradshaw:bradshaw` | Admin can write files without sudo |
| `/opt/helix/agent/.env` | `helix:helix` | Agent reads secrets at startup |
| `/opt/helix/agent/data/` | `helix:helix` | SQLite database writes |
| `/opt/helix/agent/data/pbx_assistant.db` | `helix:helix` | SQLite database writes |
| `/opt/helix/.cache/` | `helix:helix` | Torch/Kokoro/Silero model cache |

---

## Production Deployment (Ubuntu 24.04 — Bare Metal)

For production bare-metal deployments (no Docker), use the files in `systemd/` and `deploy/`.

### 1 — Create the `helix` system user
```bash
sudo useradd -r -s /sbin/nologin -d /opt/helix helix
sudo mkdir -p /opt/helix && sudo chown helix:helix /opt/helix
```

### 2 — Install and configure services
```bash
# Copy repo to /opt/helix
sudo cp -r . /opt/helix/
sudo chown -R helix:helix /opt/helix

# Install systemd units
sudo cp systemd/helix-agent.service /etc/systemd/system/
sudo cp systemd/helix-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now helix-agent helix-dashboard
```

### 3 — nginx reverse proxy
```bash
sudo apt install nginx -y
sudo cp deploy/nginx-helix.conf /etc/nginx/sites-available/helix
sudo ln -s /etc/nginx/sites-available/helix /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 4 — Log rotation
```bash
sudo cp deploy/logrotate-asterisk /etc/logrotate.d/asterisk
```

### 5 — Automated backups
```bash
sudo cp deploy/backup-db.sh /opt/helix/backup-db.sh
sudo chmod +x /opt/helix/backup-db.sh
# Add to crontab (runs daily at 2 AM):
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/helix/backup-db.sh") | crontab -
```

### 6 — Bind Ollama to loopback
See `systemd/ollama.service.reference` for exact override instructions.

### 7 — Firewall
```bash
bash scripts/firewall.sh   # Opens SIP (5060), RTP (10000-20100), HTTP (80), HTTPS (443)
                            # Agent (8000), ARI (8088), Dashboard (3000) stay loopback-only
```

### Port map (production)
| Service | Port | Binding |
|---|---|---|
| nginx (HTTP/HTTPS) | 80 / 443 | all interfaces |
| SIP | 5060 | all interfaces |
| RTP | 10000–19999 | all interfaces |
| Agent RTP | 20000–20100 | all interfaces |
| Asterisk ARI | 8088 | 127.0.0.1 only |
| Python Agent API | 8000 | 127.0.0.1 only |
| Dashboard | 3001 | 127.0.0.1 only (3000 reserved for Open WebUI) |
| Ollama | 11434 | 127.0.0.1 only |

---

### 🔜 Planned

- [ ] **CUDA Whisper on Ubuntu 24.04** — verify `libcublas12` install path in `onboard.sh` so GPU STT works out of the box
- [ ] **Barge-in** — interrupt AI mid-sentence when caller starts speaking
- [ ] **SIP trunk integration** — Twilio, VoIP.ms, or any ITSP for real inbound DID numbers
- [ ] **SMS callback confirmation** — text the caller a confirmation after scheduling (Twilio)
- [ ] **Faster translation** — swap Ollama translation path for Helsinki-NLP opus-mt (~100ms vs ~2s)
- [ ] **Wake-word detection** — skip VAD warmup on fast responses
- [ ] **PostgreSQL support** — drop-in swap from SQLite for production-scale deployments
- [ ] **GitHub Releases** — formal release pages with changelogs for v1.2 / v1.3 / v1.4
- [ ] **Additional languages** — Portuguese (PT), Polish (PL), Arabic (AR) when Kokoro adds support
- [ ] **Web-based onboarding** — browser UI equivalent of the onboarding wizard
