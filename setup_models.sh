#!/usr/bin/env bash
# Move Ollama models into ./models and point the Ollama service at them.
# Run as your normal user (not with sudo); it asks for sudo when needed.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
MODELS_DIR="$APP_DIR/models"
OLD_DIR="/usr/share/ollama/.ollama/models"
ME="$(id -un)"

mkdir -p "$MODELS_DIR"

echo "Stopping Ollama..."
sudo systemctl stop ollama

if [ -d "$OLD_DIR" ] && [ -n "$(sudo ls -A "$OLD_DIR")" ]; then
    echo "Moving models from $OLD_DIR to $MODELS_DIR..."
    sudo sh -c "mv '$OLD_DIR'/* '$MODELS_DIR'/"
fi
sudo chown -R "$ME:$ME" "$MODELS_DIR"

echo "Configuring Ollama service..."
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null <<CONF
[Service]
User=$ME
Group=$ME
Environment="OLLAMA_MODELS=$MODELS_DIR"
CONF

sudo systemctl daemon-reload
sudo systemctl start ollama
sleep 2
ollama list
