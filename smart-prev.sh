#!/usr/bin/env bash
set -euo pipefail
# Explicit media shortcut only; never called by the audio recovery controller.
: "${XDG_RUNTIME_DIR:?Run inside your user session}"
RUNTIME="$XDG_RUNTIME_DIR/linux-bluetooth-split-stereo-prev"
umask 077
mkdir -p -- "$RUNTIME"
[[ ! -L "$RUNTIME" && -O "$RUNTIME" && $(stat -c %a -- "$RUNTIME") == 700 ]] || exit 1
exec 9>"$RUNTIME/lock"
flock -n 9 || exit 0
now=$(date +%s%3N)
last=0
if [[ -f "$RUNTIME/last" ]]; then
    read -r last < "$RUNTIME/last" || last=0
fi
[[ "$last" =~ ^[0-9]{1,16}$ ]] || last=0
(( now - last >= 700 )) || exit 0
printf '%s\n' "$now" > "$RUNTIME/last"
player_args=()
[[ -z "${PLAYER:-}" ]] || player_args=(--player="$PLAYER")
position=$(timeout 3 playerctl "${player_args[@]}" position 2>/dev/null) || exit 0
[[ "$position" =~ ^[0-9]+([.][0-9]+)?$ ]] || exit 0
position_int=${position%.*}
if (( 10#$position_int < 5 )); then
    timeout 3 playerctl "${player_args[@]}" previous
else
    timeout 3 playerctl "${player_args[@]}" position 0
fi
