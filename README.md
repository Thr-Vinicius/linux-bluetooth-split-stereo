# Linux Bluetooth Split Stereo

Use two independent Bluetooth devices as a stereo pair on Linux with PipeWire,
WirePlumber and BlueZ. Only FL reaches the configured left device; only FR reaches
the right. A selected channel plays through both inputs of a stereo device or the
single input of a mono device.

This version replaces Bluetooth reconnect-based “resync” with a supervised native
`libpipewire-module-combine-stream` client. It repairs missing links without
recreating healthy ones. **Graph health is not proof of acoustic synchronization.**

## Architecture and behavior

```text
Applications following the selected output
                  │
        split_lr (FL / FR)
          native combine-stream
          │                 │
    left MONO stream   right MONO stream
          │                 │
     left FL + FR       right FL + FR
       (or MONO)           (or MONO)
```

PipeWire owns stream creation/removal as devices appear/disappear, buffering,
latency reporting and adaptive resampling. The controller owns only the links
from its two output streams. Streams cannot automatically fall back to the wrong
device. No common hardware clock is fabricated. No forced quantum, sample rate,
codec, profile or Bluetooth reconnect is used.

The virtual sink remains present while the supervisor runs, including when both
headphones are absent. The supervisor uses Pulse sink/card/server events for
availability changes and a ten-second graph audit for lost links; event bursts
are coalesced. It does not measure latency periodically. In a healthy steady state
there are no routing, default or volume writes.

| Observed graph | State | Default output policy when still managed |
| --- | --- | --- |
| Both devices and all required links | ROUTED | `split_lr` |
| Only one device, its links valid | PARTIAL | That physical device, normal full program audio |
| Neither device | DISCONNECTED | Configured/saved normal output |
| Missing, wrong, duplicate or negotiating links | DEGRADED / error until repaired | Do not select an unverified split |
| Server failure, ambiguity, unsupported ports, command failure | ERROR | Bounded retry, no Bluetooth action |

ROUTED means the software graph is correct; `acoustic_sync` is always
`unmeasured`. Suspended devices and paused links are normal when no audio plays.
Explicit node/link errors are unhealthy. Availability here means an audio node
exists, not that BlueZ reports a usable A2DP transport or that sound was heard.

Automatic default selection runs on presence changes, not continuously. A manual
choice of another output is respected, including across service restarts. If
WirePlumber automatically selects another output while a device disappears, the
controller conservatively respects that choice too. Select `split_lr` manually
to use the pair again. `AUTO_DEFAULT="false"` disables default changes entirely.
Existing application streams are never forcibly moved: apps pinned to another
output stay there; apps pinned to a disconnected split may need manual rerouting.

## Requirements

- Linux user session with `XDG_RUNTIME_DIR`
- PipeWire with `libpipewire-module-combine-stream`, `pipewire`, `pw-dump`, `pw-link`
- WirePlumber, BlueZ, paired headphones and PipeWire Pulse compatibility (`pactl`)
- Python 3.9+ (standard library only), Bash
- Optional standalone media shortcut: `playerctl`, `flock`, `timeout`, GNU `date/stat`

Tested in isolation with **PipeWire 1.6.9 / WirePlumber 0.5.17 / Python 3.14.7**. Older versions have
not been qualified; the standalone native test failed with PipeWire 1.0.5 /
WirePlumber 0.4.17 in Ubuntu CI because the virtual input ports were missing.
Do not treat that older stack as supported by this revision. Check that your distribution includes the combine-stream
module; a missing module causes a visible error rather than silently falling
back to the old architecture. WirePlumber policy restart was tested against dummy sinks, with hardware
monitors disabled and a private session bus. BlueZ/hardware integration remains
to be tested.

On Arch Linux the audio packages are `pipewire`, `pipewire-pulse`, `wireplumber`,
`bluez`, `bluez-utils`, and `libpulse`; Python and Bash are also required. Keep the
normal per-user audio services enabled. Pair/connect devices using your desktop
Bluetooth UI or `bluetoothctl`. This tool does not pair, trust, change profiles,
or automatically reconnect a device you disconnected.

## Install and try the review branch

Use the branch under review; do not install over a working setup without a backup.
No installation or real-session service changes were performed during development.

```bash
git clone --branch refactor/stable-native-split \
  https://github.com/Thr-Vinicius/linux-bluetooth-split-stereo.git
cd linux-bluetooth-split-stereo

# Existing users: first follow docs/MIGRATION.md.
install -d ~/.local/bin ~/.config/linux-bluetooth-split-stereo
install -m755 bluetooth-split-controller.py split-fones.sh resync-fones.sh \
  fones-watchdog.sh ~/.local/bin/
# Do not overwrite an existing config:
if [ ! -e ~/.config/linux-bluetooth-split-stereo/config ]; then
  install -m600 config.example ~/.config/linux-bluetooth-split-stereo/config
fi
```

Edit `~/.config/linux-bluetooth-split-stereo/config`. Find addresses with
`bluetoothctl devices`; find exact node names and your normal output with
`pactl list short sinks`. Configure two different real MAC addresses, or omit MACs
and use exact `LEFT_DEVICE` / `RIGHT_DEVICE` names. MAC matching survives suffix
changes; if multiple sinks match one MAC, configuration stops with an error.
Do not leave the example MACs in place. Set `FALLBACK_SINK` to your normal output
when possible; otherwise the current normal default is saved, then a built-in
ALSA output is preferred. Unrelated virtual outputs are not arbitrarily selected.

Config files are **assignments, not shell programs**. No command substitution,
shell variable expansion or `source` is supported. `BLUETOOTH_SPLIT_CONFIG` can
point to an alternative file; standard XDG config paths are supported.

First try in the foreground at a low physical listening volume:

```bash
~/.local/bin/fones-watchdog.sh
```

Use another terminal to inspect or repair:

```bash
python3 ~/.local/bin/bluetooth-split-controller.py status
~/.local/bin/split-fones.sh
~/.local/bin/resync-fones.sh
```

Both repair scripts now perform the same non-disconnecting, idempotent route
check. They need the foreground supervisor or installed service to own the native
sink; they do not start a hidden background process. `resync-fones.sh` cannot
measure or promise acoustic resynchronization. Ctrl+C stops the foreground
supervisor and its native client. Starting/stopping/restarting the owner removes
and recreates its virtual sink, so this explicit operation may interrupt audio;
ordinary link repair and device hotplug preserve the owner and healthy links.

After stopping the foreground instance, install the user service:

```bash
install -Dm644 systemd/fones-watchdog.service \
  ~/.config/systemd/user/fones-watchdog.service
systemctl --user daemon-reload
systemctl --user enable --now fones-watchdog.service
journalctl --user -u fones-watchdog.service -f
```

Do not run the legacy watcher, old watchdog or duplicate native configs alongside
this service. Lifetime and operation locks prevent concurrent new controllers.
All runtime files live inside a private directory under `XDG_RUNTIME_DIR`; there
are no shared predictable `/tmp` control files.

## Volume and playback

Physical volume and mute settings are never written. Each headphone retains
independent control. The native virtual sink starts with linear gain 0.064
(approximately 40% on the Pulse cubic scale); WirePlumber's normal saved-property
policy may restore your previous setting. Check the level before listening.
The controller does not continuously restore or enforce it, and does not change
volumes when recovering links or selecting outputs. Persistence across full audio
server restarts depends on the session manager's restore policy.

No recovery path calls `playerctl`, pauses media, seeks or resumes playback. The
optional `smart-prev.sh` is a separate, explicit user shortcut. Its optional
`PLAYER` environment variable selects one player; it is not invoked by recovery.

## Timing limits and compensation

`LATENCY_COMPENSATE="true"` enables native delay buffers to align **reported**
stream delays. It can help with exposed differences between streams; firmware
buffers, transport reporting errors and acoustic processing remain outside this
measurement. Enabling it is not evidence of an audible improvement on your pair.
If delay reports change during playback, native buffers may be resized; compare
`false` on your hardware if you hear artifacts. Change this setting with playback
stopped and restart the service once to apply it.

Fixed acoustic offset and drift are separate problems. A fixed offset needs an
external two-channel acoustic measurement; drift concerns different clock rates.
PipeWire handles clock adaptation with its resamplers. This tool adds no custom
rate correction loop or continuous latency probe and does not pretend unrelated
headphones share a clock. No manual fixed acoustic correction is implemented in
this revision. See [the architecture decision](docs/ARCHITECTURE.md) and
[hardware test procedure](docs/VALIDATION.md) for limits and comparison criteria.

## Diagnostics and tests

```bash
python3 ~/.local/bin/bluetooth-split-controller.py status
pw-link -l
pactl list short sinks
journalctl --user -u fones-watchdog.service -n 50 --no-pager

# From the checkout, no real devices or services are changed:
python3 -m unittest discover -s tests -v
python3 tests/native-smoke.py
shellcheck *.sh legacy/*.sh
```

The native smoke test uses its own temporary PipeWire socket, dummy sinks and
raw sample capture and a private Pulse server. It requires the normal PipeWire client config in
`/usr/share/pipewire/client.conf` and the native tools. It never uses your session's
Bluetooth or WirePlumber instance. Optional policy-only restart test:
`SPLIT_TEST_WIREPLUMBER=1 python3 tests/native-smoke.py` (requires WirePlumber 0.5
and dbus-daemon). Use `SPLIT_AUDIO_SECONDS=10` for a longer software sample.
Software tests do not validate acoustic sync,
radio reliability, codec buffering or hours-long listening stability.

For an ERROR, check the configured identifiers, active graphical session, module
availability and mono/stereo ports before restarting anything. WirePlumber's
Bluetooth monitor follows active-session/logind rules; changing seats can make
audio nodes disappear. A BlueZ connection alone does not prove an audio sink is
ready. This tool retries graph failures without resetting Bluetooth or WirePlumber.
Unsupported multi-channel layouts and ambiguous names fail visibly. Logs report
state changes/errors, not every healthy tick, and use the system journal.

The [audit](docs/AUDIT.md) distinguishes observed defects from hardware-dependent
risks. The [migration guide](docs/MIGRATION.md) includes backup and rollback.
The former bounded startup waiter remains in `legacy/auto-split-fones.sh`; it now
waits for verified routes from the supervisor. LICENSE remains MIT.
