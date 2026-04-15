---
name: Bug report
about: Something isn't working correctly
title: '[BUG] '
labels: bug
assignees: ''
---

## What happened?
<!-- Clear description of the bug -->

## Expected behavior
<!-- What should have happened instead? -->

## Steps to reproduce
1. 
2. 
3. 

## Environment
- **Version:** (check `GET /api/health` → `version` field, or `git describe --tags`)
- **Deploy mode:** [ ] Native Ubuntu  [ ] Docker Linux  [ ] Docker Windows Desktop
- **GPU:** (e.g. RTX 4090, CPU-only)
- **Ollama model:** (e.g. `llama3.1:8b`)
- **Whisper model:** (e.g. `base`, `base.en`)

## Relevant logs
<!-- Paste agent logs here. Run with: `python agent/main.py` or `docker compose logs agent` -->
```
paste logs here
```

## Additional context
<!-- Screenshots, call transcripts, call-path JSON from /api/calls/{id} → notes field, etc. -->
