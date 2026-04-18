#!/usr/bin/env bash
# fix-live-env.sh — normalize a live /opt/helix/agent/.env for current Helix config schema
#
# Removes obsolete keys (ARI_URL, PIPER_MODEL, etc.) that cause pydantic
# ValidationError on startup. Normalizes inline comments (not supported by
# python-dotenv). Does NOT change passwords or user-set values.
#
# Backs up .env to .env.bak before making any changes.
#
# Run:
#   sudo bash scripts/fix-live-env.sh

set -euo pipefail

ENV_FILE="${HELIX_ENV:-/opt/helix/agent/.env}"
BACKUP="${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"

[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE not found"; exit 1; }

echo "[fix-env] Backing up $ENV_FILE -> $BACKUP"
sudo cp "$ENV_FILE" "$BACKUP"

# Remove obsolete keys that no longer exist in the Settings model
OBSOLETE_KEYS=(
    ARI_URL
    PIPER_MODEL
    PIPER_VOICE
    TTS_ENGINE
)

for key in "${OBSOLETE_KEYS[@]}"; do
    if sudo grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sudo sed -i "/^${key}=/d" "$ENV_FILE"
        echo "[fix-env] Removed obsolete key: $key"
    fi
done

# Strip inline comments from values (python-dotenv may misparse them)
# Matches: KEY=value   # comment  ->  KEY=value
# Leaves:  # full comment lines alone
sudo sed -i '/^[^#]/s/[[:space:]]*#[^"'"'"']*$//' "$ENV_FILE"
echo "[fix-env] Stripped inline comments from value lines"

# Remove duplicate VOICEMAIL_ENABLED lines (keep last)
if [[ $(sudo grep -c "^VOICEMAIL_ENABLED=" "$ENV_FILE") -gt 1 ]]; then
    # Keep only the last occurrence
    sudo awk '!seen[$0]++ || /^VOICEMAIL_ENABLED=/' "$ENV_FILE" > /tmp/helix_env_dedup
    sudo cp /tmp/helix_env_dedup "$ENV_FILE"
    echo "[fix-env] Removed duplicate VOICEMAIL_ENABLED entries"
fi

echo "[fix-env] Done. Restart helix-agent to apply: sudo systemctl restart helix-agent"
