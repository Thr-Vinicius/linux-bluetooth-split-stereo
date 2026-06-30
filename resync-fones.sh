#!/usr/bin/env bash

# Linux Bluetooth Split Stereo - Resync Script
# Disconnects and reconnects two Bluetooth headphones,
# then reapplies the split stereo routing.
#
# Useful when the two Bluetooth devices lose synchronization.

LEFT_MAC="XX:XX:XX:XX:XX:XX"
RIGHT_MAC="YY:YY:YY:YY:YY:YY"
SPLIT_SCRIPT="./split-fones.sh"

echo "Checking dependencies..."

if ! command -v bluetoothctl >/dev/null 2>&1; then
    echo "Error: bluetoothctl not found."
    exit 1
fi

if [ ! -x "$SPLIT_SCRIPT" ]; then
    echo "Error: split script not found or not executable: $SPLIT_SCRIPT"
    echo "Make sure split-fones.sh exists and run:"
    echo "chmod +x split-fones.sh"
    exit 1
fi

echo "Disconnecting Bluetooth headphones..."

bluetoothctl disconnect "$LEFT_MAC" >/dev/null 2>&1
bluetoothctl disconnect "$RIGHT_MAC" >/dev/null 2>&1

sleep 3

echo "Reconnecting Bluetooth headphones..."

bluetoothctl connect "$LEFT_MAC"
bluetoothctl connect "$RIGHT_MAC"

sleep 2

echo "Reapplying split stereo routing..."

"$SPLIT_SCRIPT"

echo "Done. Bluetooth headphones resynced."
