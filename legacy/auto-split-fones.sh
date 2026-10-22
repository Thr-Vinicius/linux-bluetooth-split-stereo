#!/usr/bin/env bash
set -euo pipefail
# Compatibility one-shot waiter. The native owner/watchdog must already run.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
for ((attempt = 0; attempt < 60; attempt++)); do
    if status=$(python3 "$SCRIPT_DIR/bluetooth-split-controller.py" status 2>/dev/null) &&
       [[ "$status" == *'"state": "ROUTED"'* ]]; then
        exec "$SCRIPT_DIR/split-fones.sh"
    fi
    sleep 2
done
printf '%s\n' 'Both headphone routes did not become ready within 120 seconds.' >&2
exit 1
