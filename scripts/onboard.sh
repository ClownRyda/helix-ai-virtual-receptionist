#!/usr/bin/env bash
# =============================================================================
# Helix AI Virtual Receptionist — Interactive Onboarding Script
#
# Usage:
#   chmod +x scripts/onboard.sh
#   ./scripts/onboard.sh
#
# What this does:
#   - Prompts for all required configuration values
#   - Writes agent/.env, asterisk/etc/asterisk/ari.conf, pjsip.conf
#   - Optionally installs Piper TTS + voice models
#   - Optionally pulls the Ollama LLM model
#   - Installs Python dependencies
#   - Guides Google Calendar OAuth setup
#   - Validates Asterisk, Ollama, and agent are reachable
#   - Prints a final summary
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$REPO_ROOT/agent/.env"
ENV_EXAMPLE="$REPO_ROOT/agent/.env.example"
ARI_CONF="$REPO_ROOT/asterisk/etc/asterisk/ari.conf"
PJSIP_CONF="$REPO_ROOT/asterisk/etc/asterisk/pjsip.conf"
PIPER_MODEL_DIR="/opt/piper/models"
PIPER_VERSION="2023.11.14-2"
HF_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

log()     { echo -e "${GREEN}[✓]${NC} $*"; }
info()    { echo -e "${CYAN}[→]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
err()     { echo -e "${RED}[✗]${NC} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════════${NC}"; echo -e "${BOLD}${CYAN}  $*${NC}"; echo -e "${BOLD}${CYAN}══════════════════════════════════════════════${NC}\n"; }
section() { echo -e "\n${BOLD}▸ $*${NC}"; }

# ── Helper: prompt with default ───────────────────────────────────────────────
prompt() {
    local var_name="$1"
    local prompt_text="$2"
    local default_val="${3:-}"
    local secret="${4:-no}"

    if [[ -n "$default_val" ]]; then
        echo -en "  ${prompt_text} ${CYAN}[${default_val}]${NC}: "
    else
        echo -en "  ${prompt_text}: "
    fi

    local value
    if [[ "$secret" == "yes" ]]; then
        read -rs value
        echo ""
    else
        read -r value
    fi

    if [[ -z "$value" && -n "$default_val" ]]; then
        value="$default_val"
    fi

    # Re-prompt if empty and no default
    while [[ -z "$value" ]]; do
        warn "This value is required."
        if [[ "$secret" == "yes" ]]; then
            echo -en "  ${prompt_text}: "
            read -rs value
            echo ""
        else
            echo -en "  ${prompt_text}: "
            read -r value
        fi
    done

    printf -v "$var_name" '%s' "$value"
}

# ── Helper: yes/no prompt ─────────────────────────────────────────────────────
prompt_yn() {
    local var_name="$1"
    local prompt_text="$2"
    local default_val="${3:-y}"
    local answer

    while true; do
        echo -en "  ${prompt_text} ${CYAN}[y/n, default: ${default_val}]${NC}: "
        read -r answer
        answer="${answer:-$default_val}"
        case "$answer" in
            [Yy]|yes|YES) printf -v "$var_name" 'true'; return ;;
            [Nn]|no|NO)   printf -v "$var_name" 'false'; return ;;
            *) warn "Please enter y or n." ;;
        esac
    done
}

# ── Helper: sed-based in-place replacement (cross-platform) ──────────────────
replace_in_file() {
    local file="$1"
    local search="$2"
    local replace="$3"
    # Escape forward slashes in the replacement string
    local escaped_replace="${replace//\//\\/}"
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s/${search}/${escaped_replace}/g" "$file"
    else
        sed -i "s/${search}/${escaped_replace}/g" "$file"
    fi
}

# ── Helper: set a value in the .env file ─────────────────────────────────────
set_env() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        else
            sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        fi
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

# ── Welcome banner ─────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${BOLD}${CYAN}"
cat << 'EOF'
  ██╗  ██╗███████╗██╗     ██╗██╗  ██╗     █████╗ ██╗
  ██║  ██║██╔════╝██║     ██║╚██╗██╔╝    ██╔══██╗██║
  ███████║█████╗  ██║     ██║ ╚███╔╝     ███████║██║
  ██╔══██║██╔══╝  ██║     ██║ ██╔██╗     ██╔══██║██║
  ██║  ██║███████╗███████╗██║██╔╝ ██╗    ██║  ██║██║
  ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝
EOF
echo -e "${NC}"
echo -e "${BOLD}  Virtual Receptionist — First-Time Setup${NC}"
echo -e "  v1.3 Onboarding Script"
echo ""
echo -e "  This wizard will configure your Helix AI system."
echo -e "  All values can be changed later by editing ${CYAN}agent/.env${NC}."
echo ""
echo -e "  Press ${BOLD}Enter${NC} to accept a default shown in ${CYAN}[brackets]${NC}."
echo ""
echo -e "${YELLOW}  Note: No secrets or IP addresses are ever sent off-device.${NC}"
echo ""

# ── Step 0: Detect deployment mode ───────────────────────────────────────────
header "Step 1 of 9 — Deployment Mode"

echo "  How are you running Helix AI?"
echo ""
echo "  1) Docker (recommended — all services containerized)"
echo "  2) Native Linux (Asterisk installed directly on this machine)"
echo ""
echo -en "  Choose [1/2, default: 1]: "
read -r DEPLOY_MODE_CHOICE
DEPLOY_MODE_CHOICE="${DEPLOY_MODE_CHOICE:-1}"

case "$DEPLOY_MODE_CHOICE" in
    2) DEPLOY_MODE="native" ;;
    *) DEPLOY_MODE="docker" ;;
esac

log "Deployment mode: $DEPLOY_MODE"

# ── Step 1: Business identity ─────────────────────────────────────────────────
header "Step 2 of 9 — Business Identity"

info "These values are spoken in every greeting by the AI receptionist."
echo ""

prompt BUSINESS_NAME   "Business name (spoken aloud)"   "My Business"
prompt AGENT_NAME      "Receptionist name"               "Alex"

echo ""
info "Timezone must be a valid tz database string."
info "Examples: America/Chicago, America/New_York, America/Los_Angeles, America/Denver"
echo ""
prompt BUSINESS_TIMEZONE "Timezone" "America/Chicago"

section "Business Hours"
info "Use 24-hour integers (9 = 9 AM, 17 = 5 PM)."
echo ""
prompt HOURS_START "Business hours start (0-23)" "9"
prompt HOURS_END   "Business hours end   (0-23)" "17"

# Validate numeric
while ! [[ "$HOURS_START" =~ ^[0-9]+$ ]] || (( HOURS_START > 23 )); do
    warn "Hours start must be 0–23."
    prompt HOURS_START "Business hours start (0-23)" "9"
done
while ! [[ "$HOURS_END" =~ ^[0-9]+$ ]] || (( HOURS_END > 23 )); do
    warn "Hours end must be 0–23."
    prompt HOURS_END "Business hours end (0-23)" "17"
done

# ── Step 2: Security passwords ────────────────────────────────────────────────
header "Step 3 of 9 — Passwords & Security"

section "ARI Password"
info "This password secures the Asterisk REST Interface."
info "It must match between agent/.env and asterisk/etc/asterisk/ari.conf."
echo ""
prompt ARI_PASSWORD    "ARI password (min 8 chars)" "" "yes"

while (( ${#ARI_PASSWORD} < 8 )); do
    warn "Password must be at least 8 characters."
    prompt ARI_PASSWORD "ARI password (min 8 chars)" "" "yes"
done

section "SIP Extension Passwords"
info "These are the passwords your softphones use to register."
info "Each extension (1001, 1002, 1003) needs its own password."
echo ""
prompt EXT1001_PASS "Extension 1001 password (Operator)" "" "yes"
prompt EXT1002_PASS "Extension 1002 password (Sales)"    "" "yes"
prompt EXT1003_PASS "Extension 1003 password (Support)"  "" "yes"

# ── Step 3: Network configuration ─────────────────────────────────────────────
header "Step 4 of 9 — Network Configuration"

info "These values configure Asterisk PJSIP so softphones can find it."
echo ""

prompt SERVER_IP    "Server LAN IP address (e.g. 192.168.1.100)"   ""
prompt LAN_SUBNET   "LAN subnet CIDR       (e.g. 192.168.1.0/24)"  ""

# Validate IP format (basic)
while ! echo "$SERVER_IP" | grep -qE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'; do
    warn "Please enter a valid IP address (e.g. 192.168.1.100)."
    prompt SERVER_IP "Server LAN IP address" ""
done

# Validate CIDR format (basic)
while ! echo "$LAN_SUBNET" | grep -qE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$'; do
    warn "Please enter a valid CIDR (e.g. 192.168.1.0/24)."
    prompt LAN_SUBNET "LAN subnet CIDR" ""
done

# ── Step 4: Extensions & Routing ─────────────────────────────────────────────
header "Step 5 of 9 — Extensions & Routing"

info "These are the extensions the AI will transfer callers to."
echo ""
prompt OPERATOR_EXTENSION   "Operator / main desk extension"    "1001"
prompt EMERGENCY_EXTENSION  "Emergency after-hours extension"   "1001"

# ── Step 5: After-Hours Behavior ──────────────────────────────────────────────
header "Step 6 of 9 — After-Hours Behavior"

info "What should happen when a caller reaches Helix outside business hours?"
echo ""
echo "  1) callback   — Tell the caller to call back during business hours"
echo "  2) voicemail  — Record a voicemail message"
echo "  3) schedule   — Let the caller book a callback appointment (AI continues)"
echo "  4) emergency  — Immediately transfer to your emergency extension"
echo ""
echo -en "  Choose after-hours mode [1-4, default: 1]: "
read -r AH_CHOICE
AH_CHOICE="${AH_CHOICE:-1}"

case "$AH_CHOICE" in
    2) AFTER_HOURS_MODE="voicemail"  ;;
    3) AFTER_HOURS_MODE="schedule"   ;;
    4) AFTER_HOURS_MODE="emergency"  ;;
    *) AFTER_HOURS_MODE="callback"   ;;
esac
log "After-hours mode: $AFTER_HOURS_MODE"

# ── Step 6: Hardware / GPU ────────────────────────────────────────────────────
header "Step 7 of 9 — Hardware (GPU / CPU)"

info "Helix AI uses Whisper for speech recognition."
echo ""
echo "  1) CUDA GPU (NVIDIA — faster, recommended for production)"
echo "  2) CPU only (slower but works everywhere)"
echo ""
echo -en "  Choose [1/2, default: 1]: "
read -r GPU_CHOICE
GPU_CHOICE="${GPU_CHOICE:-1}"

case "$GPU_CHOICE" in
    2)
        WHISPER_DEVICE="cpu"
        WHISPER_COMPUTE_TYPE="int8"
        ;;
    *)
        WHISPER_DEVICE="cuda"
        WHISPER_COMPUTE_TYPE="float16"
        ;;
esac
log "Whisper will use: $WHISPER_DEVICE ($WHISPER_COMPUTE_TYPE)"

# ── Step 7: Optional Features ─────────────────────────────────────────────────
header "Step 8 of 9 — Optional Features"

echo ""
prompt_yn VOICEMAIL_ENABLED   "Enable voicemail recording?"            "y"
prompt_yn CALL_SUMMARY_ENABLED "Enable AI-generated post-call summaries?" "n"
prompt_yn FAQ_ENABLED          "Enable FAQ / knowledge-base lookup?"       "n"

if [[ "$FAQ_ENABLED" == "true" ]]; then
    prompt FAQ_FILE "Path to FAQ file" "faq.txt"
else
    FAQ_FILE="faq.txt"
fi

section "DTMF Keypress Fallback"
info "Adds a keypress menu as a backup to the spoken AI interface."
prompt_yn DTMF_ENABLED "Enable DTMF keypress menu?" "n"

if [[ "$DTMF_ENABLED" == "true" ]]; then
    info "Default DTMF map: 1→Sales(1002), 2→Support(1003), 0→Operator(1001)"
    echo -en "  Custom DTMF JSON map (press Enter to use default): "
    read -r DTMF_MAP_INPUT
    DTMF_MAP="${DTMF_MAP_INPUT:-{\"1\":\"1002\",\"2\":\"1003\",\"0\":\"1001\"}}"
else
    DTMF_MAP='{"1":"1002","2":"1003","0":"1001"}'
fi

section "VIP Callers (optional)"
info "Phone numbers that skip the AI and go straight to your operator."
info "Comma-separated, e.g.: +12125550100,+13125550199"
echo -en "  VIP caller numbers (press Enter to skip): "
read -r VIP_CALLERS

# ── Step 8: Write configuration files ─────────────────────────────────────────
header "Step 9 of 9 — Writing Configuration"

# ── 8a: Write .env ────────────────────────────────────────────────────────────
section "Writing agent/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    log "Created agent/.env from template"
fi

set_env "BUSINESS_NAME"           "$BUSINESS_NAME"
set_env "AGENT_NAME"              "$AGENT_NAME"
set_env "BUSINESS_TIMEZONE"       "$BUSINESS_TIMEZONE"
set_env "BUSINESS_HOURS_START"    "$HOURS_START"
set_env "BUSINESS_HOURS_END"      "$HOURS_END"
set_env "ASTERISK_ARI_PASSWORD"   "$ARI_PASSWORD"
set_env "AFTER_HOURS_MODE"        "$AFTER_HOURS_MODE"
set_env "OPERATOR_EXTENSION"      "$OPERATOR_EXTENSION"
set_env "EMERGENCY_EXTENSION"     "$EMERGENCY_EXTENSION"
set_env "WHISPER_DEVICE"          "$WHISPER_DEVICE"
set_env "WHISPER_COMPUTE_TYPE"    "$WHISPER_COMPUTE_TYPE"
set_env "VOICEMAIL_ENABLED"       "$VOICEMAIL_ENABLED"
set_env "CALL_SUMMARY_ENABLED"    "$CALL_SUMMARY_ENABLED"
set_env "FAQ_ENABLED"             "$FAQ_ENABLED"
set_env "FAQ_FILE"                "$FAQ_FILE"
set_env "DTMF_ENABLED"            "$DTMF_ENABLED"
set_env "DTMF_MAP"                "$DTMF_MAP"
set_env "VIP_CALLERS"             "$VIP_CALLERS"

log "agent/.env written"

# ── 8b: Write ari.conf ────────────────────────────────────────────────────────
section "Writing asterisk/etc/asterisk/ari.conf"

if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "s|password=CHANGE_ME_ARI_PASSWORD|password=${ARI_PASSWORD}|g" "$ARI_CONF"
else
    sed -i "s|password=CHANGE_ME_ARI_PASSWORD|password=${ARI_PASSWORD}|g" "$ARI_CONF"
fi

# Handle already-changed (re-run case) — replace any current password line
if ! grep -q "password=${ARI_PASSWORD}" "$ARI_CONF"; then
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s|^password=.*|password=${ARI_PASSWORD}|" "$ARI_CONF"
    else
        sed -i "s|^password=.*|password=${ARI_PASSWORD}|" "$ARI_CONF"
    fi
fi

log "ari.conf password updated"

# ── 8c: Write pjsip.conf ─────────────────────────────────────────────────────
section "Writing asterisk/etc/asterisk/pjsip.conf"

# Replace placeholder server IP
if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "s|external_media_address=YOUR_SERVER_IP|external_media_address=${SERVER_IP}|g" "$PJSIP_CONF"
    sed -i '' "s|external_signaling_address=YOUR_SERVER_IP|external_signaling_address=${SERVER_IP}|g" "$PJSIP_CONF"
    # Replace the first local_net (the placeholder CHANGE_ME line)
    sed -i '' "s|local_net=192.168.0.0/16.*|local_net=${LAN_SUBNET}|" "$PJSIP_CONF"
    # Extension passwords
    sed -i '' "s|password=CHANGE_ME_EXT_1001_PASSWORD|password=${EXT1001_PASS}|g" "$PJSIP_CONF"
    sed -i '' "s|password=CHANGE_ME_EXT_1002_PASSWORD|password=${EXT1002_PASS}|g" "$PJSIP_CONF"
    sed -i '' "s|password=CHANGE_ME_EXT_1003_PASSWORD|password=${EXT1003_PASS}|g" "$PJSIP_CONF"
else
    sed -i "s|external_media_address=YOUR_SERVER_IP|external_media_address=${SERVER_IP}|g" "$PJSIP_CONF"
    sed -i "s|external_signaling_address=YOUR_SERVER_IP|external_signaling_address=${SERVER_IP}|g" "$PJSIP_CONF"
    sed -i "s|local_net=192.168.0.0/16.*|local_net=${LAN_SUBNET}|" "$PJSIP_CONF"
    sed -i "s|password=CHANGE_ME_EXT_1001_PASSWORD|password=${EXT1001_PASS}|g" "$PJSIP_CONF"
    sed -i "s|password=CHANGE_ME_EXT_1002_PASSWORD|password=${EXT1002_PASS}|g" "$PJSIP_CONF"
    sed -i "s|password=CHANGE_ME_EXT_1003_PASSWORD|password=${EXT1003_PASS}|g" "$PJSIP_CONF"
fi

log "pjsip.conf updated"

# ── Docker mode: also write pjsip.windows.conf if present ────────────────────
PJSIP_WIN_CONF="$REPO_ROOT/asterisk/etc/asterisk/pjsip.windows.conf"
if [[ -f "$PJSIP_WIN_CONF" ]]; then
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s|external_media_address=YOUR_SERVER_IP|external_media_address=${SERVER_IP}|g" "$PJSIP_WIN_CONF"
        sed -i '' "s|external_signaling_address=YOUR_SERVER_IP|external_signaling_address=${SERVER_IP}|g" "$PJSIP_WIN_CONF"
        sed -i '' "s|local_net=192.168.0.0/16.*|local_net=${LAN_SUBNET}|" "$PJSIP_WIN_CONF"
        sed -i '' "s|password=CHANGE_ME_EXT_1001_PASSWORD|password=${EXT1001_PASS}|g" "$PJSIP_WIN_CONF"
        sed -i '' "s|password=CHANGE_ME_EXT_1002_PASSWORD|password=${EXT1002_PASS}|g" "$PJSIP_WIN_CONF"
        sed -i '' "s|password=CHANGE_ME_EXT_1003_PASSWORD|password=${EXT1003_PASS}|g" "$PJSIP_WIN_CONF"
    else
        sed -i "s|external_media_address=YOUR_SERVER_IP|external_media_address=${SERVER_IP}|g" "$PJSIP_WIN_CONF"
        sed -i "s|external_signaling_address=YOUR_SERVER_IP|external_signaling_address=${SERVER_IP}|g" "$PJSIP_WIN_CONF"
        sed -i "s|local_net=192.168.0.0/16.*|local_net=${LAN_SUBNET}|" "$PJSIP_WIN_CONF"
        sed -i "s|password=CHANGE_ME_EXT_1001_PASSWORD|password=${EXT1001_PASS}|g" "$PJSIP_WIN_CONF"
        sed -i "s|password=CHANGE_ME_EXT_1002_PASSWORD|password=${EXT1002_PASS}|g" "$PJSIP_WIN_CONF"
        sed -i "s|password=CHANGE_ME_EXT_1003_PASSWORD|password=${EXT1003_PASS}|g" "$PJSIP_WIN_CONF"
    fi
    log "pjsip.windows.conf updated"
fi

# ── Step 9: Install dependencies ──────────────────────────────────────────────
header "Dependencies"

if [[ "$DEPLOY_MODE" == "native" ]]; then

    section "Installing Piper TTS"
    if command -v piper &>/dev/null; then
        log "Piper already installed"
    else
        info "Downloading Piper TTS v${PIPER_VERSION}..."
        wget -q "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
            -O /tmp/piper.tar.gz
        sudo tar -xzf /tmp/piper.tar.gz -C /usr/local/bin/
        rm /tmp/piper.tar.gz
        log "Piper installed"
    fi

    section "Downloading Piper voice models"
    sudo mkdir -p "$PIPER_MODEL_DIR"

    if [[ ! -f "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx" ]]; then
        info "Downloading English voice model..."
        sudo wget -q "${HF_BASE}/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
            -O "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx"
        sudo wget -q "${HF_BASE}/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
            -O "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx.json"
        log "English voice model downloaded"
    else
        log "English voice model already present"
    fi

    if [[ ! -f "$PIPER_MODEL_DIR/es_MX-claude-high.onnx" ]]; then
        info "Downloading Spanish (Mexico) voice model..."
        sudo wget -q "${HF_BASE}/es/es_MX/claude/high/es_MX-claude-high.onnx" \
            -O "$PIPER_MODEL_DIR/es_MX-claude-high.onnx"
        sudo wget -q "${HF_BASE}/es/es_MX/claude/high/es_MX-claude-high.onnx.json" \
            -O "$PIPER_MODEL_DIR/es_MX-claude-high.onnx.json"
        log "Spanish voice model downloaded"
    else
        log "Spanish voice model already present"
    fi

    section "Installing Python dependencies"
    cd "$REPO_ROOT/agent"
    pip install -r requirements.txt
    cd "$REPO_ROOT"
    log "Python deps installed"

    section "Pulling Ollama model"
    if command -v ollama &>/dev/null; then
        info "Pulling llama3.1:8b (this may take several minutes on first run)..."
        ollama pull llama3.1:8b
        log "Ollama model ready"
    else
        warn "Ollama not found. Install from https://ollama.com and run:"
        warn "  ollama pull llama3.1:8b"
    fi

else
    # Docker mode — models are pulled inside containers at startup via deploy.sh
    info "Docker mode: dependencies are managed by containers."
    info "Run ./deploy.sh --pull to pull the Ollama model into the container."
fi

# ── Step 10: Google Calendar ──────────────────────────────────────────────────
header "Google Calendar Setup"

CREDS_FILE="$REPO_ROOT/agent/credentials.json"

if [[ -f "$CREDS_FILE" ]]; then
    log "credentials.json found"
    info "To authorize Helix AI to access your calendar, run:"
    echo ""
    echo "    cd agent && python -c \"from calendar.gcal import _get_service; _get_service()\""
    echo ""
    info "A browser window will open. Log in and allow access."
    echo ""
    prompt_yn RUN_GCAL_AUTH "Run Google Calendar authorization now?" "y"
    if [[ "$RUN_GCAL_AUTH" == "true" ]]; then
        cd "$REPO_ROOT/agent"
        python -c "from calendar.gcal import _get_service; _get_service()" || \
            warn "Auth failed or cancelled. Re-run the command above manually."
        cd "$REPO_ROOT"
    fi
else
    warn "No credentials.json found in agent/."
    echo ""
    echo "  To enable Google Calendar scheduling:"
    echo "  1. Go to: https://console.cloud.google.com"
    echo "  2. Create a project, enable the Google Calendar API"
    echo "  3. Create OAuth 2.0 Desktop credentials"
    echo "  4. Download as credentials.json → place it in agent/"
    echo "  5. Re-run this script or run:"
    echo "     cd agent && python -c \"from calendar.gcal import _get_service; _get_service()\""
    echo ""
    warn "Calendar scheduling will be disabled until credentials.json is added."
fi

# ── Step 11: Validation ───────────────────────────────────────────────────────
header "Validating Services"

VALIDATION_PASSED=true

if [[ "$DEPLOY_MODE" == "docker" ]]; then
    info "Checking Docker services (if already running)..."

    # Asterisk
    echo -n "  Asterisk (docker): "
    if docker exec pbx-asterisk asterisk -rx "core show version" &>/dev/null 2>&1; then
        echo -e "${GREEN}reachable${NC}"
    else
        echo -e "${YELLOW}not running (start with ./deploy.sh)${NC}"
    fi

    # Ollama
    echo -n "  Ollama:            "
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo -e "${GREEN}reachable${NC}"
    else
        echo -e "${YELLOW}not running (start with ./deploy.sh)${NC}"
    fi

    # Agent API
    echo -n "  Agent API:         "
    if curl -sf http://localhost:8000/api/health &>/dev/null 2>&1; then
        echo -e "${GREEN}reachable${NC}"
    else
        echo -e "${YELLOW}not running (start with ./deploy.sh)${NC}"
    fi

else
    # Native mode checks
    echo -n "  Asterisk ARI:  "
    if curl -sf -u "pbx-agent:${ARI_PASSWORD}" "http://localhost:8088/ari/asterisk/info" &>/dev/null 2>&1; then
        echo -e "${GREEN}reachable${NC}"
    else
        echo -e "${YELLOW}not running or not configured yet${NC}"
        VALIDATION_PASSED=false
    fi

    echo -n "  Ollama:        "
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo -e "${GREEN}reachable${NC}"
    else
        echo -e "${YELLOW}not running — start with: ollama serve${NC}"
        VALIDATION_PASSED=false
    fi

    echo -n "  Agent API:     "
    if curl -sf http://localhost:8000/api/health &>/dev/null 2>&1; then
        echo -e "${GREEN}reachable${NC}"
    else
        echo -e "${YELLOW}not running (start after Asterisk + Ollama are up)${NC}"
    fi
fi

# ── Final Summary ─────────────────────────────────────────────────────────────
header "Setup Complete"

echo -e "${BOLD}  Configuration Summary${NC}"
echo "  ─────────────────────────────────────────"
echo -e "  Business name:      ${CYAN}${BUSINESS_NAME}${NC}"
echo -e "  Receptionist name:  ${CYAN}${AGENT_NAME}${NC}"
echo -e "  Timezone:           ${CYAN}${BUSINESS_TIMEZONE}${NC}"
echo -e "  Business hours:     ${CYAN}${HOURS_START}:00 – ${HOURS_END}:00${NC}"
echo -e "  After-hours mode:   ${CYAN}${AFTER_HOURS_MODE}${NC}"
echo -e "  Operator ext:       ${CYAN}${OPERATOR_EXTENSION}${NC}"
echo -e "  Emergency ext:      ${CYAN}${EMERGENCY_EXTENSION}${NC}"
echo -e "  Server IP:          ${CYAN}${SERVER_IP}${NC}"
echo -e "  LAN subnet:         ${CYAN}${LAN_SUBNET}${NC}"
echo -e "  Whisper device:     ${CYAN}${WHISPER_DEVICE} (${WHISPER_COMPUTE_TYPE})${NC}"
echo -e "  Voicemail:          ${CYAN}${VOICEMAIL_ENABLED}${NC}"
echo -e "  Call summaries:     ${CYAN}${CALL_SUMMARY_ENABLED}${NC}"
echo -e "  FAQ enabled:        ${CYAN}${FAQ_ENABLED}${NC}"
echo -e "  DTMF fallback:      ${CYAN}${DTMF_ENABLED}${NC}"
echo ""
echo -e "  ${BOLD}Files written:${NC}"
echo -e "    ${GREEN}✓${NC} agent/.env"
echo -e "    ${GREEN}✓${NC} asterisk/etc/asterisk/ari.conf"
echo -e "    ${GREEN}✓${NC} asterisk/etc/asterisk/pjsip.conf"
[[ -f "$PJSIP_WIN_CONF" ]] && echo -e "    ${GREEN}✓${NC} asterisk/etc/asterisk/pjsip.windows.conf"
echo ""

if [[ "$DEPLOY_MODE" == "docker" ]]; then
    echo -e "${BOLD}  Next steps:${NC}"
    echo "  1. Run: ./deploy.sh --pull"
    echo "         (builds containers, pulls LLM model, starts everything)"
    echo "  2. Register a SIP softphone (Zoiper):"
    echo "     • Server: ${SERVER_IP}:5060"
    echo "     • Extension 1001, password: [what you entered]"
    echo "  3. Dial 9999 to speak with your AI receptionist"
    echo "  4. Dashboard: http://${SERVER_IP}:3000"
    echo "  5. Agent API: http://${SERVER_IP}:8000"
else
    echo -e "${BOLD}  Next steps:${NC}"
    echo "  1. Start Asterisk:  sudo systemctl start asterisk"
    echo "  2. Start Ollama:    ollama serve"
    echo "  3. Start agent:     cd agent && python main.py"
    echo "  4. Register Zoiper: ${SERVER_IP}:5060  ext 1001"
    echo "  5. Dial 9999"
fi

echo ""
echo -e "  See ${CYAN}README.md${NC} for full documentation."
echo -e "  Need help? Open an issue at:"
echo -e "  ${CYAN}https://github.com/ClownRyda/helix-ai-virtual-receptionist/issues${NC}"
echo ""
echo -e "${GREEN}${BOLD}  Helix AI is configured and ready to go.${NC}"
echo ""
