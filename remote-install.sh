#!/usr/bin/env bash
# QuantDesk zero-setup bootstrap (Linux/macOS):
#   curl -sL https://raw.githubusercontent.com/Sungjincude/quantdesk/main/remote-install.sh | bash
set -euo pipefail
DEST="${QUANTDESK_HOME:-$HOME/quantdesk}"

if [ -d "$DEST/.git" ]; then
    echo "[*] existing QuantDesk clone found at $DEST - updating"
    git -C "$DEST" pull --ff-only
else
    echo "[*] cloning QuantDesk into $DEST"
    git clone --depth 1 https://github.com/Sungjincude/quantdesk.git "$DEST"
fi

"$DEST/install.sh"

echo ""
echo "[ok] all set. Open a NEW terminal, then run from anywhere:"
echo "         quantdesk"
