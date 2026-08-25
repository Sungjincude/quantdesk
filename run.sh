#!/usr/bin/env bash
# QuantDesk launcher — Linux & macOS. Starts server, opens browser.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    ./install.sh
fi

.venv/bin/python -m uvicorn quantdesk.server:app --host 127.0.0.1 --port 8600 &
SPID=$!

# wait for the API to come up (max ~20s), then open a browser tab
for i in $(seq 1 20); do
    if command -v curl >/dev/null 2>&1; then
        curl -s -o /dev/null http://127.0.0.1:8600/api/config && break
    else
        sleep 3; break
    fi
    sleep 1
done
xdg-open http://127.0.0.1:8600 >/dev/null 2>&1 \
    || open http://127.0.0.1:8600 >/dev/null 2>&1 || true

echo "QuantDesk running at http://127.0.0.1:8600  (Ctrl+C to stop)"
wait $SPID
