#!/usr/bin/env bash
# Start K1 AI Desktop with the app's own virtual environment.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/streamlit ]; then
    echo "Creating .venv and installing requirements..."
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/streamlit run app.py "$@"
