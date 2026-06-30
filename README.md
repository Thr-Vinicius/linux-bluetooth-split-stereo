# Linux Bluetooth Split Stereo

Split stereo audio between two different Bluetooth headphones on Linux using PipeWire.

This project creates a virtual stereo sink and routes the left audio channel to one Bluetooth device and the right audio channel to another Bluetooth device.

It is useful when you want to use two separate Bluetooth headphones as a single stereo pair.

## What it does

Instead of duplicating the same stereo audio to both headphones, this setup works like this:

```text
System audio
├── Left channel  → Bluetooth headphone 1
└── Right channel → Bluetooth headphone 2
```
## Examples

Example outputs are available in the `examples/` directory:

- `sinks-example.txt`: example output from `pactl list short sinks`
- `ports-example.txt`: example output from `pw-link`

These files show how to identify Bluetooth device names and PipeWire ports without exposing real Bluetooth device IDs.

## Resyncing Bluetooth headphones

If the headphones lose synchronization, reconnecting both Bluetooth devices usually fixes the delay.

Edit `resync-fones.sh` and replace the placeholder MAC addresses:

```bash
LEFT_MAC="XX:XX:XX:XX:XX:XX"
RIGHT_MAC="YY:YY:YY:YY:YY:YY"
```
