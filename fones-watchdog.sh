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

CHECK_INTERVAL="${CHECK_INTERVAL:-1}"
IDLE_CHECK_INTERVAL="${IDLE_CHECK_INTERVAL:-3}"
ACTION_RETRY_DELAY="${ACTION_RETRY_DELAY:-12}"
READY_TIMEOUT="${READY_TIMEOUT:-20}"

PHYSICAL_BASE="${PHYSICAL_BASE:-90}"

SPLIT_SCRIPT="${SPLIT_SCRIPT:-$SCRIPT_DIR/split-fones.sh}"
RESYNC_SCRIPT="${RESYNC_SCRIPT:-$SCRIPT_DIR/resync-fones.sh}"

# Optional wrapper. Leave empty for standalone operation.
RESOLVER="${RESOLVER:-}"

# Optional normal output. When empty, the watchdog detects one automatically.
FALLBACK_SINK="${FALLBACK_SINK:-}"

# Volume used with one headphone or the normal computer output.
NON_SPLIT_VOLUME="${NON_SPLIT_VOLUME:-30}"

RESYNC_LOG="${RESYNC_LOG:-${XDG_STATE_HOME:-$HOME/.local/state}/linux-bluetooth-split-stereo/fones.log}"

for command_name in pactl flock; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Error: $command_name not found."
        exit 1
    fi
done

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"

LOCK_FILE="$RUNTIME_DIR/fones-watchdog-${UID}.lock"

# Created by michael-resolver or another manual controller.
REQUEST_FLAG="$RUNTIME_DIR/fones-watchdog-resync-request-${UID}.flag"

# Remembers the normal non-Bluetooth output while the service is running.
FALLBACK_STATE_FILE="$RUNTIME_DIR/fones-watchdog-fallback-${UID}.state"

# Stores the PipeWire sink indexes of the synchronized connection.
# It survives a service restart, but is removed when a device disconnects.
SYNC_STATE_FILE="$RUNTIME_DIR/fones-watchdog-sync-${UID}.state"

exec 9>"$LOCK_FILE"

if ! flock -n 9; then
    echo "The headphones watchdog is already running."
    exit 0
fi

log() {
    printf '[%(%H:%M:%S)T] %s\n' -1 "$*"
}

get_sink_state() {
    local sinks

    sinks="$(pactl list short sinks 2>/dev/null || true)"

    LEFT_INDEX="$(
        awk -v target="$LEFT_DEVICE" '
            $2 == target {
                print $1
                exit
            }
        ' <<< "$sinks"
    )"

    RIGHT_INDEX="$(
        awk -v target="$RIGHT_DEVICE" '
            $2 == target {
                print $1
                exit
            }
        ' <<< "$sinks"
    )"

    VIRTUAL_INDEX="$(
        awk -v target="$VIRTUAL_SINK" '
            $2 == target {
                print $1
                exit
            }
        ' <<< "$sinks"
    )"

    LEFT_AVAILABLE=0
    RIGHT_AVAILABLE=0
    VIRTUAL_AVAILABLE=0

    [[ -n "$LEFT_INDEX" ]] && LEFT_AVAILABLE=1
    [[ -n "$RIGHT_INDEX" ]] && RIGHT_AVAILABLE=1
    [[ -n "$VIRTUAL_INDEX" ]] && VIRTUAL_AVAILABLE=1
}

get_current_signature() {
    get_sink_state

    if (( LEFT_AVAILABLE == 1 &&
          RIGHT_AVAILABLE == 1 )); then
        printf '%s:%s\n' "$LEFT_INDEX" "$RIGHT_INDEX"
        return 0
    fi

    return 1
}

get_saved_signature() {
    if [[ -r "$SYNC_STATE_FILE" ]]; then
        cat "$SYNC_STATE_FILE"
    fi
}

save_current_signature() {
    local signature

    signature="$(get_current_signature 2>/dev/null || true)"

    if [[ -z "$signature" ]]; then
        return 1
    fi

    printf '%s\n' "$signature" > "$SYNC_STATE_FILE"
}

clear_sync_state() {
    rm -f "$SYNC_STATE_FILE"
}

reset_physical_volumes() {
    pactl set-sink-volume \
        "$LEFT_DEVICE" "${PHYSICAL_BASE}%" \
        >/dev/null 2>&1 || true

    pactl set-sink-volume \
        "$RIGHT_DEVICE" "${PHYSICAL_BASE}%" \
        >/dev/null 2>&1 || true
}


sink_exists() {
    local target="$1"

    pactl list short sinks 2>/dev/null |
        awk -v target="$target" '
            $2 == target {
                found = 1
            }

            END {
                exit(found ? 0 : 1)
            }
        '
}

fallback_is_usable() {
    local sink="$1"

    [[ -n "$sink" ]] || return 1
    [[ "$sink" != "$VIRTUAL_SINK" ]] || return 1
    [[ "$sink" != bluez_output.* ]] || return 1

    sink_exists "$sink"
}

save_fallback_sink() {
    local sink="$1"

    fallback_is_usable "$sink" || return 1

    printf '%s\n' "$sink" > "$FALLBACK_STATE_FILE"
}

get_fallback_sink() {
    local candidate=""
    local default_sink=""
    local sinks=""

    if [[ -n "$FALLBACK_SINK" ]] &&
       fallback_is_usable "$FALLBACK_SINK"; then

        printf '%s\n' "$FALLBACK_SINK"
        return 0
    fi

    if [[ -r "$FALLBACK_STATE_FILE" ]]; then
        read -r candidate < "$FALLBACK_STATE_FILE"

        if fallback_is_usable "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    default_sink="$(
        pactl get-default-sink 2>/dev/null || true
    )"

    if fallback_is_usable "$default_sink"; then
        save_fallback_sink "$default_sink"
        printf '%s\n' "$default_sink"
        return 0
    fi

    sinks="$(pactl list short sinks 2>/dev/null || true)"

    # Prefer the usual built-in analog speaker/headphone output.
    candidate="$(
        awk -v virtual="$VIRTUAL_SINK" '
            $2 != virtual &&
            $2 !~ /^bluez_output\./ &&
            $2 ~ /analog-stereo/ {
                print $2
                exit
            }
        ' <<< "$sinks"
    )"

    if [[ -z "$candidate" ]]; then
        candidate="$(
            awk -v virtual="$VIRTUAL_SINK" '
                $2 != virtual &&
                $2 !~ /^bluez_output\./ {
                    print $2
                    exit
                }
            ' <<< "$sinks"
        )"
    fi

    if fallback_is_usable "$candidate"; then
        save_fallback_sink "$candidate"
        printf '%s\n' "$candidate"
        return 0
    fi

    return 1
}

route_to_sink() {
    local target="$1"
    local message="$2"
    local current_sink=""

    [[ -n "$target" ]] || return 1
    sink_exists "$target" || return 1

    current_sink="$(
        pactl get-default-sink 2>/dev/null || true
    )"

    if [[ "$current_sink" != "$target" ||
          "${last_routed_sink:-}" != "$target" ]]; then

        log "$message"

        pactl set-default-sink \
            "$target" \
            >/dev/null 2>&1 || return 1

        move_active_streams_to "$target"

        pactl set-sink-volume \
            "$target" "${NON_SPLIT_VOLUME}%" \
            >/dev/null 2>&1 || true

        last_routed_sink="$target"
    fi
}

move_active_streams_to() {
    local target="$1"
    local input_id

    while read -r input_id _; do
        [[ -n "$input_id" ]] || continue

        pactl move-sink-input \
            "$input_id" \
            "$target" \
            >/dev/null 2>&1 || true
    done < <(pactl list short sink-inputs 2>/dev/null)
}

apply_split_only() {
    mkdir -p "$(dirname "$RESYNC_LOG")"

    if [[ ! -x "$SPLIT_SCRIPT" ]]; then
        log "Split script not found: $SPLIT_SCRIPT"
        return 1
    fi

    "$SPLIT_SCRIPT" >> "$RESYNC_LOG" 2>&1 || return 1

    pactl set-default-sink \
        "$VIRTUAL_SINK" \
        >/dev/null 2>&1 || true

    move_active_streams_to "$VIRTUAL_SINK"
    reset_physical_volumes
}

run_full_resync() {
    mkdir -p "$(dirname "$RESYNC_LOG")"

    if [[ -n "$RESOLVER" &&
          -x "$RESOLVER" ]]; then
        "$RESOLVER"
        return $?
    fi

    # Redirected non-interactive execution produced the most reliable
    # timing between BlueZ, PipeWire and the Bluetooth devices.
    if [[ -x "$RESYNC_SCRIPT" ]]; then
        "$RESYNC_SCRIPT" >> "$RESYNC_LOG" 2>&1
        return $?
    fi

    log "Resync script not found: $RESYNC_SCRIPT"
    return 1
}

confirm_ready() {
    local maximum_attempts
    local attempt

    maximum_attempts=$((READY_TIMEOUT * 2))

    for ((attempt = 1; attempt <= maximum_attempts; attempt++)); do
        get_sink_state

        if (( LEFT_AVAILABLE == 1 &&
              RIGHT_AVAILABLE == 1 &&
              VIRTUAL_AVAILABLE == 1 )); then
            return 0
        fi

        sleep 0.5
    done

    return 1
}

finish_configuration() {
    pactl set-default-sink \
        "$VIRTUAL_SINK" \
        >/dev/null 2>&1 || true

    move_active_streams_to "$VIRTUAL_SINK"
    reset_physical_volumes

    save_current_signature || return 1

    last_routed_sink="$VIRTUAL_SINK"

}

trap 'exit 0' INT TERM


ready=0
last_action_attempt=0
last_presence="unknown"
last_routed_sink=""

log "Connection-aware watchdog started."
log "New connection: full Bluetooth resync."
log "Known connection: split routing only."
log "Waiting for Bluetooth headphones..."

while true; do
    now="$(date +%s)"
    get_sink_state

    both_available=0
    any_available=0

    if (( LEFT_AVAILABLE == 1 &&
          RIGHT_AVAILABLE == 1 )); then
        both_available=1
    fi

    if (( LEFT_AVAILABLE == 1 ||
          RIGHT_AVAILABLE == 1 )); then
        any_available=1
    fi

    if (( both_available == 0 )); then

        if [[ "$last_presence" == "both" ]]; then
            if (( any_available == 1 )); then
                log "One headphone was disconnected."
            else
                log "Both headphones were disconnected."
            fi

            log "The next complete connection will receive a full resync."
        fi

        ready=0
        clear_sync_state

        if (( LEFT_AVAILABLE == 1 &&
              RIGHT_AVAILABLE == 0 )); then

            route_to_sink \
                "$LEFT_DEVICE" \
                "Only the left headphone is connected. Using it directly." \
                || true

            last_presence="partial"

        elif (( RIGHT_AVAILABLE == 1 &&
                LEFT_AVAILABLE == 0 )); then

            route_to_sink \
                "$RIGHT_DEVICE" \
                "Only the right headphone is connected. Using it directly." \
                || true

            last_presence="partial"

        else
            fallback_sink="$(
                get_fallback_sink 2>/dev/null || true
            )"

            if [[ -n "$fallback_sink" ]]; then
                route_to_sink \
                    "$fallback_sink" \
                    "No Bluetooth headphones connected. Restoring normal output." \
                    || true
            elif [[ "$last_routed_sink" != "__no_fallback__" ]]; then
                log "No normal audio output was found."
                last_routed_sink="__no_fallback__"
            fi

            last_presence="none"
        fi

        if (( any_available == 0 )); then
            sleep "$IDLE_CHECK_INTERVAL"
        else
            sleep "$CHECK_INTERVAL"
        fi
        continue
    fi

    if [[ -e "$REQUEST_FLAG" ]]; then
        log "Manual resync request received."
        log "Performing one full resync..."

        rm -f "$REQUEST_FLAG"


        last_action_attempt="$now"
        action_ok=0

        if run_full_resync; then
            action_ok=1
        fi

        if (( action_ok == 1 )) &&
           confirm_ready &&
           finish_configuration; then

            ready=1
            last_presence="both"

            log "Manual resync completed."
            log "Headphones synchronized and virtual output active."
        else
            ready=0
            clear_sync_state

            log "Manual resync did not complete successfully."
        fi


        sleep "$CHECK_INTERVAL"
        continue
    fi

    current_signature="${LEFT_INDEX}:${RIGHT_INDEX}"
    saved_signature="$(get_saved_signature 2>/dev/null || true)"

    if [[ "$last_presence" != "both" ]]; then
        log "Both headphones detected."
    fi

    last_presence="both"

    if (( ready == 1 )); then
        if [[ -z "$saved_signature" ||
              "$saved_signature" != "$current_signature" ]]; then

            log "A new PipeWire device pair was detected."
            log "Scheduling a full resync..."

            clear_sync_state
            ready=0

            sleep "$CHECK_INTERVAL"
            continue
        fi

        if (( VIRTUAL_AVAILABLE == 0 )); then
            if (( now - last_action_attempt >= ACTION_RETRY_DELAY )); then
                last_action_attempt="$now"

                log "Virtual output disappeared. Restoring split routing..."


                if apply_split_only &&
                   confirm_ready &&
                   finish_configuration; then

                    log "Virtual output restored."
                else
                    log "Split restoration failed."
                    clear_sync_state
                    ready=0
                fi

            fi
        else
            default_sink="$(
                pactl get-default-sink 2>/dev/null || true
            )"

            if [[ "$default_sink" != "$VIRTUAL_SINK" ]]; then
                log "Restoring $VIRTUAL_SINK as the default output..."

                pactl set-default-sink \
                    "$VIRTUAL_SINK" \
                    >/dev/null 2>&1 || true

                move_active_streams_to "$VIRTUAL_SINK"
            fi
        fi

        sleep "$CHECK_INTERVAL"
        continue
    fi

    if (( now - last_action_attempt < ACTION_RETRY_DELAY )); then
        sleep "$CHECK_INTERVAL"
        continue
    fi

    last_action_attempt="$now"


    action_ok=0

    if [[ -n "$saved_signature" &&
          "$saved_signature" == "$current_signature" ]]; then

        log "Known synchronized connection detected."
        log "Applying split routing without reconnecting..."

        apply_split_only && action_ok=1
    else
        log "New Bluetooth connection detected."
        log "Performing one full resync..."

        run_full_resync && action_ok=1
    fi

    if (( action_ok == 1 )) &&
       confirm_ready &&
       finish_configuration; then

        ready=1
        log "Headphones synchronized and virtual output active."
    else
        ready=0
        clear_sync_state

        log "Configuration did not complete successfully."
        log "A new attempt will be made later."
    fi


    sleep "$CHECK_INTERVAL"
done
