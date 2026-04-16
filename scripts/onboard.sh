#!/usr/bin/env bash
# =============================================================================
# Helix AI Virtual Receptionist — Full Installer + Onboarding Script
#
# Usage:
#   chmod +x scripts/onboard.sh
#   ./scripts/onboard.sh
#
# What this does:
#   1. Prompts for Docker or native Linux install mode
#   2. Installs ALL system dependencies for the chosen mode
#   3. Detects existing Ollama (local or remote); installs if not found
#   4. Installs Kokoro TTS via pip (auto-downloads model weights on first run)
#   5. Writes agent/.env, asterisk/etc/asterisk/ari.conf, pjsip.conf
#   6. Guides Google Calendar OAuth setup
#   7. Validates all services are reachable
#   8. (Native) Creates helix system user, installs systemd units + nginx
#   9. Locks down .env (chmod 600, helix:helix)
#  10. Binds Ollama to 127.0.0.1:11434 via systemd override
#  11. Prints a final summary with next steps
#
# Supported platforms: Ubuntu 20.04+, Debian 11+, macOS 13+ (native only)
# Docker mode also supported on any platform with Docker Engine installed.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_FILE="$REPO_ROOT/agent/.env"
ENV_EXAMPLE="$REPO_ROOT/agent/.env.example"
ARI_CONF="$REPO_ROOT/asterisk/etc/asterisk/ari.conf"
PJSIP_CONF="$REPO_ROOT/asterisk/etc/asterisk/pjsip.conf"
AGENT_VENV="$REPO_ROOT/agent/.venv"

HELIX_VERSION="v1.6.7"

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
step()    { echo -e "\n${BOLD}${CYAN}[ Step $1 of ${TOTAL_STEPS} ]${NC} ${BOLD}$2${NC}"; }

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
        read -rs value; echo ""
    else
        read -r value
    fi

    [[ -z "$value" && -n "$default_val" ]] && value="$default_val"

    while [[ -z "$value" ]]; do
        warn "This value is required."
        if [[ "$secret" == "yes" ]]; then
            echo -en "  ${prompt_text}: "; read -rs value; echo ""
        else
            echo -en "  ${prompt_text}: "; read -r value
        fi
    done

    printf -v "$var_name" '%s' "$value"
}

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
            [Yy]|yes|YES) printf -v "$var_name" 'true';  return ;;
            [Nn]|no|NO)   printf -v "$var_name" 'false'; return ;;
            *) warn "Please enter y or n." ;;
        esac
    done
}

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

replace_in_conf() {
    local file="$1"; local search="$2"; local replace="$3"
    local escaped_replace="${replace//\//\\/}"
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s/${search}/${escaped_replace}/g" "$file"
    else
        sed -i "s/${search}/${escaped_replace}/g" "$file"
    fi
}

command_exists() { command -v "$1" &>/dev/null; }

# ── Welcome banner ─────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${BOLD}${CYAN}"
cat << 'BANNER'
  ██╗  ██╗███████╗██╗     ██╗██╗  ██╗     █████╗ ██╗
  ██║  ██║██╔════╝██║     ██║╚██╗██╔╝    ██╔══██╗██║
  ███████║█████╗  ██║     ██║ ╚███╔╝     ███████║██║
  ██╔══██║██╔══╝  ██║     ██║ ██╔██╗     ██╔══██║██║
  ██║  ██║███████╗███████╗██║██╔╝ ██╗    ██║  ██║██║
  ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝
BANNER
echo -e "${NC}"
echo -e "${BOLD}  Virtual Receptionist — Full Installer + Setup  ${HELIX_VERSION}${NC}"
echo ""
echo -e "  This script will install all dependencies, configure your system,"
echo -e "  and get Helix AI ready to take calls."
echo ""
echo -e "  Press ${BOLD}Enter${NC} to accept defaults shown in ${CYAN}[brackets]${NC}."
echo -e "  All settings can be changed later by editing ${CYAN}agent/.env${NC}."
echo ""
echo -e "  ${YELLOW}No secrets or IP addresses are ever sent off-device.${NC}"
echo ""

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS="$(uname -s)"
ARCH="$(uname -m)"
IS_LINUX=false; IS_MAC=false
[[ "$OS" == "Linux" ]]  && IS_LINUX=true
[[ "$OS" == "Darwin" ]] && IS_MAC=true

if $IS_LINUX; then
    DISTRO_ID="$(. /etc/os-release && echo "${ID:-unknown}")"
    DISTRO_LIKE="$(. /etc/os-release && echo "${ID_LIKE:-}")"
else
    DISTRO_ID="macos"
fi

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1 — Install Mode
# ═════════════════════════════════════════════════════════════════════════════
TOTAL_STEPS=11
step "1" "Install Mode"

echo ""
echo "  How do you want to run Helix AI?"
echo ""
echo "  1) Docker (recommended)"
echo "     All services run in containers. Easiest to manage."
echo "     Requires: Docker Engine + Docker Compose"
echo ""
echo "  2) Native Linux (direct install)"
echo "     Asterisk, Python, Ollama installed directly on this machine."
echo "     More control; more manual steps."
echo ""
echo -en "  Choose [1/2, default: 1]: "
read -r DEPLOY_MODE_CHOICE
DEPLOY_MODE_CHOICE="${DEPLOY_MODE_CHOICE:-1}"
case "$DEPLOY_MODE_CHOICE" in
    2) DEPLOY_MODE="native" ;;
    *) DEPLOY_MODE="docker" ;;
esac
log "Install mode: $DEPLOY_MODE"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2 — System Dependencies
# ═════════════════════════════════════════════════════════════════════════════
step "2" "Installing System Dependencies"
echo ""

install_apt_packages() {
    local packages=("$@")
    info "Updating package lists..."
    sudo apt-get update -qq
    info "Installing: ${packages[*]}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${packages[@]}"
}

if [[ "$DEPLOY_MODE" == "docker" ]]; then
    section "Docker Engine"
    if command_exists docker; then
        DOCKER_VER="$(docker --version | awk '{print $3}' | tr -d ',')"
        log "Docker already installed: $DOCKER_VER"
    else
        info "Docker not found — installing Docker Engine..."
        if $IS_LINUX; then
            curl -fsSL https://get.docker.com | sudo sh
            sudo usermod -aG docker "$USER"
            log "Docker Engine installed."
            warn "You have been added to the 'docker' group."
            warn "Log out and back in (or run: newgrp docker) to use Docker without sudo."
        elif $IS_MAC; then
            err "Automatic Docker install not supported on macOS."
            echo "  Please install Docker Desktop from https://www.docker.com/products/docker-desktop/"
            echo "  Then re-run this script."
            exit 1
        fi
    fi

    section "Docker Compose"
    if docker compose version &>/dev/null 2>&1; then
        log "Docker Compose (plugin) available."
    elif command_exists docker-compose; then
        log "docker-compose (standalone) available."
    else
        info "Installing Docker Compose plugin..."
        if $IS_LINUX; then
            sudo apt-get install -y docker-compose-plugin 2>/dev/null || \
            sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
                -o /usr/local/bin/docker-compose && sudo chmod +x /usr/local/bin/docker-compose
            log "Docker Compose installed."
        fi
    fi

    section "Python 3.11+ (for onboarding helper scripts)"
    if $IS_LINUX; then
        if ! command_exists python3 || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" 2>/dev/null; then
            install_apt_packages software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            install_apt_packages python3.11 python3.11-venv python3-pip
            sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 || true
        fi
        log "Python $(python3 --version 2>&1 | awk '{print $2}') ready."
    fi

else
    # ── Native install ────────────────────────────────────────────────────────
    section "Core system packages"
    if $IS_LINUX; then
        PACKAGES=(
            asterisk
            python3.11
            python3.11-venv
            python3.11-dev
            python3-pip
            ffmpeg
            wget
            curl
            git
            libsndfile1
            espeak-ng
            libespeak-ng-dev
            build-essential
        )
        # Add deadsnakes PPA for python3.11 if not available
        if ! dpkg -l python3.11 &>/dev/null 2>&1; then
            install_apt_packages software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa
        fi
        install_apt_packages "${PACKAGES[@]}"
        log "System packages installed."

        # Set python3.11 as python3 if needed
        if ! python3 --version 2>&1 | grep -q "3\.1[1-9]"; then
            sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 10 || true
        fi
        log "Python $(python3 --version 2>&1 | awk '{print $2}') set as default."

    elif $IS_MAC; then
        if ! command_exists brew; then
            err "Homebrew not found. Install from https://brew.sh then re-run."
            exit 1
        fi
        info "Installing macOS dependencies via Homebrew..."
        brew install asterisk python@3.11 ffmpeg espeak-ng portaudio 2>/dev/null || true
        log "macOS dependencies installed."
    fi

    section "Python virtualenv for agent"
    if [[ ! -d "$AGENT_VENV" ]]; then
        info "Creating virtualenv at agent/.venv ..."
        python3.11 -m venv "$AGENT_VENV" 2>/dev/null || python3 -m venv "$AGENT_VENV"
        log "Virtualenv created."
    else
        log "Virtualenv already exists."
    fi

    VENV_PIP="$AGENT_VENV/bin/pip"
    VENV_PYTHON="$AGENT_VENV/bin/python"

    section "Python dependencies (agent)"
    info "Installing from agent/requirements.txt ..."
    "$VENV_PIP" install --upgrade pip -q
    "$VENV_PIP" install -r "$REPO_ROOT/agent/requirements.txt" -q
    log "Python dependencies installed."

    section "Kokoro TTS — first-run model pre-download"
    info "Pre-downloading Kokoro model weights (saves time on first call)..."
    "$VENV_PYTHON" -c "
from kokoro import KPipeline
for lc in ['a', 'e', 'f', 'i']:
    print(f'  Loading Kokoro pipeline: lang_code={lc}')
    KPipeline(lang_code=lc)
print('Kokoro models cached.')
" && log "Kokoro model weights cached." || warn "Kokoro pre-download failed — models will download on first call."

    section "Asterisk configuration"
    if [[ -d /etc/asterisk ]]; then
        info "Copying Helix Asterisk config files..."
        sudo cp -r "$REPO_ROOT/asterisk/etc/asterisk/"* /etc/asterisk/
        sudo asterisk -rx "core reload" 2>/dev/null && log "Asterisk config reloaded." || \
            warn "Could not reload Asterisk live — restart manually: sudo systemctl restart asterisk"
    else
        warn "/etc/asterisk not found — Asterisk may not be installed correctly."
        info "Config files are in: $REPO_ROOT/asterisk/etc/asterisk/"
        info "Copy them manually once Asterisk is installed."
    fi
fi

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3 — Ollama LLM
# ═════════════════════════════════════════════════════════════════════════════
step "3" "Ollama LLM"
echo ""
info "Helix AI uses Ollama to run the local LLM (llama3.1:8b)."
echo ""

# Detect if Ollama is already running or reachable on common addresses
detect_ollama() {
    local hosts=("http://localhost:11434" "http://127.0.0.1:11434")
    for h in "${hosts[@]}"; do
        if curl -sf "$h/api/tags" &>/dev/null; then
            echo "$h"
            return 0
        fi
    done
    return 1
}

OLLAMA_HOST_DETECTED=""
if OLLAMA_HOST_DETECTED="$(detect_ollama)"; then
    log "Ollama detected at ${OLLAMA_HOST_DETECTED} — will use it directly."
    OLLAMA_HOST="$OLLAMA_HOST_DETECTED"
    INSTALL_OLLAMA=false
else
    warn "Ollama not found on localhost:11434."
    echo ""
    echo "  Options:"
    echo "  1) Install Ollama on this machine (recommended)"
    echo "  2) Use an existing Ollama on another host (enter its URL)"
    echo "  3) Skip — I will set OLLAMA_HOST manually in agent/.env"
    echo ""
    echo -en "  Choose [1/2/3, default: 1]: "
    read -r OLLAMA_CHOICE
    OLLAMA_CHOICE="${OLLAMA_CHOICE:-1}"

    case "$OLLAMA_CHOICE" in
        2)
            prompt OLLAMA_HOST "Ollama URL (e.g. http://192.168.1.10:11434)" "http://localhost:11434"
            INSTALL_OLLAMA=false
            ;;
        3)
            OLLAMA_HOST="http://localhost:11434"
            INSTALL_OLLAMA=false
            warn "Remember to set OLLAMA_HOST in agent/.env before starting Helix."
            ;;
        *)
            OLLAMA_HOST="http://localhost:11434"
            INSTALL_OLLAMA=true
            ;;
    esac
fi

if [[ "${INSTALL_OLLAMA:-false}" == "true" ]]; then
    if command_exists ollama; then
        log "Ollama binary already installed."
    else
        info "Installing Ollama..."
        curl -fsSL https://ollama.com/install.sh | sh
        log "Ollama installed."
    fi

    # Start ollama serve in background if not running
    if ! curl -sf http://localhost:11434/api/tags &>/dev/null; then
        info "Starting Ollama service..."
        nohup ollama serve >/tmp/ollama.log 2>&1 &
        sleep 3
        if curl -sf http://localhost:11434/api/tags &>/dev/null; then
            log "Ollama service started."
        else
            warn "Ollama did not start cleanly. Check /tmp/ollama.log"
        fi
    else
        log "Ollama service already running."
    fi
fi

# Determine which LLM model to pull
echo ""
prompt OLLAMA_MODEL "Ollama model to use" "llama3.1:8b"

if [[ "${INSTALL_OLLAMA:-false}" == "true" ]] || \
   ( [[ -n "${OLLAMA_HOST_DETECTED}" ]] && prompt_yn _PULL "Pull ${OLLAMA_MODEL} now?" "y" && [[ "$_PULL" == "true" ]] ); then
    info "Pulling ${OLLAMA_MODEL} (this may take a few minutes the first time)..."
    ollama pull "$OLLAMA_MODEL" 2>&1 | tail -3 || \
        warn "Could not pull model. Run manually: ollama pull ${OLLAMA_MODEL}"
    log "Model ${OLLAMA_MODEL} ready."
fi

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4 — Business Identity
# ═════════════════════════════════════════════════════════════════════════════
step "4" "Business Identity"
echo ""
info "These values are spoken in every greeting."
echo ""
prompt BUSINESS_NAME    "Business name (spoken aloud)"  "My Business"
prompt AGENT_NAME       "Receptionist name"              "Alex"
echo ""
info "Timezone must be a valid tz database string."
info "Examples: America/Chicago  America/New_York  America/Los_Angeles"
echo ""
prompt BUSINESS_TIMEZONE "Timezone" "America/Chicago"

section "Business Hours (24-hour integers)"
prompt HOURS_START "Open  (0-23)" "9"
prompt HOURS_END   "Close (0-23)" "17"
while ! [[ "$HOURS_START" =~ ^[0-9]+$ ]] || (( HOURS_START > 23 )); do
    warn "Must be 0–23."
    prompt HOURS_START "Open (0-23)" "9"
done
while ! [[ "$HOURS_END" =~ ^[0-9]+$ ]] || (( HOURS_END > 23 )); do
    warn "Must be 0–23."
    prompt HOURS_END "Close (0-23)" "17"
done

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5 — Security
# ═════════════════════════════════════════════════════════════════════════════
step "5" "Passwords & Security"
echo ""
section "ARI password (secures the Asterisk REST Interface)"
info "Must match between agent/.env and asterisk/etc/asterisk/ari.conf."
echo ""
prompt ARI_PASSWORD "ARI password (min 8 chars)" "" "yes"
while (( ${#ARI_PASSWORD} < 8 )); do
    warn "Password must be at least 8 characters."
    prompt ARI_PASSWORD "ARI password (min 8 chars)" "" "yes"
done

section "SIP extension passwords (used by your softphones to register)"
prompt EXT1001_PASS "Extension 1001 (Operator)" "" "yes"
prompt EXT1002_PASS "Extension 1002 (Sales)"    "" "yes"
prompt EXT1003_PASS "Extension 1003 (Support)"  "" "yes"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 6 — Network
# ═════════════════════════════════════════════════════════════════════════════
step "6" "Network Configuration"
echo ""
info "Asterisk needs to know which LAN address to advertise for SIP and RTP."
echo ""
prompt SERVER_IP   "Server LAN IP (e.g. 192.168.1.100)" ""
prompt LAN_SUBNET  "LAN subnet CIDR (e.g. 192.168.1.0/24)" ""

while ! echo "$SERVER_IP" | grep -qE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'; do
    warn "Enter a valid IP address."
    prompt SERVER_IP "Server LAN IP" ""
done
while ! echo "$LAN_SUBNET" | grep -qE '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}/[0-9]{1,2}$'; do
    warn "Enter a valid CIDR (e.g. 192.168.1.0/24)."
    prompt LAN_SUBNET "LAN subnet CIDR" ""
done

# ═════════════════════════════════════════════════════════════════════════════
# STEP 7 — Extensions & Routing
# ═════════════════════════════════════════════════════════════════════════════
step "7" "Extensions & Routing"
echo ""
prompt OPERATOR_EXTENSION  "Operator / main desk extension"  "1001"
prompt EMERGENCY_EXTENSION "Emergency after-hours extension"  "1001"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 8 — After-Hours Behavior
# ═════════════════════════════════════════════════════════════════════════════
step "8" "After-Hours Behavior"
echo ""
info "What should Helix AI do when called outside business hours?"
echo ""
echo "  1) callback   — Tell caller to call back during hours"
echo "  2) voicemail  — Record a voicemail"
echo "  3) schedule   — Let caller book a callback (AI continues)"
echo "  4) emergency  — Transfer immediately to emergency extension"
echo ""
echo -en "  Choose [1-4, default: 1]: "
read -r AH_CHOICE
AH_CHOICE="${AH_CHOICE:-1}"
case "$AH_CHOICE" in
    2) AFTER_HOURS_MODE="voicemail"  ;;
    3) AFTER_HOURS_MODE="schedule"   ;;
    4) AFTER_HOURS_MODE="emergency"  ;;
    *) AFTER_HOURS_MODE="callback"   ;;
esac
log "After-hours mode: $AFTER_HOURS_MODE"

# ═════════════════════════════════════════════════════════════════════════════
# STEP 9 — Hardware (GPU / CPU)
# ═════════════════════════════════════════════════════════════════════════════
step "9" "Hardware — Whisper Speech Recognition"
echo ""
echo "  1) CUDA GPU — NVIDIA (faster, recommended for production)"
echo "     Sub-second speech recognition. Requires nvidia-container-toolkit for Docker."
echo ""
echo "  2) CPU only — works everywhere"
echo "     3-5 second recognition latency. No GPU required."
echo ""
echo -en "  Choose [1/2, default: 1]: "
read -r GPU_CHOICE
GPU_CHOICE="${GPU_CHOICE:-1}"
case "$GPU_CHOICE" in
    2)
        WHISPER_DEVICE="cpu"
        WHISPER_COMPUTE_TYPE="int8"
        log "CPU mode selected (WHISPER_DEVICE=cpu, WHISPER_COMPUTE_TYPE=int8)."
        ;;
    *)
        WHISPER_DEVICE="cuda"
        WHISPER_COMPUTE_TYPE="float16"
        log "GPU mode selected (WHISPER_DEVICE=cuda, WHISPER_COMPUTE_TYPE=float16)."
        if $IS_LINUX && ! command_exists nvidia-smi; then
            warn "nvidia-smi not found. Make sure your NVIDIA drivers are installed."
            warn "For Docker GPU pass-through: apt-get install nvidia-container-toolkit"
        fi
        ;;
esac

# ═════════════════════════════════════════════════════════════════════════════
# STEP 10 — Write Config Files + Validate
# ═════════════════════════════════════════════════════════════════════════════
step "10" "Writing Configuration"
echo ""

# ── agent/.env ────────────────────────────────────────────────────────────────
section "Writing agent/.env"
cp "$ENV_EXAMPLE" "$ENV_FILE"
set_env "BUSINESS_NAME"        "$BUSINESS_NAME"
set_env "AGENT_NAME"           "$AGENT_NAME"
set_env "BUSINESS_TIMEZONE"    "$BUSINESS_TIMEZONE"
set_env "BUSINESS_HOURS_START" "$HOURS_START"
set_env "BUSINESS_HOURS_END"   "$HOURS_END"
set_env "ASTERISK_ARI_PASSWORD" "$ARI_PASSWORD"
set_env "OLLAMA_HOST"          "$OLLAMA_HOST"
set_env "OLLAMA_MODEL"         "$OLLAMA_MODEL"
set_env "WHISPER_DEVICE"       "$WHISPER_DEVICE"
set_env "WHISPER_COMPUTE_TYPE" "$WHISPER_COMPUTE_TYPE"
set_env "OPERATOR_EXTENSION"   "$OPERATOR_EXTENSION"
set_env "EMERGENCY_EXTENSION"  "$EMERGENCY_EXTENSION"
set_env "AFTER_HOURS_MODE"     "$AFTER_HOURS_MODE"
# If voicemail mode selected, enable voicemail recording automatically
if [[ "$AFTER_HOURS_MODE" == "voicemail" ]]; then
    set_env "VOICEMAIL_ENABLED" "true"
    log "VOICEMAIL_ENABLED=true set (required for after_hours_mode=voicemail)."
fi

if [[ "$DEPLOY_MODE" == "docker" ]]; then
    set_env "AGENT_RTP_HOST"           "0.0.0.0"
    set_env "AGENT_RTP_ADVERTISE_HOST" "agent"
    set_env "ASTERISK_HOST"            "asterisk"
    set_env "OLLAMA_HOST"              "http://ollama:11434"
    # If Ollama was detected locally, keep user's chosen host
    if [[ -n "${OLLAMA_HOST_DETECTED:-}" ]]; then
        set_env "OLLAMA_HOST" "$OLLAMA_HOST"
    fi
fi

log "agent/.env written."

# ── asterisk/ari.conf ─────────────────────────────────────────────────────────
section "Writing ari.conf"
if [[ -f "$ARI_CONF" ]]; then
    replace_in_conf "$ARI_CONF" "CHANGE_ME_ARI_PASSWORD" "$ARI_PASSWORD"
    log "ari.conf updated."
else
    warn "ari.conf not found at expected path: $ARI_CONF"
fi

# ── asterisk/pjsip.conf ───────────────────────────────────────────────────────
section "Writing pjsip.conf"
if [[ -f "$PJSIP_CONF" ]]; then
    # Extension passwords
    replace_in_conf "$PJSIP_CONF" "CHANGE_ME_EXT_1001_PASSWORD" "$EXT1001_PASS"
    replace_in_conf "$PJSIP_CONF" "CHANGE_ME_EXT_1002_PASSWORD" "$EXT1002_PASS"
    replace_in_conf "$PJSIP_CONF" "CHANGE_ME_EXT_1003_PASSWORD" "$EXT1003_PASS"
    # Server IP (external_media_address / external_signaling_address)
    replace_in_conf "$PJSIP_CONF" "YOUR_SERVER_IP" "$SERVER_IP"
    # LAN subnet — replace the broad catch-all default with the actual LAN CIDR
    # pjsip.conf ships with local_net=192.168.0.0/16 as the first local_net line;
    # replace only that line so the RFC-1918 fallbacks (172.16, 10.0) are preserved
    # unless the user's subnet already matches one of them.
    if [[ "$(uname)" == "Darwin" ]]; then
        sed -i '' "s|local_net=192\.168\.0\.0/16.*|local_net=${LAN_SUBNET}|" "$PJSIP_CONF"
    else
        sed -i "s|local_net=192\.168\.0\.0/16.*|local_net=${LAN_SUBNET}|" "$PJSIP_CONF"
    fi
    log "pjsip.conf updated (passwords, server IP, LAN subnet)."
else
    warn "pjsip.conf not found at expected path: $PJSIP_CONF"
fi

# ── Docker: apply config files to containers ──────────────────────────────────
if [[ "$DEPLOY_MODE" == "docker" ]]; then
    if [[ -d /etc/asterisk ]]; then
        info "Copying Asterisk config to /etc/asterisk ..."
        sudo cp -r "$REPO_ROOT/asterisk/etc/asterisk/"* /etc/asterisk/ 2>/dev/null || true
    fi
fi

# ── Firewall (Linux native only) ─────────────────────────────────────────────
# NOTE: 8088 (ARI), 8000 (agent API), 3000 (dashboard) are loopback-only.
# Only SIP, RTP, and nginx (80/443) are opened to the network.
if $IS_LINUX && [[ "$DEPLOY_MODE" == "native" ]]; then
    section "Firewall"
    if command_exists ufw; then
        prompt_yn OPEN_FW "Open required ports in UFW firewall?" "y"
        if [[ "$OPEN_FW" == "true" ]]; then
            sudo ufw allow 22/tcp    comment "SSH"         2>/dev/null || true
            sudo ufw allow 80/tcp    comment "HTTP/nginx"  2>/dev/null || true
            sudo ufw allow 443/tcp   comment "HTTPS/nginx" 2>/dev/null || true
            sudo ufw allow 5060/udp  comment "SIP"         2>/dev/null || true
            sudo ufw allow 5060/tcp  comment "SIP"         2>/dev/null || true
            sudo ufw allow 10000:19999/udp comment "Asterisk RTP"    2>/dev/null || true
            sudo ufw allow 20000:20100/udp comment "Helix Agent RTP" 2>/dev/null || true
            sudo ufw --force enable 2>/dev/null || true
            log "UFW rules: SSH 22, nginx 80/443, SIP 5060, RTP 10000-19999/20000-20100."
            info "ARI (8088), Agent API (8000), Dashboard (3000) stay loopback — served via nginx."
        fi
    elif command_exists firewall-cmd; then
        prompt_yn OPEN_FW "Open required ports in firewalld?" "y"
        if [[ "$OPEN_FW" == "true" ]]; then
            sudo firewall-cmd --permanent --add-service=ssh
            sudo firewall-cmd --permanent --add-service=http
            sudo firewall-cmd --permanent --add-service=https
            sudo firewall-cmd --permanent --add-port=5060/udp
            sudo firewall-cmd --permanent --add-port=5060/tcp
            sudo firewall-cmd --permanent --add-port=10000-19999/udp
            sudo firewall-cmd --permanent --add-port=20000-20100/udp
            sudo firewall-cmd --reload
            log "firewalld rules: SSH, HTTP/HTTPS, SIP 5060, RTP 10000-19999/20000-20100."
            info "ARI (8088), Agent API (8000), Dashboard (3000) stay loopback — served via nginx."
        fi
    else
        info "No UFW or firewalld detected — skipping firewall setup."
        warn "Manually open: 22/tcp, 80/tcp, 443/tcp, 5060/udp, 10000-19999/udp, 20000-20100/udp"
        warn "Do NOT open: 8088 (ARI), 8000 (agent API), 3000 (dashboard) — loopback only."
    fi
fi

# =============================================================================
# STEP 11 — Production Services (native mode only)
# =============================================================================
if $IS_LINUX && [[ "$DEPLOY_MODE" == "native" ]]; then
    step "11" "Production Services (systemd + nginx)"
    echo ""
    info "This step installs Helix AI as proper production services:"
    info "  * Creates a dedicated 'helix' system user (no login shell)"
    info "  * Copies the repo to /opt/helix/ and sets ownership"
    info "  * Installs systemd units for the agent and dashboard"
    info "  * Installs and enables nginx as the reverse proxy"
    info "  * Locks down .env permissions to 600"
    echo ""
    prompt_yn SETUP_PRODUCTION "Set up production systemd + nginx now?" "y"

    if [[ "$SETUP_PRODUCTION" == "true" ]]; then
        INSTALL_PATH="/opt/helix"

        section "Creating helix system user"
        if id helix &>/dev/null; then
            log "User 'helix' already exists."
        else
            sudo useradd -r -s /sbin/nologin -d "$INSTALL_PATH" helix
            log "System user 'helix' created (no login shell)."
        fi

        section "Copying repo to $INSTALL_PATH"
        if [[ "$(realpath "$REPO_ROOT")" != "$INSTALL_PATH" ]]; then
            sudo mkdir -p "$INSTALL_PATH"
            # Remove stale agent/calendar/ if source now ships agent/gcal/.
            # rsync does not delete old target directories by default, so without
            # this step the old package survives and shadows Python's stdlib calendar.
            if [[ -d "$REPO_ROOT/agent/gcal" ]] && [[ -d "$INSTALL_PATH/agent/calendar" ]]; then
                warn "Removing stale $INSTALL_PATH/agent/calendar/ (shadowed stdlib — replaced by gcal/)"
                sudo rm -rf "$INSTALL_PATH/agent/calendar"
            fi
            sudo rsync -a --exclude=".git" --exclude="agent/.venv" "$REPO_ROOT/" "$INSTALL_PATH/"
            if [[ -d "$AGENT_VENV" ]]; then
                sudo cp -r "$AGENT_VENV" "$INSTALL_PATH/agent/.venv"
            fi
            sudo chown -R helix:helix "$INSTALL_PATH"
            log "Repo deployed to $INSTALL_PATH."
        else
            sudo chown -R helix:helix "$INSTALL_PATH"
            log "Already at $INSTALL_PATH — ownership updated."
        fi

        section "Locking down .env permissions"
        ENV_PROD="$INSTALL_PATH/agent/.env"
        if [[ ! -f "$ENV_PROD" ]] && [[ -f "$ENV_FILE" ]]; then
            sudo cp "$ENV_FILE" "$ENV_PROD"
        fi
        if [[ -f "$ENV_PROD" ]]; then
            sudo chmod 600 "$ENV_PROD"
            sudo chown helix:helix "$ENV_PROD"
            log ".env: chmod 600, owner helix:helix."
        else
            warn ".env not found at $ENV_PROD — copy agent/.env there manually after setup."
        fi

        section "Building dashboard (native)"
        DASHBOARD_DIR="$INSTALL_PATH/dashboard"
        if [[ -d "$DASHBOARD_DIR" ]]; then
            # Check Node.js is available
            if ! command_exists node; then
                info "Node.js not found — installing via NodeSource (LTS)..."
                curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
                sudo apt-get install -y nodejs
                log "Node.js $(node --version) installed."
            else
                log "Node.js $(node --version) already installed."
            fi
            info "Installing dashboard dependencies..."
            # Use npm ci if lockfile is present (faster, reproducible).
            # Fall back to npm install if lockfile is absent (generates one).
            if [[ -f "$DASHBOARD_DIR/package-lock.json" ]]; then
                sudo -u helix bash -c "cd '$DASHBOARD_DIR' && npm ci --ignore-scripts" 2>&1 | tail -5
            else
                warn "No package-lock.json found — running npm install (slower first run)."
                sudo -u helix bash -c "cd '$DASHBOARD_DIR' && npm install --ignore-scripts" 2>&1 | tail -5
            fi
            info "Building dashboard production bundle (npm run build)..."
            sudo -u helix bash -c "cd '$DASHBOARD_DIR' && npm run build" 2>&1 | tail -5
            if [[ -f "$DASHBOARD_DIR/dist/index.cjs" ]]; then
                log "Dashboard built successfully: dist/index.cjs ready."
            else
                warn "Dashboard build may have failed — dist/index.cjs not found."
                warn "Manual recovery: sudo -u helix bash -c 'cd $DASHBOARD_DIR && npm install --ignore-scripts && npm run build'"
            fi
        else
            warn "Dashboard directory not found at $DASHBOARD_DIR — skipping build."
        fi

        section "Installing systemd units"
        # Pre-flight: check if the default dashboard port (3000) is already bound.
        # If it is, prompt for an alternate port and patch the service + nginx config.
        DASHBOARD_PORT=3000
        if ss -tlnH 2>/dev/null | awk '{print $4}' | grep -qE ":(${DASHBOARD_PORT})$"; then
            warn "Port ${DASHBOARD_PORT} is already in use on this host."
            read -rp "  Enter alternate dashboard port [default: 3001]: " ALT_PORT
            DASHBOARD_PORT="${ALT_PORT:-3001}"
            log "Dashboard will use port $DASHBOARD_PORT."
            # Patch the dashboard service file in the install path
            if [[ -f "$INSTALL_PATH/systemd/helix-dashboard.service" ]]; then
                sudo sed -i "s/PORT=3000/PORT=${DASHBOARD_PORT}/g" \
                    "$INSTALL_PATH/systemd/helix-dashboard.service"
                log "Patched helix-dashboard.service: PORT=${DASHBOARD_PORT}"
            fi
            # Patch nginx config to point to the alternate port
            if [[ -f "$INSTALL_PATH/deploy/nginx-helix.conf" ]]; then
                sudo sed -i "s/127\.0\.0\.1:3000/127.0.0.1:${DASHBOARD_PORT}/g" \
                    "$INSTALL_PATH/deploy/nginx-helix.conf"
                log "Patched nginx-helix.conf: dashboard upstream → 127.0.0.1:${DASHBOARD_PORT}"
            fi
        fi
        SYSTEMD_SRC="$INSTALL_PATH/systemd"
        if [[ -d "$SYSTEMD_SRC" ]]; then
            for unit in helix-agent.service helix-dashboard.service; do
                if [[ -f "$SYSTEMD_SRC/$unit" ]]; then
                    sudo sed "s|/opt/helix|${INSTALL_PATH}|g" "$SYSTEMD_SRC/$unit" \
                        | sudo tee "/etc/systemd/system/$unit" > /dev/null
                    log "Installed /etc/systemd/system/$unit"
                fi
            done
            sudo systemctl daemon-reload
            sudo systemctl enable helix-agent helix-dashboard
            log "helix-agent and helix-dashboard enabled."
            prompt_yn START_NOW "Start Helix services now?" "y"
            if [[ "$START_NOW" == "true" ]]; then
                sudo systemctl start asterisk  2>/dev/null || warn "Could not start asterisk — run: sudo systemctl start asterisk"
                sudo systemctl start helix-agent
                sudo systemctl start helix-dashboard
                sleep 2
                systemctl is-active helix-agent      &>/dev/null && log  "helix-agent:     running" || warn "helix-agent:     failed — check: journalctl -u helix-agent"
                systemctl is-active helix-dashboard  &>/dev/null && log  "helix-dashboard: running" || warn "helix-dashboard: failed — check: journalctl -u helix-dashboard"
            fi
        else
            warn "systemd/ directory not found at $SYSTEMD_SRC — skipping."
            warn "Expected: $SYSTEMD_SRC/helix-agent.service and helix-dashboard.service"
        fi

        section "Installing nginx"
        if ! command_exists nginx; then
            info "Installing nginx..."
            sudo apt-get install -y nginx
        else
            log "nginx already installed."
        fi
        NGINX_CONF="$INSTALL_PATH/deploy/nginx-helix.conf"
        NGINX_MAP_CONF="$INSTALL_PATH/deploy/nginx-helix-map.conf"
        if [[ -f "$NGINX_CONF" ]]; then
            # Install the WebSocket upgrade map into nginx http context (conf.d)
            # This MUST be copied before nginx -t or the config test will fail.
            if [[ -f "$NGINX_MAP_CONF" ]]; then
                sudo mkdir -p /etc/nginx/conf.d
                sudo cp "$NGINX_MAP_CONF" /etc/nginx/conf.d/helix-map.conf
                log "nginx WebSocket map installed: /etc/nginx/conf.d/helix-map.conf"
            else
                # Fallback: write the map inline if the file is missing
                sudo tee /etc/nginx/conf.d/helix-map.conf > /dev/null <<'NGINX_MAP'
map $http_upgrade $helix_connection_upgrade {
    default  upgrade;
    ''       close;
}
NGINX_MAP
                log "nginx WebSocket map written inline to /etc/nginx/conf.d/helix-map.conf"
            fi
            sudo cp "$NGINX_CONF" /etc/nginx/sites-available/helix
            prompt NGINX_DOMAIN "Public domain or server IP for nginx server_name" "$SERVER_IP"
            sudo sed -i "s|server_name _;|server_name ${NGINX_DOMAIN};|g" /etc/nginx/sites-available/helix
            sudo ln -sf /etc/nginx/sites-available/helix /etc/nginx/sites-enabled/helix
            sudo rm -f /etc/nginx/sites-enabled/default
            sudo nginx -t 2>&1 && {
                sudo systemctl enable --now nginx
                log "nginx running. Dashboard: http://${NGINX_DOMAIN}/  |  API: http://${NGINX_DOMAIN}/api/"
            } || warn "nginx config test failed — check: /etc/nginx/sites-available/helix"
        else
            warn "deploy/nginx-helix.conf not found — install nginx manually using deploy/nginx-helix.conf."
        fi

        section "Binding Ollama to loopback (127.0.0.1:11434)"
        sudo mkdir -p /etc/systemd/system/ollama.service.d
        sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<'OLLAMA_OVERRIDE'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
OLLAMA_OVERRIDE
        sudo systemctl daemon-reload
        if systemctl is-active ollama &>/dev/null; then
            sudo systemctl restart ollama
            log "Ollama restarted — bound to 127.0.0.1:11434."
        else
            log "Ollama override installed. Start with: sudo systemctl start ollama"
        fi

    else
        info "Skipping production service setup."
        warn "To set up later: see systemd/ and deploy/ directories, or the Production section in README.md"
    fi
fi

# ── Google Calendar OAuth (optional) ─────────────────────────────────────────
header "Optional — Google Calendar Integration"

echo "  Helix AI can schedule callback appointments using Google Calendar."
echo "  This requires a Google Cloud service account JSON credentials file."
echo ""
prompt_yn SETUP_GCAL "Set up Google Calendar now?" "n"

if [[ "$SETUP_GCAL" == "true" ]]; then
    info "Steps to get credentials.json:"
    echo ""
    echo "    1. Go to https://console.cloud.google.com/"
    echo "    2. Create a project and enable the Google Calendar API"
    echo "    3. Create OAuth2 credentials → Desktop App"
    echo "    4. Download the JSON file and place it at: ${REPO_ROOT}/agent/credentials.json"
    echo ""
    echo "  Once the file is in place, run the agent once and follow the"
    echo "  browser OAuth flow to generate token.json."
    echo ""
    read -rp "  Press Enter when credentials.json is in place (or Enter to skip)..."
    if [[ -f "$REPO_ROOT/agent/credentials.json" ]]; then
        log "credentials.json found."
    else
        warn "credentials.json not found — Google Calendar will be disabled until you add it."
    fi
fi

# ── Validation ────────────────────────────────────────────────────────────────
header "Validating Installation"
echo ""
VALIDATION_PASSED=true

# Ollama
info "Checking Ollama..."
OLLAMA_CHECK_HOST="${OLLAMA_HOST_DETECTED:-$OLLAMA_HOST}"
if curl -sf "${OLLAMA_CHECK_HOST}/api/tags" &>/dev/null; then
    log "Ollama is reachable at ${OLLAMA_CHECK_HOST}."
else
    warn "Cannot reach Ollama at ${OLLAMA_CHECK_HOST}."
    warn "Start it with: ollama serve"
    VALIDATION_PASSED=false
fi

# espeak-ng
info "Checking espeak-ng..."
if command_exists espeak-ng; then
    log "espeak-ng available."
else
    if [[ "$DEPLOY_MODE" == "native" ]]; then
        warn "espeak-ng not found. Install: sudo apt-get install espeak-ng"
        VALIDATION_PASSED=false
    else
        info "espeak-ng will be installed inside the Docker container."
    fi
fi

# Kokoro (native mode only)
if [[ "$DEPLOY_MODE" == "native" ]]; then
    info "Checking Kokoro TTS..."
    if "$VENV_PYTHON" -c "from kokoro import KPipeline" 2>/dev/null; then
        log "Kokoro TTS installed."
    else
        warn "Kokoro not importable. Run: ${VENV_PIP} install kokoro>=0.9.2 soundfile misaki[en]"
        VALIDATION_PASSED=false
    fi
fi

# Asterisk (native mode)
if [[ "$DEPLOY_MODE" == "native" ]]; then
    info "Checking Asterisk..."
    if command_exists asterisk; then
        log "Asterisk binary found: $(asterisk -V 2>&1 | head -1)."
    else
        warn "Asterisk not found."
        VALIDATION_PASSED=false
    fi
fi

# Docker (docker mode)
if [[ "$DEPLOY_MODE" == "docker" ]]; then
    info "Checking Docker..."
    if docker info &>/dev/null; then
        log "Docker is running."
    else
        warn "Docker daemon not running. Start it with: sudo systemctl start docker"
        VALIDATION_PASSED=false
    fi
fi

# ── Final summary ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${BOLD}${CYAN}  Setup Complete — Helix AI ${HELIX_VERSION}${NC}"
echo -e "${BOLD}${CYAN}══════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Business:${NC}     $BUSINESS_NAME  (receptionist: $AGENT_NAME)"
echo -e "  ${BOLD}Hours:${NC}        ${HOURS_START}:00 – ${HOURS_END}:00  ($BUSINESS_TIMEZONE)"
echo -e "  ${BOLD}After hours:${NC}  $AFTER_HOURS_MODE"
echo -e "  ${BOLD}LLM:${NC}          $OLLAMA_MODEL  at $OLLAMA_HOST"
echo -e "  ${BOLD}Whisper:${NC}      $WHISPER_DEVICE / $WHISPER_COMPUTE_TYPE"
echo -e "  ${BOLD}TTS:${NC}          Kokoro (EN/ES/FR/IT) + espeak-ng (DE/RO/HE)"
echo -e "  ${BOLD}Install mode:${NC} $DEPLOY_MODE"
echo ""

if [[ "$VALIDATION_PASSED" == "true" ]]; then
    echo -e "  ${GREEN}${BOLD}All checks passed.${NC}"
else
    echo -e "  ${YELLOW}${BOLD}Some checks failed — see warnings above.${NC}"
fi

echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo ""
if [[ "$DEPLOY_MODE" == "docker" ]]; then
    echo -e "    1. Start Helix AI:"
    echo -e "       ${CYAN}./deploy.sh --pull${NC}   (first time — builds containers + pulls model)"
    echo -e "       ${CYAN}./deploy.sh${NC}           (subsequent starts)"
    echo ""
    echo -e "    2. Register a softphone (e.g. Zoiper) to ${BOLD}${SERVER_IP}${NC}"
    echo -e "       Extension: 1001–1003  |  SIP port: 5060"
    echo ""
    echo -e "    3. Dial ${BOLD}9999${NC} to reach the AI receptionist."
    echo ""
    echo -e "    4. Dashboard: ${CYAN}http://${SERVER_IP}:3000${NC}"
    echo -e "       API:       ${CYAN}http://${SERVER_IP}:8000/docs${NC}"
else
    echo -e "    1. Verify all services are running:"
    echo -e "       ${CYAN}systemctl status helix-agent helix-dashboard asterisk ollama nginx${NC}"
    echo ""
    echo -e "    2. If anything is not running:"
    echo -e "       ${CYAN}sudo systemctl start asterisk${NC}"
    echo -e "       ${CYAN}sudo systemctl start ollama${NC}"
    echo -e "       ${CYAN}sudo systemctl start helix-agent helix-dashboard${NC}"
    echo ""
    echo -e "    3. Register a softphone (e.g. Zoiper) to ${BOLD}${SERVER_IP}${NC}"
    echo -e "       Extension: 1001–1003  |  SIP port: 5060"
    echo ""
    echo -e "    4. Dial ${BOLD}9999${NC} to reach the AI receptionist."
    echo ""
    echo -e "    5. Dashboard: ${CYAN}http://${SERVER_IP}/${NC}   (via nginx)"
    echo -e "       API docs:  ${CYAN}http://${SERVER_IP}/api/docs${NC}   (via nginx)"
    echo ""
    echo -e "    ${YELLOW}Tail logs:${NC}"
    echo -e "       ${CYAN}journalctl -fu helix-agent${NC}     — AI agent"
    echo -e "       ${CYAN}journalctl -fu helix-dashboard${NC}  — dashboard"
    echo -e "       ${CYAN}tail -f /var/log/asterisk/full${NC}  — Asterisk"
fi

echo ""
echo -e "  Edit ${CYAN}agent/.env${NC} to change any setting at any time."
echo ""
if [[ -f "$REPO_ROOT/docs/zoiper-setup.md" ]]; then
    echo -e "  Softphone setup guide: ${CYAN}docs/zoiper-setup.md${NC}"
fi
echo ""
echo -e "${BOLD}  ${GREEN}Helix AI is ready.${NC}"
echo ""
