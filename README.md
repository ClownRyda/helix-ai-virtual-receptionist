# Helix AI Virtual Receptionist

![Version](https://img.shields.io/badge/version-v1.4-cyan)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Asterisk](https://img.shields.io/badge/asterisk-20+-orange)
![Ollama](https://img.shields.io/badge/LLM-ollama%20local-purple)
![Stars](https://img.shields.io/github/stars/ClownRyda/helix-ai-virtual-receptionist?style=flat)

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
Calendar      Route to ext         Piper TTS reply
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
               ├── Piper TTS              text → speech (EN + ES voices)
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

### Bilingual EN / ES support
- Greeting plays in English; Whisper detects language from caller's first response
- If a non-English language is detected (ES, FR, IT, DE, RO, HE) → greeting replays in that language; full conversation continues in the caller's language
- Greeting tells caller "no buttons to press — just speak naturally"
- All AI responses generated directly in the caller's detected language

### Live translation relay (during transfers)
After a call is transferred to a live person, if the caller and the agent speak different languages, a **TranslationRelay** starts automatically — both parties just speak normally:

```
Caller (ES) ──speaks──▶ caller_snoop channel
                              │ Whisper ES → translate ES→EN → Piper EN
                              ▼
                      Agent hears English

Agent (EN) ──speaks──▶ agent_snoop channel
                              │ Whisper EN → translate EN→ES → Piper ES
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
- Optionally install Piper TTS voice models and pull the Ollama model
- Guide you through Google Calendar OAuth
- Validate that all services are reachable

### Step 2 — Start (if not already running)

**Linux (Docker):**
```bash
bash scripts/firewall.sh   # open ports (one-time)
./deploy.sh --pull         # first run: build + pull LLM
./deploy.sh                # subsequent runs
```

**Windows (Docker Desktop):**
```powershell
.\deploy-windows.ps1 -Pull   # first run
.\deploy-windows.ps1         # subsequent runs
```

**Linux (Native):**
```bash
sudo systemctl start asterisk
ollama serve &
cd agent && python main.py
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
| `WHISPER_DEVICE` | `cuda` | `cuda` or `cpu` |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model for intent, conversation, translation |
| `PIPER_MODEL` | `en_US-lessac-medium` | English TTS voice |
| `PIPER_MODEL_ES` | `es_MX-claude-high` | Spanish TTS voice |
| `PIPER_MODEL_FR` | `fr_FR-siwis-medium` | French TTS voice |
| `PIPER_MODEL_IT` | `it_IT-paola-medium` | Italian TTS voice |
| `PIPER_MODEL_DE` | `de_DE-thorsten-medium` | German TTS voice |
| `PIPER_MODEL_RO` | `ro_RO-mihai-medium` | Romanian TTS voice |
| `PIPER_MODEL_HE` | _(espeak-ng fallback)_ | Hebrew TTS (no Piper model available) |
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
| Settings | Current agent configuration (v1.2: all new settings included) |

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
│   │   └── piper_engine.py      Piper TTS, EN + ES voices
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

| Component | Minimum | Recommended |
|---|---|---|
| GPU | Any CUDA GPU (4 GB+) | RTX 4090 |
| RAM | 8 GB | 16 GB+ |
| OS | Ubuntu 22.04 | Ubuntu 22.04 |
| Disk | 10 GB | 20 GB (models + voicemail recordings) |

**Model VRAM footprint:**

| Component | Model | VRAM |
|---|---|---|
| STT | faster-whisper base (multilingual) | ~150 MB |
| LLM | llama3.1:8b | ~5 GB |
| TTS | Piper (CPU, no GPU needed) | 0 |
| **Total** | | **~5.2 GB** |

RTX 4090 (24 GB) handles everything with room to spare. Also works on a 3080 (10 GB).  
Windows Docker Desktop testing runs on CPU — slower but functional.

---

## Built with

| Layer | Technology |
|---|---|
| Telephony | [Asterisk 20](https://www.asterisk.org/) + PJSIP + ARI WebSocket |
| Call control | Python asyncio + `aiohttp` ARI client |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (multilingual, GPU) |
| Voice activity | [Silero VAD](https://github.com/snakers4/silero-vad) |
| LLM | [Ollama](https://ollama.com/) — `llama3.1:8b` (local, no cloud) |
| Text-to-speech | [Piper TTS](https://github.com/rhasspy/piper) — EN + ES neural voices |
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
| v1.0 | Piper TTS — neural voice synthesis |
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
| v1.4 | Piper TTS voices for FR / IT / DE / RO |
| v1.4 | espeak-ng fallback for Hebrew (no Piper voice available) |
| v1.4 | All prompts, greetings, after-hours messages, DTMF menus localized in 7 languages |

---

### 🔜 Planned

- [ ] **Barge-in** — interrupt AI mid-sentence when caller starts speaking
- [ ] **SIP trunk integration** — Twilio, VoIP.ms, or any ITSP for real inbound DID numbers
- [ ] **SMS callback confirmation** — text the caller a confirmation after scheduling (Twilio)
- [ ] **Faster translation** — swap Ollama translation path for Helsinki-NLP opus-mt (~100ms vs ~2s)
- [ ] **Wake-word detection** — skip VAD warmup on fast responses
- [ ] **PostgreSQL support** — drop-in swap from SQLite for production-scale deployments
- [ ] **Dashboard Voicemails page** — in-browser playback + transcript view
- [ ] **GitHub Releases** — formal release pages with changelogs for v1.2 / v1.3 / v1.4
- [ ] **Additional languages** — Portuguese (PT), Polish (PL), Arabic (AR) when Piper voices become available
- [ ] **Web-based onboarding** — browser UI equivalent of the onboarding wizard
