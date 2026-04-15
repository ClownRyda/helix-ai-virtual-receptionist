# Contributing to Helix AI Virtual Receptionist

Thank you for your interest in contributing. This document covers how the project is structured and how to submit changes cleanly.

---

## Project philosophy

- **AI-first, not IVR-first.** The caller speaks naturally; keypress menus are a fallback, not the primary interface.
- **Fully local.** No cloud APIs in the call path. Everything runs on your hardware.
- **Extend, don't replace.** Changes should extend the existing call state machine in `agent/ari_agent.py` rather than introducing a parallel implementation.
- **No hardcoded secrets.** All credentials go through `.env` / Pydantic settings in `agent/config.py`.
- **Bilingual by default.** EN/ES must continue to work after any change to the audio or LLM path.

---

## Repository layout

```
agent/              Python agent (ARI, STT, TTS, LLM, routing, API)
asterisk/           Asterisk configuration files
dashboard/          React + Express dashboard
docker/             Dockerfiles and Compose files
docs/               Setup guides
scripts/            Install and firewall scripts
```

---

## Development setup

### Native (recommended for agent development)

```bash
# Python agent
cd agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit
python main.py

# Dashboard
cd dashboard
npm install
npm run dev
```

### Docker (for integration testing)

```bash
./deploy.sh --pull        # Linux
.\deploy-windows.ps1 -Pull  # Windows
```

---

## Making changes

1. **Read the relevant code first.** The call flow lives in `agent/ari_agent.py`. Configuration lives in `agent/config.py`. All new settings must go through Pydantic and be documented in `agent/.env.example`.

2. **One improvement per commit.** Keep commits scoped and descriptive.

3. **Update `CHANGELOG.md`.** Every user-visible change gets a changelog entry. Follow the existing format: version header, category (Added / Changed / Fixed), bullet points.

4. **Bump the version.** Versions follow `1.x` incrementing. Update:
   - `CHANGELOG.md` header
   - `agent/api.py` → `version="x.y.z"`
   - `README.md` badge
   - Git tag: `git tag vX.Y && git tag -f latest`

5. **Test the call path end-to-end** before submitting. At minimum:
   - English caller → intent detected → response spoken
   - Spanish caller → language detected → response in Spanish
   - After-hours call → correct mode behavior
   - Silence × 3 → operator fallback

6. **No IP addresses, passwords, or personal info** in any committed file.

---

## Submitting a pull request

- Target the `main` branch
- Include a clear description of what changed and why
- Reference any related issues
- Ensure `python -m py_compile agent/*.py agent/**/*.py` passes with no errors

---

## Commit message format

```
Short summary (under 72 chars)

Longer description if needed. Explain what changed and why,
not just what the diff shows. Reference the patch number if
this is part of a larger upgrade (e.g. "Patch 3 of v1.2").

Files changed:
- agent/ari_agent.py — what and why
- agent/config.py — what and why
```
