# Linux Bluetooth Split Stereo

Use two independent Bluetooth headphones as a single stereo pair on Linux with PipeWire.

The left audio channel is sent to one Bluetooth device, while the right channel is sent to the other.

```text
System audio
├── Left channel  → Bluetooth headphone 1
└── Right channel → Bluetooth headphone 2
```

## Features

- Creates a virtual stereo sink named `split_lr`
- Routes each audio channel to a different Bluetooth headphone
- Automatically detects disconnection and reconnection
- Restores the virtual sink as the default audio output
- Keeps both physical headphones at a fixed volume
- Uses either headphone's touch volume control to change the virtual output volume
- Includes a manual Bluetooth reconnection script

## Requirements

- Bash
- PipeWire
- PipeWire PulseAudio compatibility
- WirePlumber
- BlueZ and `bluetoothctl`
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
install -Dm755 split-fones.sh ~/.local/bin/split-fones.sh
install -Dm755 fones-watchdog.sh ~/.local/bin/fones-watchdog.sh
install -Dm755 resync-fones.sh ~/.local/bin/resync-fones.sh
```

Create the configuration file:

```bash
install -Dm644 \
  config.example \
  ~/.config/linux-bluetooth-split-stereo/config
```

Edit it:

```bash
nano ~/.config/linux-bluetooth-split-stereo/config
```

Find the PipeWire sink names:

```bash
pactl list short sinks
```

Find the Bluetooth MAC addresses:

```bash
bluetoothctl devices
```

Replace the placeholder values in the configuration file.

## Manual test

Connect both headphones and run:

```bash
~/.local/bin/fones-watchdog.sh
```

Stop the manual test with `Ctrl+C`.

## Automatic startup with systemd

Install the user service:

```bash
install -Dm644 \
  systemd/fones-watchdog.service \
  ~/.config/systemd/user/fones-watchdog.service
```

Enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now fones-watchdog.service
```

Check its status:

```bash
systemctl --user status fones-watchdog.service
```

Follow the logs:

```bash
journalctl --user -u fones-watchdog.service -f
```

## Manual resynchronization

If the headphones develop noticeable delay, run:

```bash
~/.local/bin/resync-fones.sh
```

This disconnects and reconnects both Bluetooth devices, reapplies the split routing and resumes playback when `playerctl` is installed.

## Configuration

Important options in the configuration file:

```bash
VIRTUAL_SINK="split_lr"

PHYSICAL_VOLUME="90%"
PHYSICAL_BASE=90

VIRTUAL_VOLUME="40%"
TOUCH_STEP=5
```

`PHYSICAL_VOLUME` and `PHYSICAL_BASE` should represent the same percentage.

The physical headphones remain at that fixed volume. Touch volume commands are translated into changes to the virtual `split_lr` output.

## Legacy script

The old one-shot startup script is preserved under:

```text
legacy/auto-split-fones.sh
```

The persistent watchdog replaces it for normal use.

## License

MIT
