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
