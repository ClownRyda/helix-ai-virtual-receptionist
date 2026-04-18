#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { echo "[fix-audio-fastpath] $*"; }
warn() { echo "[warn] $*" >&2; }
die()  { echo "[error] $*" >&2; exit 1; }

cleanup_on_error() {
  warn "Recent helix-agent logs:"
  journalctl -u helix-agent -n 120 --no-pager 2>/dev/null || true
}
trap cleanup_on_error ERR

[[ "${EUID}" -eq 0 ]] || die "Run with sudo: sudo bash scripts/fix-call-audio-fastpath.sh"

log "Deploying updated ari_agent.py and main.py"
install -o helix -g helix -m 0644 "$REPO_ROOT/agent/ari_agent.py" /opt/helix/agent/ari_agent.py
install -o helix -g helix -m 0644 "$REPO_ROOT/agent/main.py" /opt/helix/agent/main.py

log "Clearing Python caches"
find /opt/helix/agent -name '*.pyc' -delete
find /opt/helix/agent -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

log "Restarting helix-agent"
systemctl restart helix-agent
sleep 5

log "Health"
curl -i http://127.0.0.1:8000/api/health

log "Next step: place one test call, then run:"
echo "  sudo journalctl -u helix-agent -n 220 --no-pager"
