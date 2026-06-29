#!/usr/bin/env bash

# Linux Bluetooth Split Stereo
# Sends the left audio channel to one Bluetooth device
# and the right audio channel to another Bluetooth device.

LEFT_DEVICE="bluez_output.YOUR_LEFT_DEVICE.1"
RIGHT_DEVICE="bluez_output.YOUR_RIGHT_DEVICE.1"
VIRTUAL_SINK="split_lr"

echo "Setting default sink to $VIRTUAL_SINK..."
pactl set-default-sink "$VIRTUAL_SINK"

echo "Removing old links..."

pw-link -d "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FL" 2>/dev/null
pw-link -d "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FR" 2>/dev/null
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FL" 2>/dev/null
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FR" 2>/dev/null

pw-link -d "$VIRTUAL_SINK:monitor_FL" "$RIGHT_DEVICE:playback_FL" 2>/dev/null
pw-link -d "$VIRTUAL_SINK:monitor_FL" "$RIGHT_DEVICE:playback_FR" 2>/dev/null
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$LEFT_DEVICE:playback_FL" 2>/dev/null
pw-link -d "$VIRTUAL_SINK:monitor_FR" "$LEFT_DEVICE:playback_FR" 2>/dev/null

echo "Connecting left channel to left Bluetooth device..."
pw-link "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FL"
pw-link "$VIRTUAL_SINK:monitor_FL" "$LEFT_DEVICE:playback_FR"

echo "Connecting right channel to right Bluetooth device..."
pw-link "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FL"
pw-link "$VIRTUAL_SINK:monitor_FR" "$RIGHT_DEVICE:playback_FR"

echo "Done."
