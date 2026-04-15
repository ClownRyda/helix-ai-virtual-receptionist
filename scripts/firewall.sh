#!/usr/bin/env bash
# ============================================================
# PBX Assistant — Host Firewall Rules (UFW)
# Run once on the Ubuntu server
#
# Opens only what's needed for LAN softphone testing.
# All rules are scoped to the LAN subnet you pass in.
# ============================================================

set -euo pipefail

SUBNET="${1:-${PBX_LAN_SUBNET:-YOUR_LAN_SUBNET}}"  # e.g. 10.0.0.0/24

echo "=== PBX Assistant Firewall Setup ==="
echo "Allowing traffic from $SUBNET only"
echo ""

# Ensure UFW is installed and enabled
if ! command -v ufw &>/dev/null; then
    echo "Installing UFW..."
    sudo apt-get update && sudo apt-get install -y ufw
fi

# ── SIP signaling ─────────────────────────────────────────────
echo "[+] SIP 5060/udp (Asterisk signaling)"
sudo ufw allow from $SUBNET to any port 5060 proto udp comment "PBX: SIP signaling"

echo "[+] SIP 5060/tcp (Asterisk signaling - TCP fallback)"
sudo ufw allow from $SUBNET to any port 5060 proto tcp comment "PBX: SIP signaling TCP"

# ── RTP media ─────────────────────────────────────────────────
echo "[+] RTP 10000-20000/udp (Asterisk media)"
sudo ufw allow from $SUBNET to any port 10000:20000 proto udp comment "PBX: Asterisk RTP"

echo "[+] RTP 20000-20100/udp (Agent ExternalMedia)"
sudo ufw allow from $SUBNET to any port 20000:20100 proto udp comment "PBX: Agent RTP"

# ── ARI (Asterisk REST Interface) ─────────────────────────────
echo "[+] ARI 8088/tcp (Asterisk HTTP/WebSocket)"
sudo ufw allow from $SUBNET to any port 8088 proto tcp comment "PBX: ARI HTTP"

# ── Agent REST API ────────────────────────────────────────────
echo "[+] API 8000/tcp (Python agent)"
sudo ufw allow from $SUBNET to any port 8000 proto tcp comment "PBX: Agent API"

# ── Dashboard ─────────────────────────────────────────────────
echo "[+] Dashboard 3000/tcp (React UI)"
sudo ufw allow from $SUBNET to any port 3000 proto tcp comment "PBX: Dashboard"

# ── Ollama (optional — only if accessing from other machines) ─
echo "[+] Ollama 11434/tcp (LLM API — LAN only)"
sudo ufw allow from $SUBNET to any port 11434 proto tcp comment "PBX: Ollama LLM"

# ── Enable UFW if not already ──────────────────────────────────
if sudo ufw status | grep -q "Status: inactive"; then
    echo ""
    echo "UFW is inactive. Enabling with default deny incoming..."
    sudo ufw default deny incoming
    sudo ufw default allow outgoing
    # Make sure SSH stays open!
    sudo ufw allow ssh comment "SSH access"
    sudo ufw --force enable
fi

echo ""
echo "=== Firewall rules applied ==="
sudo ufw status numbered
echo ""
echo "Ports open on LAN ($SUBNET):"
echo "  5060/udp+tcp  — SIP signaling"
echo "  8088/tcp      — ARI WebSocket"
echo "  8000/tcp      — Agent REST API"
echo "  3000/tcp      — Dashboard"
echo "  10000-20100   — RTP media"
echo "  11434/tcp     — Ollama LLM"
