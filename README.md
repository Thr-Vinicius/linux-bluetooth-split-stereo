# Linux Bluetooth Split Stereo

Use two independent Bluetooth audio devices as a single stereo pair on Linux with PipeWire.

The left audio channel is sent to one Bluetooth device and the right channel is sent to the other.

```text
System audio
├── Left channel  → Bluetooth device 1
└── Right channel → Bluetooth device 2
```

## Features

- Creates a virtual stereo output named `split_lr`
- Routes each stereo channel to a different Bluetooth device
- Detects device connection and disconnection automatically
- Performs a full resync when a new pair connects
- Avoids unnecessary reconnection after a service restart
- Uses one connected headphone directly
- Restores the normal computer output when both headphones disconnect
- Moves active audio streams to the selected output
- Keeps the physical devices at a fixed volume in split mode
- Supports manual resynchronization requests
- Runs as a persistent systemd user service

## Routing behavior

The watchdog manages four main situations:

```text
Two headphones — new connection
└── Full Bluetooth resync
    └── Activate split_lr

Two headphones — already synchronized
└── Restore split routing without reconnecting

One headphone
└── Use that headphone directly
    └── Apply NON_SPLIT_VOLUME once

No Bluetooth headphones
└── Restore the normal computer output
    └── Apply NON_SPLIT_VOLUME once
```

The one-headphone and normal-output volume is applied only when the route changes.

The watchdog does not permanently lock that volume. Manual volume changes remain possible afterward.

## Why a new connection is reconnected once

Simply detecting both PipeWire sinks does not guarantee that two independent Bluetooth devices started with matching latency.

For this reason, a new pair is deliberately disconnected and reconnected once before the stereo routing is activated.

A synchronized connection is identified by the current PipeWire sink indexes. Restarting the watchdog while the same pair remains connected therefore restores the split without another Bluetooth reconnection.

## Requirements

- Bash
- PipeWire
- PipeWire PulseAudio compatibility
- WirePlumber
- BlueZ
- `bluetoothctl`
- `pactl`
- `pw-link`
- `flock`
- `playerctl` is optional

Arch Linux example:

```bash
sudo pacman -S pipewire pipewire-pulse wireplumber bluez bluez-utils
```

## Installation

Clone the repository:

```bash
git clone https://github.com/Thr-Vinicius/linux-bluetooth-split-stereo.git
cd linux-bluetooth-split-stereo
```

Install the scripts:

```bash
install -Dm755 split-fones.sh \
  ~/.local/bin/split-fones.sh

install -Dm755 resync-fones.sh \
  ~/.local/bin/resync-fones.sh

install -Dm755 fones-watchdog.sh \
  ~/.local/bin/fones-watchdog.sh
```

Install the configuration:

```bash
install -Dm644 config.example \
  ~/.config/linux-bluetooth-split-stereo/config
```

Edit it:

```bash
nano ~/.config/linux-bluetooth-split-stereo/config
```

## Finding the device identifiers

Connect the Bluetooth devices and list the PipeWire sinks:

```bash
pactl list short sinks
```

Typical output:

```text
bluez_output.XX_XX_XX_XX_XX_XX.1
bluez_output.YY_YY_YY_YY_YY_YY.1
```

Use those names for:

```bash
LEFT_DEVICE="bluez_output.XX_XX_XX_XX_XX_XX.1"
RIGHT_DEVICE="bluez_output.YY_YY_YY_YY_YY_YY.1"
```

List Bluetooth devices:

```bash
bluetoothctl devices
```

Use their addresses for:

```bash
LEFT_MAC="XX:XX:XX:XX:XX:XX"
RIGHT_MAC="YY:YY:YY:YY:YY:YY"
```

## Volume configuration

The physical device volume used in split mode:

```bash
PHYSICAL_VOLUME="90%"
PHYSICAL_BASE=90
```

These values should represent the same percentage.

The initial virtual output volume:

```bash
VIRTUAL_VOLUME="40%"
```

The volume applied once when only one headphone or no Bluetooth headphones are connected:

```bash
NON_SPLIT_VOLUME=30
```

## Normal output detection

Leave this empty for automatic detection:

```bash
FALLBACK_SINK=""
```

The watchdog prefers a non-Bluetooth `analog-stereo` output when one is available.

A specific output may also be configured:

```bash
FALLBACK_SINK="alsa_output.pci-0000_00_00.0.analog-stereo"
```

## Automatic startup

Install the systemd user service:

```bash
install -Dm644 systemd/fones-watchdog.service \
  ~/.config/systemd/user/fones-watchdog.service
```

Reload systemd:

```bash
systemctl --user daemon-reload
```

Enable and start the service:

```bash
systemctl --user enable --now fones-watchdog.service
```

Check its status:

```bash
systemctl --user status fones-watchdog.service
```

Follow its logs:

```bash
journalctl --user -u fones-watchdog.service -f
```

Stop following the logs with `Ctrl+C`. This does not stop the service.

## Manual split routing

Apply the split routing without reconnecting the devices:

```bash
~/.local/bin/split-fones.sh
```

## Manual resynchronization

Run the resync script directly:

```bash
~/.local/bin/resync-fones.sh
```

When the watchdog is running, the preferred method is to send it a request:

```bash
touch "${XDG_RUNTIME_DIR:-/tmp}/fones-watchdog-resync-request-${UID}.flag"
```

### Hyprland shortcut

On this system, manual resynchronization is also mapped to:

```text
SUPER + SHIFT + R
```

The shortcut calls:

`~/.local/bin/michael-resolver`

The resolver checks whether both configured headphones are connected and then sends a resynchronization request to the watchdog.

The watchdog then performs one controlled resync and restores `split_lr`.

This request mechanism can be integrated with voice assistants, keyboard shortcuts or other automation tools.

## Useful commands

Current default output:

```bash
pactl get-default-sink
```

Available outputs:

```bash
pactl list short sinks
```

PipeWire links:

```bash
pw-link -l
```

Relevant split and Bluetooth links:

```bash
pw-link -l | grep -E 'split_lr|bluez_output'
```

Recent watchdog logs:

```bash
journalctl --user -u fones-watchdog.service -n 30 --no-pager
```

Restart the watchdog:

```bash
systemctl --user restart fones-watchdog.service
```

## Synchronization limitations

This project combines two independent Bluetooth audio devices.

Each device has its own hardware clock, Bluetooth buffer, codec implementation and internal processing delay. Small latency differences or synchronization drift may therefore occur.

Results may vary depending on:

- headphone firmware
- Bluetooth codec
- Bluetooth adapter
- radio interference
- BlueZ timing
- PipeWire timing
- system load

The full resynchronization procedure usually reduces the difference significantly, but sample-perfect synchronization between unrelated Bluetooth devices cannot be guaranteed.

A result that is excellent on one pair of devices may be slightly different on another pair or after a later connection.

## Legacy script

The former one-shot startup script is preserved under:

```text
legacy/auto-split-fones.sh
```

The persistent connection-aware watchdog replaces it for normal use.

## License

MIT
