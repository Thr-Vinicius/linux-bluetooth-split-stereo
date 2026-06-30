#!/usr/bin/env bash

# Smart previous media control
# If the current track position is below 5 seconds, go to the previous track.
# Otherwise, restart the current track from the beginning.

LOCK="/tmp/smart-prev.lock"
STATE="/tmp/smart-prev.last"

exec 9>"$LOCK"
flock -n 9 || exit 0

now=$(date +%s%3N)
last=0

if [ -f "$STATE" ]; then
    last=$(cat "$STATE")
fi

# Prevent duplicate triggers from the same gesture.
if [ $((now - last)) -lt 700 ]; then
    exit 0
fi

echo "$now" > "$STATE"

position=$(playerctl position 2>/dev/null)

if [ -z "$position" ]; then
    exit 0
fi

position_int=${position%.*}

if [ "$position_int" -lt 5 ]; then
    playerctl previous 2>/dev/null
else
    playerctl position 0 2>/dev/null
fi
