#!/usr/bin/env bash
# First-time setup script
set -e

echo "=== PBX Assistant Setup ==="

# Copy env file
if [ ! -f agent/.env ]; then
    cp agent/.env.example agent/.env
    echo "[✓] Created agent/.env — edit it with your settings"
fi

# Install Piper TTS locally (for non-Docker use)
if ! command -v piper &>/dev/null; then
    echo "[*] Installing Piper TTS..."
    PIPER_VERSION="2023.11.14-2"
    wget -q "https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_x86_64.tar.gz" \
        -O /tmp/piper.tar.gz
    sudo tar -xzf /tmp/piper.tar.gz -C /usr/local/bin/
    rm /tmp/piper.tar.gz
    echo "[✓] Piper installed"
fi

# Download Piper voice model
PIPER_MODEL_DIR="/opt/piper/models"
sudo mkdir -p "$PIPER_MODEL_DIR"
if [ ! -f "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx" ]; then
    echo "[*] Downloading Piper voice model..."
    sudo wget -q \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" \
        -O "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx"
    sudo wget -q \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" \
        -O "$PIPER_MODEL_DIR/en_US-lessac-medium.onnx.json"
    echo "[✓] Piper voice model downloaded"
fi

# Install Python dependencies
echo "[*] Installing Python dependencies..."
cd agent
pip install -r requirements.txt
cd ..
echo "[✓] Python deps installed"

# Pull Ollama model
if command -v ollama &>/dev/null; then
    echo "[*] Pulling Ollama model (llama3.1:8b)..."
    ollama pull llama3.1:8b
    echo "[✓] Model ready"
else
    echo "[!] Ollama not found. Install from https://ollama.com and run: ollama pull llama3.1:8b"
fi

echo ""
echo "=== Next steps ==="
echo "1. Edit agent/.env with your Asterisk and Google credentials"
echo "2. Place your Google OAuth credentials.json in agent/"
echo "3. Run: python agent/main.py  (or: docker compose up)"
echo ""
echo "Google Calendar auth: python -c \"from agent.calendar.gcal import _get_service; _get_service()\""
