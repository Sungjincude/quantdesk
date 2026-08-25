#!/usr/bin/env bash
# QuantDesk installer — Linux & macOS. Run:  ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "== QuantDesk installer =="

if command -v uv >/dev/null 2>&1; then
    echo "[*] creating venv with uv (fetches Python 3.11 if needed)"
    uv venv .venv --python 3.11
    echo "[*] installing dependencies"
    uv pip install --python .venv/bin/python -r requirements.txt
elif command -v python3 >/dev/null 2>&1 \
     && python3 -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null \
     && python3 -m venv .venv 2>/dev/null; then
    echo "[*] created venv with $(python3 -V)"
    echo "[*] installing dependencies"
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -r requirements.txt
else
    echo "!! Could not create a Python environment."
    echo "   Easiest fix — install uv (https://docs.astral.sh/uv/):"
    echo "      curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "   Or on Debian/Mint/Ubuntu:"
    echo "      sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

echo "[ok] installed. Start the app with:  ./run.sh"
