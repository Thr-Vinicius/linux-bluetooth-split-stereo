#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

CONFIG_FILE="${BLUETOOTH_SPLIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/linux-bluetooth-split-stereo/config}"

if [[ -r "$CONFIG_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$CONFIG_FILE"
fi

: "${LEFT_DEVICE:?Set LEFT_DEVICE in $CONFIG_FILE}"
: "${RIGHT_DEVICE:?Set RIGHT_DEVICE in $CONFIG_FILE}"

VIRTUAL_SINK="${VIRTUAL_SINK:-split_lr}"

CHECK_INTERVAL="${CHECK_INTERVAL:-5}"
VOLUME_INTERVAL="${VOLUME_INTERVAL:-0.20}"
STABILIZE_TIME="${STABILIZE_TIME:-2}"

PHYSICAL_BASE="${PHYSICAL_BASE:-90}"
TOUCH_STEP="${TOUCH_STEP:-5}"

SPLIT_SCRIPT="${SPLIT_SCRIPT:-$SCRIPT_DIR/split-fones.sh}"

if [[ ! -x "$SPLIT_SCRIPT" ]]; then
    echo "Split script not found or not executable: $SPLIT_SCRIPT"
    exit 1
fi

LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/fones-watchdog-${UID}.lock"

exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    echo "The headphones watchdog is already running."
    exit 0
fi

log() {
    printf '[%(%H:%M:%S)T] %s\n' -1 "$*"
}

sink_exists() {
    pactl list short sinks 2>/dev/null |
        awk -v sink="$1" '
            $2 == sink { found = 1 }
            END { exit !found }
        '
}

both_headphones_available() {
    sink_exists "$LEFT_DEVICE" &&
        sink_exists "$RIGHT_DEVICE"
}

virtual_sink_available() {
    sink_exists "$VIRTUAL_SINK"
}

get_volume_percent() {
    pactl get-sink-volume "$1" 2>/dev/null |
        grep -oE '[0-9]+%' |
        head -n1 |
        tr -d '%'
}

reset_physical_volumes() {
    pactl set-sink-volume \
        "$LEFT_DEVICE" "${PHYSICAL_BASE}%" \
        >/dev/null 2>&1 || true

    pactl set-sink-volume \
        "$RIGHT_DEVICE" "${PHYSICAL_BASE}%" \
        >/dev/null 2>&1 || true
}

touch_volume_controller() {
    local armed=0
    local left_volume=""
    local right_volume=""
    local virtual_volume=""
    local new_volume=""
    local direction=0
    local source=""

    while true; do
        if both_headphones_available && virtual_sink_available; then
            if (( armed == 0 )); then
                reset_physical_volumes
                armed=1
                sleep 0.5
                continue
            fi

            left_volume="$(get_volume_percent "$LEFT_DEVICE")"
            right_volume="$(get_volume_percent "$RIGHT_DEVICE")"

            direction=0
            source=""

            if [[ -n "$left_volume" &&
                  "$left_volume" -ne "$PHYSICAL_BASE" ]]; then

                source="left"

                if (( left_volume < PHYSICAL_BASE )); then
                    direction=-1
                else
                    direction=1
                fi

            elif [[ -n "$right_volume" &&
                    "$right_volume" -ne "$PHYSICAL_BASE" ]]; then

                source="right"

                if (( right_volume < PHYSICAL_BASE )); then
                    direction=-1
                else
                    direction=1
                fi
            fi

            if (( direction != 0 )); then
                virtual_volume="$(get_volume_percent "$VIRTUAL_SINK")"

                if [[ -n "$virtual_volume" ]]; then
                    new_volume=$((virtual_volume + direction * TOUCH_STEP))

                    (( new_volume < 0 )) && new_volume=0
                    (( new_volume > 100 )) && new_volume=100

                    pactl set-sink-volume \
                        "$VIRTUAL_SINK" "${new_volume}%" \
                        >/dev/null 2>&1 || true

                    reset_physical_volumes

                    if (( direction > 0 )); then
                        log "Touch on $source headphone: virtual volume increased to ${new_volume}%."
                    else
                        log "Touch on $source headphone: virtual volume reduced to ${new_volume}%."
                    fi

                    sleep 0.25
                fi
            fi
        else
            armed=0
        fi

        sleep "$VOLUME_INTERVAL"
    done
}

touch_pid=""

cleanup() {
    if [[ -n "${touch_pid:-}" ]]; then
        kill "$touch_pid" 2>/dev/null || true
        wait "$touch_pid" 2>/dev/null || true
    fi
}

trap 'exit 0' INT TERM
trap cleanup EXIT

touch_volume_controller &
touch_pid=$!

previously_connected=0

log "Watchdog started."
log "Waiting for both Bluetooth headphones..."

while true; do
    if both_headphones_available; then
        default_sink="$(pactl get-default-sink 2>/dev/null || true)"

        if (( previously_connected == 0 )); then
            log "Both headphones detected."
            log "Waiting for Bluetooth to stabilize..."

            sleep "$STABILIZE_TIME"

            if both_headphones_available; then
                log "Applying split stereo..."

                if "$SPLIT_SCRIPT"; then
                    reset_physical_volumes
                    log "Split stereo applied."
                    previously_connected=1
                else
                    log "Failed to apply split stereo. Retrying later."
                    previously_connected=0
                fi
            fi

        elif ! virtual_sink_available; then
            log "Virtual sink disappeared. Recreating it..."

            if "$SPLIT_SCRIPT"; then
                reset_physical_volumes
                log "Virtual sink restored."
            else
                log "Failed to restore virtual sink."
                previously_connected=0
            fi

        elif [[ "$default_sink" != "$VIRTUAL_SINK" ]]; then
            log "Default sink changed. Restoring $VIRTUAL_SINK..."
            pactl set-default-sink "$VIRTUAL_SINK" 2>/dev/null || true
        fi

    else
        if (( previously_connected == 1 )); then
            log "One or both headphones were disconnected."
            log "Waiting for reconnection..."
        fi

        previously_connected=0
    fi

    sleep "$CHECK_INTERVAL"
done
