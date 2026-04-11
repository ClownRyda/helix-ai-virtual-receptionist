#!/usr/bin/env bash
# ============================================================
# PBX Assistant — One-Shot Deploy Script
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh          # Build and start everything
#   ./deploy.sh --down   # Stop everything
#   ./deploy.sh --logs   # Tail all logs
#   ./deploy.sh --pull   # Pull latest Ollama model then start
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"
ENV_FILE="$SCRIPT_DIR/agent/.env"
ENV_EXAMPLE="$SCRIPT_DIR/agent/.env.example"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[PBX]${NC} $*"; }
warn() { echo -e "${YELLOW}[PBX]${NC} $*"; }
err()  { echo -e "${RED}[PBX]${NC} $*" >&2; }

# ── Handle flags ──────────────────────────────────────────────

if [[ "${1:-}" == "--down" ]]; then
    log "Stopping all services..."
    docker compose -f "$COMPOSE_FILE" down
    log "Done."
    exit 0
fi

if [[ "${1:-}" == "--logs" ]]; then
    docker compose -f "$COMPOSE_FILE" logs -f --tail=100
    exit 0
fi

# ── Pre-flight checks ────────────────────────────────────────

log "Running pre-flight checks..."

# Docker
if ! command -v docker &>/dev/null; then
    err "Docker is not installed. Install it first: https://docs.docker.com/engine/install/ubuntu/"
    exit 1
fi

# Docker Compose v2
if ! docker compose version &>/dev/null; then
    err "Docker Compose v2 not found. Install docker-compose-plugin."
    exit 1
fi

# NVIDIA Container Toolkit
if ! docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null 2>&1; then
    warn "NVIDIA GPU test failed. Whisper will fall back to CPU."
    warn "To fix: install nvidia-container-toolkit and restart Docker."
fi

# .env file
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        log "Creating .env from .env.example..."
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        warn "Edit $ENV_FILE to set your passwords and business info."
        warn "At minimum, change ASTERISK_ARI_PASSWORD and review BUSINESS_NAME."
    else
        err "No .env file found at $ENV_FILE"
        exit 1
    fi
fi

# Google Calendar credentials (optional but warn)
if [[ ! -f "$SCRIPT_DIR/agent/credentials.json" ]]; then
    warn "No Google Calendar credentials.json found."
    warn "Calendar scheduling will not work until you add it."
    warn "See: https://developers.google.com/calendar/api/quickstart/python"
fi

echo ""
log "============================================"
log "  PBX Assistant — Docker Deployment"
log "============================================"
echo ""

# ── Pull Ollama model if requested ────────────────────────────

OLLAMA_MODEL=$(grep -E "^OLLAMA_MODEL=" "$ENV_FILE" | cut -d= -f2 || echo "qwen3:8b")

if [[ "${1:-}" == "--pull" ]]; then
    log "Pulling Ollama model: $OLLAMA_MODEL"
    log "Starting Ollama container first..."
    docker compose -f "$COMPOSE_FILE" up -d ollama
    sleep 5
    docker exec pbx-ollama ollama pull "$OLLAMA_MODEL"
    log "Model pulled. Continuing with full startup..."
fi

# ── Build and start ───────────────────────────────────────────

log "Building containers (this may take a few minutes on first run)..."
docker compose -f "$COMPOSE_FILE" build

log "Starting services..."
docker compose -f "$COMPOSE_FILE" up -d

echo ""
log "Waiting for services to come up..."

# Wait for Asterisk
echo -n "[PBX] Asterisk: "
for i in $(seq 1 30); do
    if docker exec pbx-asterisk asterisk -rx "core show version" &>/dev/null 2>&1; then
        echo -e "${GREEN}ready${NC}"
        break
    fi
    echo -n "."
    sleep 2
done

# Wait for Ollama
echo -n "[PBX] Ollama:   "
for i in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/tags &>/dev/null; then
        echo -e "${GREEN}ready${NC}"
        break
    fi
    echo -n "."
    sleep 2
done

# Check if model is downloaded
if ! curl -sf http://localhost:11434/api/tags | grep -q "$OLLAMA_MODEL" 2>/dev/null; then
    warn "Ollama model '$OLLAMA_MODEL' not found. Pulling now..."
    docker exec pbx-ollama ollama pull "$OLLAMA_MODEL"
fi

# Wait for Agent
echo -n "[PBX] Agent:    "
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/health &>/dev/null 2>&1; then
        echo -e "${GREEN}ready${NC}"
        break
    fi
    if [[ $i -eq 30 ]]; then
        echo -e "${YELLOW}timeout (check: docker compose -f $COMPOSE_FILE logs agent)${NC}"
    fi
    echo -n "."
    sleep 2
done

# Wait for Dashboard
echo -n "[PBX] Dashboard:"
for i in $(seq 1 15); do
    if curl -sf http://localhost:3000 &>/dev/null 2>&1; then
        echo -e " ${GREEN}ready${NC}"
        break
    fi
    if [[ $i -eq 15 ]]; then
        echo -e " ${YELLOW}timeout (check: docker compose -f $COMPOSE_FILE logs dashboard)${NC}"
    fi
    echo -n "."
    sleep 2
done

echo ""
log "============================================"
log "  All services started"
log "============================================"
echo ""
echo -e "  ${CYAN}Dashboard:${NC}   http://192.168.4.31:3000"
echo -e "  ${CYAN}Agent API:${NC}   http://192.168.4.31:8000"
echo -e "  ${CYAN}ARI:${NC}         http://192.168.4.31:8088"
echo -e "  ${CYAN}Ollama:${NC}      http://192.168.4.31:11434"
echo ""
echo -e "  ${CYAN}SIP Server:${NC}  192.168.4.31:5060/UDP"
echo -e "  ${CYAN}Extensions:${NC}  1001 (test1001) / 1002 (test1002) / 1003 (test1003)"
echo -e "  ${CYAN}AI Number:${NC}   ${GREEN}9999${NC}"
echo ""
log "Register a softphone (Zoiper) and dial 9999 to test the AI."
log "See docs/zoiper-setup.md for step-by-step instructions."
echo ""
log "Useful commands:"
echo "  ./deploy.sh --logs    # Tail all logs"
echo "  ./deploy.sh --down    # Stop everything"
echo "  docker compose -f docker/docker-compose.yml logs agent -f   # Agent logs only"
echo "  docker exec -it pbx-asterisk asterisk -rvvv                 # Asterisk CLI"
