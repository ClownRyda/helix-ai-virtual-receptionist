#!/usr/bin/env bash
# update-live-install.sh — safely sync /opt/helix from the current repo checkout
#
# Preserves: .env, credentials.json, token.json, agent/data/, voicemail spool
# Clears:    Python bytecode cache, stale agent/calendar/ (stdlib shadow)
# Rebuilds:  dashboard (npm ci && npm run build)
# Restarts:  helix-agent, helix-dashboard
#
# Run from the repo root:
#   sudo bash scripts/update-live-install.sh
#
# Requirements: the user running this must have sudo. The helix system user
# must own /opt/helix.

set -euo pipefail

INSTALL_PATH="${HELIX_INSTALL_PATH:-/opt/helix}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[update]${NC} $*"; }
warn() { echo -e "${YELLOW}[update]${NC} $*"; }
die()  { echo -e "${RED}[update] ERROR:${NC} $*"; exit 1; }

[[ -d "$INSTALL_PATH" ]] || die "$INSTALL_PATH does not exist. Run onboard.sh first."

log "Stopping services..."
sudo systemctl stop helix-agent helix-dashboard 2>/dev/null || true

log "Removing stale agent/calendar/ if present (stdlib shadow)..."
if [[ -d "$REPO_ROOT/agent/gcal" ]] && [[ -d "$INSTALL_PATH/agent/calendar" ]]; then
    sudo rm -rf "$INSTALL_PATH/agent/calendar"
    log "Removed $INSTALL_PATH/agent/calendar"
fi

log "Syncing agent code..."
sudo rsync -a \
    --exclude='.env' \
    --exclude='credentials.json' \
    --exclude='token.json' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.venv' \
    --exclude='data/' \
    "$REPO_ROOT/agent/" "$INSTALL_PATH/agent/"

log "Clearing Python bytecode cache..."
sudo find "$INSTALL_PATH/agent" -name "*.pyc" -delete
sudo find "$INSTALL_PATH/agent" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

log "Syncing systemd units and deploy configs..."
sudo rsync -a "$REPO_ROOT/systemd/" "$INSTALL_PATH/systemd/"
sudo rsync -a "$REPO_ROOT/deploy/" "$INSTALL_PATH/deploy/"
sudo rsync -a "$REPO_ROOT/asterisk/" "$REPO_ROOT/asterisk/" 2>/dev/null || true

log "Ensuring runtime directories exist..."
sudo mkdir -p "$INSTALL_PATH/agent/data"
sudo mkdir -p /var/spool/helix/voicemail
sudo chown -R helix:helix "$INSTALL_PATH/agent/data" /var/spool/helix 2>/dev/null || true

log "Syncing dashboard source..."
sudo rsync -a \
    --exclude='node_modules' \
    --exclude='dist' \
    "$REPO_ROOT/dashboard/" "$INSTALL_PATH/dashboard/"

log "Rebuilding dashboard..."
sudo -u helix bash -c "cd $INSTALL_PATH/dashboard && npm ci && npm run build"

log "Fixing ownership..."
sudo chown -R helix:helix "$INSTALL_PATH/agent" "$INSTALL_PATH/dashboard"

log "Restarting services..."
sudo systemctl daemon-reload
sudo systemctl start helix-agent helix-dashboard

log "Waiting 4 seconds for services to settle..."
sleep 4

echo ""
sudo systemctl status helix-agent helix-dashboard --no-pager -l | head -30
echo ""
log "Done. Run: sudo journalctl -u helix-agent -n 40 --no-pager"
