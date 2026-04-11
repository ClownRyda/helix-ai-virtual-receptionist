# PBX AI Voice Assistant

A fully local AI-powered virtual receptionist built on:
- **Asterisk** (PBX, SIP, ARI)
- **faster-whisper** (local STT)
- **Ollama + Qwen3 8B** (local LLM intent/conversation)
- **Piper TTS** (local neural voice)
- **Google Calendar** (scheduling)
- **React dashboard** (management UI)

---

## Architecture

```
Caller → SIP Trunk → Asterisk (PJSIP + ARI)
                          │
                          │ ARI WebSocket + ExternalMedia RTP
                          ▼
                    Python Agent (FastAPI)
                    ├── faster-whisper (STT)
                    ├── Ollama / Qwen3 8B (intent + conversation)
                    ├── Piper TTS (voice)
                    └── Google Calendar (scheduling)
                          │
                          │ REST API
                          ▼
                    React Dashboard (port 3000)
```

## Call Flow

1. Caller dials in → Asterisk answers → `Stasis(pbx-agent)` fires
2. ARI agent creates mixing bridge + ExternalMedia RTP channel
3. Agent greets caller (Piper TTS → RTP)
4. Caller speaks → RTP audio → Whisper transcribes
5. Transcript → Ollama detects intent
6. **If schedule**: query Google Calendar → offer slots → book event
7. **If transfer**: look up routing rules → redirect to extension via ARI
8. All calls logged with full transcript to SQLite DB

---

## Quick Start

### 1. Clone and set up
```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

### 2. Configure
```bash
cp agent/.env.example agent/.env
nano agent/.env  # Set your Asterisk, Google Calendar, business settings
```

### 3. Asterisk config
Copy `asterisk/etc/asterisk/` configs to your Asterisk server (or use Docker):
```bash
# Edit pjsip.conf with your SIP provider credentials and extensions
# The defaults work for local testing with a softphone
```

### 4. Google Calendar OAuth
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable Google Calendar API
3. Create OAuth 2.0 credentials (Desktop app)
4. Download `credentials.json` → place in `agent/`
5. First run will open browser for auth → creates `token.json`

### 5. Start

**With Docker Compose:**
```bash
docker compose up -d
# Pull Ollama model on first run:
docker exec pbx-ollama ollama pull llama3.1:8b
```

**Without Docker:**
```bash
# Terminal 1: Asterisk (must already be installed)
sudo asterisk -f -vvv

# Terminal 2: Ollama
ollama serve

# Terminal 3: Python agent + API
cd agent && python main.py
```

---

## Configuration

All settings in `agent/.env`:

| Variable | Default | Description |
|---|---|---|
| `ASTERISK_HOST` | `localhost` | Asterisk server IP |
| `ASTERISK_ARI_PASSWORD` | `CHANGE_ME` | ARI password (set in ari.conf) |
| `WHISPER_MODEL` | `base.en` | STT model size (tiny/base/small/medium) |
| `WHISPER_DEVICE` | `cuda` | `cuda` or `cpu` |
| `OLLAMA_MODEL` | `llama3.1:8b` | LLM model name |
| `PIPER_MODEL` | `en_US-lessac-medium` | TTS voice |
| `AGENT_NAME` | `Alex` | Receptionist name |
| `BUSINESS_NAME` | `My Business` | Your business name |
| `BUSINESS_TIMEZONE` | `America/Chicago` | Timezone for scheduling |
| `BUSINESS_HOURS_START` | `9` | Business open hour (24h) |
| `BUSINESS_HOURS_END` | `17` | Business close hour (24h) |
| `GOOGLE_CALENDAR_ID` | `primary` | Calendar to use for scheduling |

---

## Extension Routing

Default routing rules (configurable via dashboard or DB):

| Keyword | Extension | Department |
|---|---|---|
| `sales` | 1002 | Sales |
| `billing` | 1002 | Billing → Sales |
| `support` | 1003 | Support |
| `technical` | 1003 | Technical issues |
| `operator` | 1001 | Operator/reception |

---

## SIP Credentials (for softphones)

To test with a softphone (Zoiper, Linphone, etc.):

| Field | Value |
|---|---|
| Server | Your Asterisk server IP |
| Port | 5060 |
| Username | 1001, 1002, or 1003 |
| Password | Set in `pjsip.conf` |

---

## Project Structure

```
pbx-assistant/
├── asterisk/
│   └── etc/asterisk/       # All Asterisk config files
│       ├── pjsip.conf       # SIP trunks + extensions
│       ├── extensions.conf  # Dialplan
│       ├── ari.conf         # ARI credentials
│       ├── http.conf        # ARI HTTP server
│       └── rtp.conf         # RTP port range
├── agent/
│   ├── main.py              # Entry point (FastAPI + ARI agent)
│   ├── ari_agent.py         # Core ARI event loop + call handler
│   ├── api.py               # REST API for dashboard
│   ├── config.py            # Pydantic settings
│   ├── database.py          # SQLAlchemy models
│   ├── stt/
│   │   └── whisper_engine.py
│   ├── tts/
│   │   └── piper_engine.py
│   ├── llm/
│   │   └── intent_engine.py
│   ├── calendar/
│   │   └── gcal.py
│   └── routing/
│       └── router.py
├── dashboard/               # React management UI (next step)
├── docker/
│   ├── Dockerfile.agent
│   └── Dockerfile.asterisk
├── docker-compose.yml
└── scripts/
    └── setup.sh
```

---

## Model Recommendations

Given your hardware (RTX 3080 10GB or MacBook Air M5 32GB):

| Use case | Model | VRAM |
|---|---|---|
| STT | `faster-whisper base.en` | ~1 GB |
| Intent + conversation | `llama3.1:8b` | ~5 GB |
| TTS | Piper (CPU, <100MB) | CPU only |

Total GPU usage: ~6 GB — fits comfortably on the 3080 with headroom.

For better conversation quality, try `llama3.3:70b` (needs ~9 GB) or `mistral-nemo:12b`.
