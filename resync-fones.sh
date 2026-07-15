#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

CONFIG_FILE="${BLUETOOTH_SPLIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/linux-bluetooth-split-stereo/config}"

if [[ -r "$CONFIG_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
fi

: "${LEFT_MAC:?Set LEFT_MAC in $CONFIG_FILE}"
: "${RIGHT_MAC:?Set RIGHT_MAC in $CONFIG_FILE}"

SPLIT_SCRIPT="${SPLIT_SCRIPT:-$SCRIPT_DIR/split-fones.sh}"

if ! command -v bluetoothctl >/dev/null 2>&1; then
    echo "Error: bluetoothctl not found."
    exit 1
fi

if [[ ! -x "$SPLIT_SCRIPT" ]]; then
    echo "Split script not found or not executable: $SPLIT_SCRIPT"
    exit 1
fi

echo "Disconnecting headphones..."

bluetoothctl disconnect "$LEFT_MAC" || true
bluetoothctl disconnect "$RIGHT_MAC" || true

sleep 3

echo "Connecting headphones..."

bluetoothctl connect "$LEFT_MAC" || true
bluetoothctl connect "$RIGHT_MAC" || true

sleep 2

echo "Reapplying split stereo..."
"$SPLIT_SCRIPT"

if command -v playerctl >/dev/null 2>&1; then
    playerctl play >/dev/null 2>&1 || true
fi

echo "Done. Headphones resynced."
