# Changelog — Helix AI Virtual Receptionist

All versions are tagged in GitHub. Latest release is always `latest`.

---

## [latest] → v1.1

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
- Voicemail fallback (no answer → record + transcribe + notify)
- SMS callback confirmation
- SIP trunk integration (Twilio, VoIP.ms) for external calls
- PostgreSQL for production (replace SQLite)
- Faster translation model (Helsinki-NLP opus-mt, ~100ms vs ~2–4s)
- Additional languages (FR, DE, PT)
