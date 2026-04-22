# Helix AI Virtual Receptionist

![Version](https://img.shields.io/badge/version-v1.9.5-cyan)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Asterisk](https://img.shields.io/badge/asterisk-20+-orange)
![Ollama](https://img.shields.io/badge/LLM-ollama%20local-purple)
![Stars](https://img.shields.io/github/stars/BB-AI-Arena/helix-ai-virtual-receptionist?style=flat)

Helix is a production-ready, self-hosted AI phone system for businesses that want more than a chatbot bolted onto a phone line. It works as an AI receptionist, multilingual front desk, live-agent routing layer, translation bridge, after-hours assistant, scheduling assistant, voicemail system, and operational dashboard in one stack.

In practical terms, Helix can:
- answer inbound calls and speak naturally with callers
- detect and switch languages during the call
- route to the right live agent based on queue, availability, and language
- translate live conversations when caller and agent do not share a language
- handle after-hours flows with callback, voicemail, scheduling, or emergency routing
- book appointments against Google Calendar
- look up callers in Vtiger CRM, create or update records, and sync call notes back to the CRM
- support normal PBX behavior like direct extension dialing, voicemail fallback, hold music, and internal extension calling
- expose call logs, routing rules, voicemails, holidays, agent state, CRM health, and outbound/campaign scaffolding in a live dashboard and API

Built for operators who care about control, privacy, and reliability, Helix runs on your own infrastructure with Asterisk ARI, Ollama, Whisper, Kokoro TTS, FastAPI, Google Calendar, optional Vtiger CRM integration, and a live operations dashboard. No subscriptions. No per-minute API billing. No external speech or LLM provider required.

**Deployment target:** bare-metal Ubuntu production, with Docker/Desktop support for testing and development  
**Runtime profile:** fully local voice AI, live agent routing, multilingual translation bridging, Google Calendar scheduling  
**Operating model:** your hardware, your SIP stack, your data, your PBX behavior

See [CHANGELOG.md](CHANGELOG.md) for full version history · [Contributing](.github/CONTRIBUTING.md) · [Report a bug](../../issues/new?template=bug_report.md)

---

## What It Does

Helix acts as the intelligent first point of contact for your business phone line. It answers inbound calls, determines what the caller needs, adapts to language automatically, and either resolves the request directly or hands the call to the right human agent with as little friction as possible.

```
Caller dials in
      ↓
VIP / priority caller? → direct to operator (no AI delay)
      ↓
Business hours / holiday policy check
  ├── Open → normal AI conversation flow
  └── Closed → after-hours handling
           ├── callback  → explain hours, offer next step
           ├── voicemail → record + transcribe message
           ├── schedule  → book callback via Calendar
           └── emergency → transfer to emergency extension
      ↓
AI greets caller
      ↓
Whisper detects language (EN, ES, FR, IT, DE, RO, HE)
Greeting and prompts adapt to caller language
      ↓
DTMF fallback announced if enabled — or just speak naturally
      ↓
LLM determines intent and next action
      ↓
   ┌──────────────┬──────────────────────┐
   ▼              ▼                      ▼
Schedule      Route to human        Answer directly
   │              │                      │
Calendar      Claim best agent     Kokoro TTS reply
books slot    / extension          in caller's language
                   │
          caller_lang ≠ agent_lang?
          TranslationRelay starts
          (both parties hear own language)
      ↓
If unclear → retry prompts → operator / fallback path
Structured call-path event log written to database
Optional: LLM call summary saved
```

---

## Architecture

The production stack is intentionally simple: Asterisk handles SIP and media control, the Python agent handles intelligence and orchestration, and the dashboard exposes operational visibility and configuration. The entire system is designed to run locally, with the AI, telephony, routing, and agent state all inside your own environment.

```
Caller ──SIP/RTP──▶ Asterisk PBX (PJSIP + ARI)
                         │
              ARI control + ExternalMedia RTP
                         │
                         ▼
               Python Agent (FastAPI :8000)
               ├── Business hours / holiday logic
               ├── VIP caller bypass
               ├── SileroVAD              voice activity detection
               ├── faster-whisper         speech → text
               ├── Ollama llama3.1:8b     intent, conversation, FAQ, translation control
               ├── translate_engine       multilingual live relay support
               ├── Kokoro TTS             neural speech output
               ├── Google Calendar        callback scheduling
               ├── SQLite                 calls, routing, holidays, voicemail, agents
               └── CallPath logger        structured per-call event log
                         │
                    REST API
                         │
               React Dashboard (:3001 → nginx :80)
               call logs · routing · appointments · holidays · voicemails · settings · agents
               React Dashboard (:3001 → nginx :80)
               call logs · routing · appointments · holidays · voicemails · settings · agents
```

---

## Capabilities

### Business hours & holiday management
- Timezone-aware business hours check (configurable start/end hour)
- Weekend detection — automatically closed Sat/Sun
- Holiday table in the database — add/remove via dashboard or API (`GET/POST/DELETE /api/holidays`)
- Hard-override holiday list in `.env` (`HOLIDAY_DATES=2026-12-25,2027-01-01`)
- Four after-hours modes: **callback**, **voicemail**, **schedule**, **emergency**

### Core PBX behavior
- Direct extension-to-extension dialing for internal users (`1001`, `1002`, `1003`)
- No-answer fallback to **Mini-Voicemail** for direct extension calls
- Built-in **Music on Hold** classes:
  - `default` = 90s R&B stream
  - `ai-news` = optional AI/talk stream
  - `local-fallback` = bundled local audio loop
- Dedicated MOH test extension: dial `*59` from any registered internal endpoint

### 7-language support
- Greeting plays in English; Whisper detects language from the caller's first response
- Non-English detected (ES, FR, IT, DE, RO, HE) → greeting replays in that language; full conversation continues in the caller's language
- All prompts, retry messages, DTMF menus, after-hours messages, and operator fallback localized in all 7 languages
- TTS voices: Kokoro neural voices for EN/ES/FR/IT — espeak-ng for DE/RO/HE

### Live translation relay (during transfers)
After a call is transferred to a live person, if the caller and the agent speak different languages, a **TranslationRelay** starts automatically on the live agent leg — both parties just speak normally:

```
Caller (ES) ──speaks──▶ caller media leg
                              │ Whisper ES → translate ES→EN → Kokoro EN
                              ▼
                      Agent hears English

Agent (EN) ──speaks──▶ agent media leg
                              │ Whisper EN → translate EN→ES → Kokoro ES
                              ▼
                      Caller hears Spanish
```

Two isolated media legs prevent audio mixing. Relay only starts when `caller_lang ≠ agent_lang` — same-language transfers have zero overhead.

### Retry / fallback logic
- Silence → localized retry prompt in caller's language ("I didn't catch that…" in all 7 languages)
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

### CRM integration
- Optional Vtiger CRM lookup and sync path built into the live call flow
- Caller phone numbers can be normalized and matched against existing CRM records
- Helix can create/update the caller record, cache the mapping locally, and append post-call notes back to Vtiger
- REST endpoints expose CRM health and caller lookup behavior for operational checks

### Outbound and campaign foundation
- Campaign model, lifecycle, dashboard pages, and API endpoints are in place
- Individual outbound proof-of-life calls can be originated through ARI from the dashboard/API
- Campaign runner, pacing, retries, and AMD are intentionally deferred; this release ships the data and control layer first

### Extension routing
Rules stored in SQLite, editable live via the dashboard. Each rule stores the language of the agent at that extension — relay activates automatically on mismatch.

### Optional feature flags

All three flags are off by default and degrade gracefully when disabled.

| Flag | What it does |
|---|---|
| `VOICEMAIL_ENABLED` | Records after-hours messages as WAV; optional Whisper transcription; stored in DB |
| `CALL_SUMMARY_ENABLED` | LLM writes a 2-3 sentence post-call summary into `CallLog.summary` |
| `FAQ_ENABLED` | Keyword-matches caller utterances against `FAQ_FILE` (plain text); matching lines injected into LLM context |

---

## Agent System

Helix includes a first-pass live human agent layer on top of the caller-side AI experience. Human agents can register in the dashboard or log in from their phone, select a preferred language, and make themselves available for inbound handoff. Inbound live-agent routing prefers queue match first, then language match, then longest-idle selection across the remaining available pool. If the caller and the selected agent speak different languages, live translation activates automatically on the agent leg.

### Feature Code Reference

| Code | Action | Notes |
|---|---|---|
| `*55` | Login + select language | Press `1=EN`, `2=ES`, `3=FR`, `4=IT`, `5=HE`, `6=RO` |
| `*56` | Set state to break | |
| `*57` | Set state to available | |
| `*58` | Set state to offline | |
| `*59` | Test default Music on Hold | Answers immediately and plays the current default MOH class |

### Agent Routing Flow

```
Inbound call
      ↓
Language detected (Whisper)
      ↓
claim_agent_for_call(caller_lang, queue)
      ↓
Atomic UPDATE: availability='available' AND current_call_id IS NULL
      ↓
┌─────────────┬─────────────────────┐
▼             ▼                     ▼
Preferred     Supported          Any available
language      language           (translation
match         match              bridge will
                                 activate)
      ↓
Tie-break: longest-idle (last_offered_at ASC)
      ↓
Agent claimed → bridge to agent leg
      ↓
caller_lang ≠ agent_lang?
├── Yes → TranslationRelay on agent leg
│         (caller hears their lang, agent hears theirs)
└── No  → Direct bridge, no relay overhead
      ↓
Call ends → release agent (current_call_id=null,
           state=available, state_changed_at=now)
```

### State Lifecycle

```
     ┌──────────┐
     │ offline  │
     └────┬─────┘
          │ *55 (login + language)
          ▼
     ┌──────────┐   *56    ┌──────────┐
     │available │◄────────►│  break   │
     └────┬─────┘   *57    └──────────┘
          │
          │ call claimed (atomic)
          ▼
     ┌──────────┐
     │   busy   │
     └────┬─────┘
          │ call ends
          ▼
     back to available
```

Agent claim uses an optimistic conditional `UPDATE` guarded by `availability_state='available' AND current_call_id IS NULL`. Two concurrent inbound calls can never claim the same agent — the losing claim retries up to 3 times with a fresh candidate query before falling back.

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
- Install Kokoro TTS and all dependencies; detect and reuse existing Ollama
- Guide you through Google Calendar OAuth
- Validate that all services are reachable

### Step 2 — Start services

**Linux (Docker):**
```bash
# One-time: open required firewall ports (SIP 5060, RTP 10000-20100, ARI 8088, API 8000, Dashboard 3001)
bash scripts/firewall.sh YOUR_LAN_SUBNET   # e.g. 192.168.1.0/24

./deploy.sh --pull   # first run: builds containers + pulls Ollama model
./deploy.sh          # subsequent runs
```

`deploy.sh` builds Docker images, starts all 4 services (Asterisk, Ollama, agent, dashboard), waits for each to become healthy, then prints a summary of URLs and extensions.

**Windows (Docker Desktop):**
```powershell
.\deploy-windows.ps1 -Pull   # first run
.\deploy-windows.ps1         # subsequent runs
```

**Linux (native — no Docker):**
```bash
# 1. System dependencies
sudo apt-get update
sudo apt-get install -y asterisk python3.11 python3.11-venv python3-pip espeak-ng libespeak-ng-dev ffmpeg

# 2. Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b

# 3. Run the onboarding wizard (installs Kokoro + all Python deps)
bash scripts/onboard.sh

# 4. Copy Asterisk config files
sudo cp -r asterisk/etc/asterisk/* /etc/asterisk/
sudo asterisk -rx "core reload"

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

#### PBX media / voicemail templates
| File | Purpose |
|---|---|
| `asterisk/etc/asterisk/extensions.conf` | Internal dialing, Mini-Voicemail fallback, feature codes, MOH test extension |
| `asterisk/etc/asterisk/minivm.conf` | Mailbox definitions for direct-extension voicemail |
| `asterisk/etc/asterisk/musiconhold.conf` | MOH class definitions (`default`, `ai-news`, `local-fallback`) |
| `asterisk/moh/default/*` | Bundled local fallback hold audio copied into `/var/lib/asterisk/moh/` during onboarding |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/calls` | List call logs |
| `GET` | `/api/calls/{id}` | Call detail + transcript + call-path JSON + summary |
| `GET` | `/api/stats` | Aggregate call stats |
| `GET` | `/api/stats/daily` | Per-day call counts for last 7 days |
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
| `GET` | `/api/health` | Health check + version + feature flags + TTS engine |
| `GET` | `/api/agents` | List all registered agents with state, language, queues |
| `POST` | `/api/agents/register` | Register a new agent |
| `PATCH` | `/api/agents/{agent_id}` | Update agent fields (language, queues, state) |
| `DELETE` | `/api/agents/{agent_id}` | Remove an agent (409 if on active call) |

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

Access at `http://YOUR_SERVER_IP` (nginx port 80 in production) or `http://localhost:3001` (direct).

| Page | What it shows |
|---|---|
| Dashboard | Live stats: total calls, scheduled, transferred, after-hours, avg duration; 7-day call volume sparkline |
| Call Logs | Searchable call history with intent and disposition badges |
| Call Detail | Full transcript + structured call-path events + LLM summary |
| Routing | Keyword → extension rules with agent language (inline CRUD) |
| Agents | Register agents, manage language/queue/state, see current call + last-offered data |
| Appointments | Scheduled callbacks with Google Calendar status |
| Voicemails | After-hours voicemail inbox with status badges, transcript, and archive actions |
| Agents | Agent roster — extensions, languages, routing assignments |
| Settings | Current agent configuration — all feature flags, business hours, TTS, LLM settings |

---

## Remote / WAN Callers

If your softphone is on a different network (mobile data, remote office, VPN), Asterisk must advertise your **public WAN IP** in SDP — not your LAN IP. Without this, the remote phone receives `c=IN IP4 192.168.x.x` and media never arrives (silent call from both sides).

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

**`onboard.sh` (v1.9.0+) auto-detects your WAN IP and prompts you to confirm
it before writing `pjsip.conf`.**  For existing installs, edit `pjsip.conf`
manually and reload.

### Firewall
```bash
sudo ufw allow 5060/udp
sudo ufw allow 10000:20000/udp
```

---

## File Ownership After Manual Deploys

When copying files into `/opt/helix/` manually, always restore service-critical ownership afterward. The `helix` system user must own `.env`, the SQLite data directory, and the model cache — or the agent crashes on startup with `PermissionError` / `sqlite3.OperationalError`.

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
| `/opt/helix/` (dir) | `youruser:youruser` | Admin can write files without sudo |
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
                            # Agent (8000), ARI (8088), Dashboard (3001) stay loopback-only
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

## Project Structure

```
helix-ai-virtual-receptionist/
├── agent/
│   ├── main.py                  Entry point — FastAPI + ARI agent
│   ├── ari_agent.py             Core call handler, business hours gate, retries,
│   │                            DTMF, VIP routing, CallPath logger, voicemail,
│   │                            TranslationRelay
│   ├── api.py                   REST API — calls, routing, holidays, config, voicemails,
│   │                            agents, campaigns, outbound test call
│   ├── config.py                All settings (Pydantic + .env)
│   ├── database.py              SQLAlchemy models: CallLog, Appointment, RoutingRule,
│   │                            Holiday, VoicemailMessage, AgentProfile, Campaign
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
│   ├── gcal/
│   │   └── gcal.py              Google Calendar free/busy + booking
│   └── routing/
│       ├── agents.py            Agent selection, atomic claim, state transitions
│       └── router.py            DB-backed routing + VIP route + after-hours route
├── asterisk/
│   ├── etc/asterisk/
│   │   ├── pjsip.conf           SIP extensions + NAT config
│   │   ├── extensions.conf      Dialplan: 9999 → AI, ext-to-ext, MiniVM fallback,
│   │   │                        feature codes, MOH test
│   │   ├── minivm.conf          Mini-Voicemail mailboxes for direct extension fallback
│   │   ├── musiconhold.conf     MOH classes: default stream + alternate classes + local fallback
│   │   ├── ari.conf             ARI credentials
│   │   ├── http.conf            ARI HTTP server
│   │   └── rtp.conf             RTP port range (10000–20000)
│   └── moh/
│       └── default/             Bundled local fallback hold audio installed to /var/lib/asterisk/moh/
├── dashboard/
│   ├── client/src/pages/        React pages (Dashboard, CallLogs, Routing, Appointments,
│   │                            Voicemails, Agents, Campaigns, OutboundCalls, Settings)
│   └── server/                  Express API proxy (holidays, voicemails, config PATCH)
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

**GPU is optional.** Helix runs on CPU-only hardware — Whisper is slower (~3-5s per utterance vs sub-second on GPU) but fully functional. The onboarding wizard asks which mode you want.

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
| TTS | Kokoro TTS (runs on CPU) | 0 |
| **Total** | | **~5.2 GB** |

RTX 4090 (24 GB) handles everything with room to spare. RTX 3080 (10 GB) works fine.

CPU-only mode: set `WHISPER_DEVICE=cpu` in `.env` (or choose option 2 in the onboarding wizard). Expect 3-5 second STT latency instead of sub-second.

**CUDA on Ubuntu 24.04:** If Whisper fails with `libcublas.so.12: cannot open shared object file`, run `sudo apt install libcublas12`. This is a known gap between the CUDA toolkit and the Ubuntu 24.04 package split.

Windows Docker Desktop testing always runs on CPU — slower but functional for development.

---

## Built With

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

### Shipped

| Version | What shipped |
|---|---|
| **v1.0** | Asterisk PBX + ARI WebSocket, Whisper STT + Silero VAD, Ollama intent detection, Kokoro TTS, Google Calendar scheduling, SQLite call log + routing rules, React dashboard, Docker (Linux GPU + Windows CPU) |
| **v1.1** | Bilingual EN/ES — auto language detection + greeting replay; live translation relay during transfers (both parties hear own language) |
| **v1.2** | Business hours gate + timezone-aware scheduling; holiday management (DB + `.env` + dashboard CRUD); four after-hours modes; retry logic with localized silence prompts; DTMF keypress menu; VIP caller routing; structured call-path logging; optional voicemail + Whisper transcription; optional LLM post-call summary; optional FAQ/knowledge-base injection; dashboard overhaul (stats, routing, holidays, voicemails, config, health) |
| **v1.3** | Interactive onboarding wizard for Linux/macOS (`onboard.sh`) and Windows (`onboard-windows.ps1`) — auto-writes `.env`, `ari.conf`, `pjsip.conf` |
| **v1.4** | 7-language support: EN, ES, FR, IT, DE, RO, HE — multilingual TTS voices (Kokoro for EN/ES/FR/IT, espeak-ng for DE/RO/HE); all prompts and messages localized |
| **v1.6** | Kokoro TTS replaces Piper TTS (82M parameter neural model); `onboard.sh` becomes full system installer; automatic Ollama detection |
| **v1.6.1–v1.6.9** | Production hardening: all services bind to 127.0.0.1; systemd units; nginx reverse proxy; logrotate; SQLite backup script; CORS hardening; RTP port overlap fix; `chan_sip` disabled; Docker dashboard loopback-only; various `onboard.sh` and config fixes |
| **v1.7.0–v1.7.5** | Silero VAD `trust_repo=True` crash fix; Kokoro voices exposed in `/api/config`; `.env` migration script; `update-live-install.sh` safe upgrade script; `StasisEnd` bridge-transition fix; `asyncio.sleep(0)` handler start fix; backgrounded initial DB insert; `ChannelHangupRequest` silent-call root cause fix |
| **v1.8.0** | ExternalMedia codec switched to PCMU/ulaw with PCM16↔ulaw transcode helpers; RTP streamed at real-time 20 ms pacing; `UnicastRTP` StasisStart events ignored; Whisper/Kokoro/Silero VAD all prewarmed at startup; WAN IP auto-detection in `onboard.sh`; dashboard voicemail inbox + 7-day sparkline + sidebar health footer; `/api/stats/daily` endpoint; Agents page added to dashboard |

### Planned

- [ ] **Barge-in** — interrupt AI mid-sentence when caller starts speaking
- [ ] **SIP trunk integration** — Twilio, VoIP.ms, or any ITSP for real inbound DID numbers
- [ ] **SMS callback confirmation** — text the caller a confirmation after scheduling
- [ ] **Faster translation** — swap Ollama translation for Helsinki-NLP opus-mt (~100 ms vs ~2 s)
- [ ] **PostgreSQL support** — drop-in swap from SQLite for production-scale deployments
- [ ] **Additional languages** — Portuguese (PT), Polish (PL), Arabic (AR) when Kokoro adds support
- [ ] **Web-based onboarding** — browser UI equivalent of the onboarding wizard
- [ ] **GitHub Releases** — formal release pages with changelogs for each milestone
