# Helix AI Virtual Receptionist

A fully local, self-hosted AI phone receptionist for Asterisk-based phone systems. It answers inbound calls, speaks with callers in English or Spanish, figures out what they need, schedules callbacks with Google Calendar, and transfers calls to the right extension when a human should take over.

This project is for people who want an on-prem phone assistant that runs on their own hardware instead of sending call audio to cloud speech or voice APIs.

**Server:** Ubuntu 22.04 + NVIDIA GPU on your LAN  
**Testing:** Docker Desktop on Windows or native install on Ubuntu  
**No subscriptions. No cloud. Everything runs on your hardware.**

---

## What This Project Is

Helix sits between your SIP callers and your team:

- A caller dials your PBX.
- Asterisk answers and hands the call to the Python agent.
- The agent listens to the caller, detects language and intent, and decides what to do next.
- It can answer basic questions, offer a callback time, or transfer the call to a configured extension.
- If the caller and employee speak different languages, it can relay the conversation between English and Spanish after the transfer.

In practice, this is a working foundation for a small-business receptionist, call router, and bilingual call assistant that stays inside your own PBX environment.

## Core Capabilities

- Answers inbound SIP calls through Asterisk and ARI
- Speaks English and Spanish with automatic caller language detection
- Handles receptionist-style conversations instead of button-based IVR menus
- Routes calls by intent such as sales, support, or operator
- Books callbacks against Google Calendar availability
- Transfers to live staff extensions
- Runs an English/Spanish translation relay after transfer when caller and staff language differ
- Stores call logs, appointments, and routing rules locally
- Exposes a dashboard for reviewing calls and editing routing behavior

## Best Fit

Helix is a good fit if you want:

- A front desk or receptionist workflow for a small business
- Natural-language call handling instead of menu trees
- English/Spanish call intake and bilingual handoff
- Local control over call audio and models
- A starting point you can customize for your own routing rules and business logic

Helix is not positioned here as a finished hosted phone platform, a turnkey enterprise contact center, or a drop-in replacement for a commercial SIP carrier stack.

---

## What Happens On A Call

```
Caller dials in
      ↓
Asterisk PBX answers
      ↓
AI greets caller in English + Spanish
      ↓
Whisper detects caller language (EN or ES)
      ↓
Llama 3.1 determines intent
      ↓
   ┌──────────────────┬──────────────────────┐
   ▼                  ▼                      ▼
Schedule          Transfer              Answer info
   │                  │                      │
Google Calendar   Routes to ext       Piper TTS reply
books appointment  (sales/support)    in caller's lang
                       │
              If caller speaks ES:
              TranslationRelay starts
              (both parties hear own language)
```

---

## System Architecture

```
Caller ──SIP/RTP──▶ Asterisk PBX (PJSIP + ARI)
                         │
              ARI WebSocket + ExternalMedia RTP
                         │
                         ▼
               Python Agent (FastAPI :8000)
               ├── SileroVAD          voice activity detection
               ├── faster-whisper     speech → text (GPU)
               ├── Ollama llama3.1:8b intent + conversation
               ├── translate_engine   EN ↔ ES via Ollama (local)
               ├── Piper TTS          text → speech (EN + ES voices)
               ├── Google Calendar    scheduling
               └── SQLite             call logs + routing rules
                         │
                    REST API
                         │
               React Dashboard (:3000)
               call logs · routing rules · appointments · settings
```

---

## Bilingual Support (EN / ES)

The system handles English and Spanish callers transparently:

### AI Attendant phase
- Greeting plays in **both English and Spanish** so the caller hears their language immediately
- Whisper auto-detects language on every turn using the multilingual `base` model
- Caller language is locked in after 2 consistent turns
- LLM responses are generated directly in the caller's language
- Piper uses `en_US-lessac-medium` for English, `es_MX-claude-high` for Spanish

### After transfer to a live person
The **TranslationRelay** kicks in — both parties just speak normally:

```
Caller (ES) ──speaks──▶ caller_snoop channel
                              │ Whisper (ES) → translate ES→EN → Piper EN
                              ▼
                      Agent hears English

Agent (EN) ──speaks──▶ agent_snoop channel
                              │ Whisper (EN) → translate EN→ES → Piper ES
                              ▼
                      Caller hears Spanish
```

Two isolated snoop channels (one per participant) prevent audio mixing. Each has its own VAD and translation loop running concurrently.

> **Latency note:** Each translation pass takes ~2–4 seconds on a modern NVIDIA GPU (Whisper + Ollama + Piper). That means live bilingual calls feel more like using a human interpreter than a zero-latency phone call.

---

## Quick Start

If you just want to see the system working, start with Docker first. If you want to run it as a real always-on service on your own server, use the native Ubuntu path.

### Option A — Windows (Docker Desktop, for testing)

```powershell
git clone https://github.com/ClownRyda/helix-ai-virtual-receptionist.git
cd helix-ai-virtual-receptionist

# First run: builds images + pulls Ollama model
.\deploy-windows.ps1 -Pull

# Subsequent runs
.\deploy-windows.ps1

# Stop
.\deploy-windows.ps1 -Down

# Watch logs
.\deploy-windows.ps1 -Logs
```

### Option B — Ubuntu Server (Docker, for testing)

```bash
git clone https://github.com/ClownRyda/helix-ai-virtual-receptionist.git
cd helix-ai-virtual-receptionist

# Open firewall ports (one-time)
bash scripts/firewall.sh

# First run: builds images + pulls Ollama model
./deploy.sh --pull

# Subsequent runs
./deploy.sh
```

### Option C — Ubuntu Server (Native / Production)

```bash
# 1. Install dependencies
bash scripts/setup.sh

# 2. Configure
cp agent/.env.example agent/.env
nano agent/.env   # set passwords, business name, timezone

# 3. Install Asterisk configs
sudo cp -r asterisk/etc/asterisk/* /etc/asterisk/
sudo asterisk -rx "core reload"

# 4. Pull Ollama model
ollama pull llama3.1:8b

# 5. Start agent
cd agent && python main.py
```

After the stack is up, register a softphone extension and dial `9999` to talk to the receptionist.

---

## Configuration

### Step 1 — Copy and edit `.env`

```bash
cp agent/.env.example agent/.env   # Linux/Mac
copy agent\.env.example agent\.env  # Windows
```

### Step 2 — Required changes

| Variable | What to set |
|---|---|
| `ASTERISK_ARI_PASSWORD` | Must match `password` in `asterisk/etc/asterisk/ari.conf` |
| `BUSINESS_NAME` | Your business name (spoken in greetings) |
| `AGENT_NAME` | Receptionist name (default: Alex) |
| `BUSINESS_TIMEZONE` | e.g. `America/Chicago`, `America/New_York` |

### Full configuration reference

#### Asterisk / ARI
| Variable | Default | Description |
|---|---|---|
| `ASTERISK_HOST` | `localhost` | Asterisk IP (`asterisk` in Docker) |
| `ASTERISK_ARI_PORT` | `8088` | ARI HTTP port |
| `ASTERISK_ARI_USER` | `pbx-agent` | ARI username (set in ari.conf) |
| `ASTERISK_ARI_PASSWORD` | `CHANGE_ME_ARI_PASSWORD` | **Change this** — must match ari.conf |
| `ASTERISK_APP_NAME` | `pbx-agent` | Stasis app name |

#### RTP
| Variable | Default | Description |
|---|---|---|
| `AGENT_RTP_HOST` | `127.0.0.1` | Bind address for agent RTP sockets (`0.0.0.0` in Docker) |
| `AGENT_RTP_PORT_START` | `20000` | Start of agent RTP port pool |
| `AGENT_RTP_PORT_END` | `20100` | End of agent RTP port pool |
| `AGENT_RTP_ADVERTISE_HOST` | _(empty)_ | Advertise address for Asterisk (set to `agent` in Docker bridge) |

#### Voice Activity Detection
| Variable | Default | Description |
|---|---|---|
| `VAD_THRESHOLD` | `0.5` | Speech probability threshold (0–1). Raise to 0.7 in noisy environments |
| `VAD_MIN_SILENCE_MS` | `600` | ms of silence before end-of-utterance |
| `VAD_SPEECH_PAD_MS` | `100` | ms padding added to speech start/end |

#### Speech-to-Text (Whisper)
| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `base.en` | Model for English-only mode |
| `WHISPER_MODEL_MULTILINGUAL` | `base` | Model used when `AUTO_DETECT_LANGUAGE=true` — **must not be a `.en` model** |
| `WHISPER_DEVICE` | `cuda` | `cuda` (GPU) or `cpu` |
| `WHISPER_COMPUTE_TYPE` | `float16` | `float16` (GPU) or `int8` (CPU) |

#### LLM (Ollama)
| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API URL (`http://ollama:11434` in Docker) |
| `OLLAMA_MODEL` | `llama3.1:8b` | Model for intent, conversation, and translation |

#### Text-to-Speech (Piper)
| Variable | Default | Description |
|---|---|---|
| `PIPER_MODEL` | `en_US-lessac-medium` | English voice |
| `PIPER_MODEL_ES` | `es_MX-claude-high` | Spanish voice |
| `PIPER_MODEL_PATH` | `/opt/piper/models` | Path to downloaded voice models |

#### Bilingual
| Variable | Default | Description |
|---|---|---|
| `SUPPORTED_LANGUAGES` | `en,es` | Comma-separated language codes |
| `AUTO_DETECT_LANGUAGE` | `true` | Auto-detect caller language via Whisper |

#### Google Calendar
| Variable | Default | Description |
|---|---|---|
| `GOOGLE_CREDENTIALS_FILE` | `credentials.json` | OAuth2 client credentials (download from Google Cloud Console) |
| `GOOGLE_TOKEN_FILE` | `token.json` | OAuth2 token (auto-created on first auth) |
| `GOOGLE_CALENDAR_ID` | `primary` | Calendar to use for appointments |
| `APPOINTMENT_SLOT_MINUTES` | `30` | Duration of each appointment slot |
| `AVAILABILITY_LOOKAHEAD_DAYS` | `7` | How many days ahead to offer slots |

#### Business
| Variable | Default | Description |
|---|---|---|
| `AGENT_NAME` | `Alex` | Receptionist name spoken in greetings |
| `BUSINESS_NAME` | `My Business` | Business name spoken in greetings |
| `BUSINESS_HOURS_START` | `9` | Opening hour (24h) |
| `BUSINESS_HOURS_END` | `17` | Closing hour (24h) |
| `BUSINESS_TIMEZONE` | `America/Chicago` | Timezone for scheduling |

#### Routing
| Variable | Default | Description |
|---|---|---|
| `ROUTING_RULES` | `{"sales":"1002",...}` | JSON keyword→extension map (also editable in dashboard) |

---

## Google Calendar Setup

Google Calendar is optional. If you skip it, the receptionist can still answer calls, detect intent, and transfer calls, but it will not be able to book callback times.

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable the **Google Calendar API**
3. Create **OAuth 2.0 credentials** → Desktop app type
4. Download `credentials.json` → place in `agent/`
5. First run opens a browser for OAuth consent → creates `token.json`
6. Both files are in `.gitignore` — never committed

---

## Softphone Setup (Zoiper)

See **[docs/zoiper-setup.md](docs/zoiper-setup.md)** for full step-by-step instructions.

Quick reference:

| Field | Value |
|---|---|
| SIP Server | `YOUR_SERVER_IP` (or your Windows IP for Docker Desktop) |
| Port | `5060 / UDP` |
| Extension 1 | `1001` / password set in `pjsip.conf` |
| Extension 2 | `1002` / password set in `pjsip.conf` |
| Extension 3 | `1003` / password set in `pjsip.conf` |
| AI Receptionist | Dial **`9999`** |

The softphone setup exists mainly so you can test the receptionist end-to-end on your LAN before connecting it to a wider phone environment.

---

## Extension Routing

The receptionist decides where to send a caller based on what they say. Default routing is editable live from the dashboard:

| Keyword caller says | Routes to | Extension | Agent Language |
|---|---|---|---|
| "sales", "pricing", "billing" | Sales | 1002 | `en` |
| "support", "technical", "help" | Support | 1003 | `en` |
| "operator", "person", "anyone" | Operator | 1001 | `en` |

### Agent Language per Extension

Each routing rule also stores the language spoken by the person at that extension (`agent_lang`). When a call is transferred, the system compares the caller's detected language to the employee's language:

```
caller_lang == agent_lang  →  plain transfer (no relay, no overhead)
caller_lang != agent_lang  →  TranslationRelay starts automatically
```

To mark an extension as Spanish-speaking, edit the routing rule in the dashboard and set **Agent Language** to `es`. No code changes are needed.

**Example:** Hire a Spanish-speaking support agent on ext 1004:
1. Add routing rule: keyword `soporte` → extension `1004` → agent_lang `es`
2. Spanish caller says "soporte" → routes to 1004 → same language → no relay
3. English caller says "soporte" → routes to 1004 → different language → relay starts automatically

---

## Project Structure

```
helix-ai-virtual-receptionist/
├── agent/
│   ├── main.py                  Entry point — FastAPI + ARI agent
│   ├── ari_agent.py             Core call handler, TranslationRelay
│   ├── api.py                   REST API for dashboard
│   ├── config.py                All settings (Pydantic + .env)
│   ├── database.py              SQLAlchemy models (CallLog, Appointment, RoutingRule)
│   ├── .env.example             Template — copy to .env and edit
│   ├── .env.windows             Pre-configured for Docker Desktop / Windows
│   ├── stt/
│   │   └── whisper_engine.py    faster-whisper STT, returns text + detected language
│   ├── tts/
│   │   └── piper_engine.py      Piper TTS, EN + ES voices
│   ├── llm/
│   │   ├── intent_engine.py     Ollama intent detection + conversation state
│   │   └── translate_engine.py  EN ↔ ES translation via Ollama (fully local)
│   ├── vad/
│   │   └── silero_engine.py     Silero VAD for real-time speech detection
│   ├── calendar/
│   │   └── gcal.py              Google Calendar free/busy + booking
│   └── routing/
│       └── router.py            DB-backed keyword → extension routing
├── asterisk/
│   └── etc/asterisk/
│       ├── pjsip.conf           SIP extensions + NAT config
│       ├── pjsip.windows.conf   Windows-specific (patched by deploy-windows.ps1)
│       ├── extensions.conf      Dialplan (9999 → AI, internal ext-to-ext)
│       ├── ari.conf             ARI credentials
│       ├── http.conf            ARI HTTP server
│       └── rtp.conf             RTP port range (10000–20000)
├── dashboard/
│   ├── client/src/pages/        React pages (Dashboard, CallLogs, Routing, Appointments, Settings)
│   └── server/                  Express API proxy + mock data
├── docker/
│   ├── docker-compose.yml       Linux/Ubuntu (GPU, host networking)
│   ├── docker-compose.windows.yml  Windows Docker Desktop (bridge networking)
│   ├── Dockerfile.agent         CUDA base image for GPU Whisper
│   ├── Dockerfile.agent.windows CPU-only agent for Windows testing
│   ├── Dockerfile.asterisk      Asterisk on Ubuntu 22.04
│   └── Dockerfile.dashboard     Node.js dashboard
├── docs/
│   └── zoiper-setup.md          Step-by-step Zoiper softphone guide
├── scripts/
│   ├── setup.sh                 Native (non-Docker) install script
│   └── firewall.sh              UFW rules for Ubuntu server
├── deploy.sh                    One-shot Linux deploy script
├── deploy-windows.ps1           One-shot Windows PowerShell deploy script
└── docker-compose.yml           Symlink → docker/docker-compose.yml
```

---

## Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| GPU | Any CUDA GPU (4GB+) | Modern NVIDIA GPU |
| RAM | 8 GB | 16 GB+ |
| OS | Ubuntu 22.04 | Ubuntu 22.04 |
| Disk | 10 GB | 20 GB (models + recordings) |

**Model footprint on GPU:**

| Component | Model | VRAM |
|---|---|---|
| STT | `faster-whisper base` (multilingual) | ~150 MB |
| LLM | `llama3.1:8b` | ~5 GB |
| TTS | Piper (CPU, no GPU needed) | 0 |
| **Total** | | **~5.2 GB** |

A 24 GB NVIDIA GPU handles all of this with room to spare. A 10 GB card is also workable for this stack.

For Windows Docker Desktop testing, everything runs on CPU — slower but functional.

---

## Dashboard

Access the dashboard at `http://YOUR_SERVER_IP:3000` (server) or `http://localhost:3000` (Docker Desktop).

The dashboard is the operator view for the system. It lets you review what happened on calls and adjust routing without editing code.

| Page | What it shows |
|---|---|
| Dashboard | Live stats: total calls, scheduled, transferred, avg duration |
| Call Logs | Searchable call history with intent badges |
| Call Detail | Full transcript per call |
| Routing | Keyword → extension rules (inline CRUD) |
| Appointments | Scheduled callbacks with Google Calendar status |
| Settings | Read-only view of current agent configuration |

---

## Roadmap

- [ ] Barge-in / interrupt AI mid-sentence
- [ ] Voicemail fallback (no answer → record + transcribe + notify)
- [ ] SMS callback confirmation via Twilio
- [ ] SIP trunk integration (Twilio, VoIP.ms) for external calls
- [ ] Swap SQLite → PostgreSQL for production
- [ ] Faster translation model (Helsinki-NLP opus-mt, ~100ms vs ~2s)
- [ ] More languages (FR, DE, PT)
- [ ] Wake-word detection to skip VAD on fast responses
