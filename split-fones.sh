#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${BLUETOOTH_SPLIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/linux-bluetooth-split-stereo/config}"

if [[ -r "$CONFIG_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
fi

: "${LEFT_DEVICE:?Set LEFT_DEVICE in $CONFIG_FILE}"
: "${RIGHT_DEVICE:?Set RIGHT_DEVICE in $CONFIG_FILE}"

VIRTUAL_SINK="${VIRTUAL_SINK:-split_lr}"
PHYSICAL_VOLUME="${PHYSICAL_VOLUME:-90%}"
VIRTUAL_VOLUME="${VIRTUAL_VOLUME:-40%}"

for command_name in pactl pw-link; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Error: $command_name not found."
        exit 1
    fi
done

sink_exists() {
    pactl list short sinks 2>/dev/null |
        awk -v sink="$1" '
            $2 == sink { found = 1 }
            END { exit !found }
        '
}

echo "Checking Bluetooth devices..."

if ! sink_exists "$LEFT_DEVICE"; then
    echo "Left device not found: $LEFT_DEVICE"
    exit 1
fi

if ! sink_exists "$RIGHT_DEVICE"; then
    echo "Right device not found: $RIGHT_DEVICE"
    exit 1
fi

echo "Checking virtual sink..."

if ! sink_exists "$VIRTUAL_SINK"; then
    echo "Creating virtual sink: $VIRTUAL_SINK"

    pactl load-module module-null-sink \
        sink_name="$VIRTUAL_SINK" \
        channels=2 \
        channel_map=front-left,front-right \
        sink_properties=device.description="Bluetooth L/R Split"
fi

sync_volumes() {
    echo "Syncing headphone volumes..."

    pactl set-sink-mute "$LEFT_DEVICE" 0 || true
    pactl set-sink-mute "$RIGHT_DEVICE" 0 || true
    pactl set-sink-mute "$VIRTUAL_SINK" 0 || true

    pactl set-sink-volume "$LEFT_DEVICE" "$PHYSICAL_VOLUME" || true
    pactl set-sink-volume "$RIGHT_DEVICE" "$PHYSICAL_VOLUME" || true
    pactl set-sink-volume "$VIRTUAL_SINK" "$VIRTUAL_VOLUME" || true

    pactl set-default-sink "$VIRTUAL_SINK" || true
}

echo "Setting default sink to $VIRTUAL_SINK..."
pactl set-default-sink "$VIRTUAL_SINK"

echo "Removing old links..."

pw-link -d "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FL" 2>/dev/null || true
pw-link -d "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FR" 2>/dev/null || true
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FL" 2>/dev/null || true
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FR" 2>/dev/null || true

pw-link -d "$VIRTUAL_SINK:monitor_FL" "$RIGHT_DEVICE:playback_FL" 2>/dev/null || true
pw-link -d "$VIRTUAL_SINK:monitor_FL" "$RIGHT_DEVICE:playback_FR" 2>/dev/null || true
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$LEFT_DEVICE:playback_FL" 2>/dev/null || true
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$LEFT_DEVICE:playback_FR" 2>/dev/null || true

echo "Connecting left channel..."
pw-link "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FL"
pw-link "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FR"

echo "Connecting right channel..."
pw-link "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FL"
pw-link "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FR"

sync_volumes

echo "Done. Bluetooth split stereo is active."
