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
: "${LEFT_DEVICE:?Set LEFT_DEVICE in $CONFIG_FILE}"
: "${RIGHT_DEVICE:?Set RIGHT_DEVICE in $CONFIG_FILE}"

SPLIT_SCRIPT="${SPLIT_SCRIPT:-$SCRIPT_DIR/split-fones.sh}"

CONNECT_TIMEOUT="${CONNECT_TIMEOUT:-25}"
CONNECT_RETRY_INTERVAL="${CONNECT_RETRY_INTERVAL:-3}"
POST_CONNECT_SETTLE="${POST_CONNECT_SETTLE:-2}"

for command_name in bluetoothctl pactl; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Error: $command_name not found."
        exit 1
    fi
done

if [[ ! -x "$SPLIT_SCRIPT" ]]; then
    echo "Split script not found or not executable: $SPLIT_SCRIPT"
    exit 1
fi

sink_exists() {
    pactl list short sinks 2>/dev/null |
        awk -v target="$1" '
            $2 == target {
                found = 1
            }

            END {
                exit(found ? 0 : 1)
            }
        '
}

both_sinks_exist() {
    sink_exists "$LEFT_DEVICE" &&
        sink_exists "$RIGHT_DEVICE"
}

connect_missing_devices() {
    if ! sink_exists "$LEFT_DEVICE"; then
        echo "Connecting left headphone..."
        bluetoothctl connect "$LEFT_MAC" >/dev/null 2>&1 || true
    fi

    if ! sink_exists "$RIGHT_DEVICE"; then
        echo "Connecting right headphone..."
        bluetoothctl connect "$RIGHT_MAC" >/dev/null 2>&1 || true
    fi
}

wait_for_both_devices() {
    local deadline
    local next_retry=0

    deadline=$((SECONDS + CONNECT_TIMEOUT))

    while (( SECONDS < deadline )); do
        if both_sinks_exist; then
            echo "Both Bluetooth devices are available."
            return 0
        fi

        if (( SECONDS >= next_retry )); then
            connect_missing_devices
            next_retry=$((SECONDS + CONNECT_RETRY_INTERVAL))
        fi

        sleep 0.5
    done

    return 1
}

echo "Disconnecting headphones..."

bluetoothctl disconnect "$LEFT_MAC" >/dev/null 2>&1 || true
bluetoothctl disconnect "$RIGHT_MAC" >/dev/null 2>&1 || true

sleep 3

echo "Connecting headphones..."

connect_missing_devices

if ! wait_for_both_devices; then
    echo "Error: both Bluetooth devices did not become available."

    sink_exists "$LEFT_DEVICE" ||
        echo "Left device is still unavailable: $LEFT_DEVICE"

    sink_exists "$RIGHT_DEVICE" ||
        echo "Right device is still unavailable: $RIGHT_DEVICE"

    exit 1
fi

sleep "$POST_CONNECT_SETTLE"

if ! both_sinks_exist; then
    echo "Error: a Bluetooth device disconnected before split routing."
    exit 1
fi

echo "Reapplying split stereo..."
"$SPLIT_SCRIPT"

sleep 1

if ! both_sinks_exist; then
    echo "Error: a Bluetooth device disconnected after split routing."
    exit 1
fi

if command -v playerctl >/dev/null 2>&1; then
    playerctl play >/dev/null 2>&1 || true
fi

echo "Done. Headphones resynced."
