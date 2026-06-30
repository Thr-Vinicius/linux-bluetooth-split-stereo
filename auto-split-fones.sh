#!/usr/bin/env bash

# Linux Bluetooth Split Stereo - Auto Start Script
# Waits for two Bluetooth headphones to appear,
# then applies the split stereo routing.

LEFT_DEVICE="bluez_output.YOUR_LEFT_DEVICE.1"
RIGHT_DEVICE="bluez_output.YOUR_RIGHT_DEVICE.1"
SPLIT_SCRIPT="./split-fones.sh"

MAX_TRIES=60
SLEEP_TIME=2

echo "Waiting for Bluetooth headphones..."

if [ ! -x "$SPLIT_SCRIPT" ]; then
    echo "Error: split script not found or not executable: $SPLIT_SCRIPT"
    echo "Run: chmod +x split-fones.sh"
    exit 1
fi

for i in $(seq 1 "$MAX_TRIES"); do
    if pactl list short sinks | grep -q "$LEFT_DEVICE" && pactl list short sinks | grep -q "$RIGHT_DEVICE"; then
        echo "Both headphones found. Applying split stereo..."
        "$SPLIT_SCRIPT"
        exit 0
    fi

    sleep "$SLEEP_TIME"
done

echo "Headphones were not found. Split stereo was not applied."
exit 1
