# Qualification follow-up, 2026-10-18

Historical preparation record. A later authorized temporary real trial failed
before test playback and was rolled back. Current findings and limits are in
[NATIVE-STARTUP.md](NATIVE-STARTUP.md); the next trial is prepared in
[SECOND-TRIAL.md](SECOND-TRIAL.md) and has not been executed.

Status at the preparation snapshot: **pending real-device qualification of the candidate**. The installed
legacy audio graph was inspected read-only. No live links, devices, services,
levels, defaults or permanent personal configuration were changed.

## Environment observed

Arch Linux rolling, kernel 6.18.54-1-lts; PipeWire 1.6.9, WirePlumber 0.5.17,
BlueZ 5.87; Realtek USB Bluetooth adapter 0bda:4853. Both configured devices
advertise Lenovo thinkplus GM2 Pro, were connected in A2DP/AAC and exposed
stereo playback ports. This stack matches the versions used in native testing.
The devices' identity comes from BlueZ's advertised names, not physical inspection.

The active default was the old `split_lr` null sink. Four existing links were
active and mapped FL to the left sink's FL/FR, FR to the right sink's FL/FR.
This validates only the snapshot of the old graph, not heard channel output or
acoustic timing. Physical levels differed (82% / 90%) and the virtual level was
30%, all unmuted; this reinforces preserving independent levels.

Pulse and BlueZ read queries succeeded. Direct systemd user-bus queries failed
from the execution environment. Journal entries show service startup and the old
watchdog performing reconnect-based resync, but do not replace a current systemd
state query. EasyEffects is present as another virtual output and must not have
its routing taken over. Local configs contained legacy timing/volume settings.
The resync shortcut calls the installed old script; an external resolver still
writes the legacy per-user request flag. Unrelated personal files were not edited.
Addresses, raw graph/application data, config and backup hashes remain in private
local artifacts, not this public repository.

## Reproduced failures and narrowly scoped fixes

1. A native client delayed by two seconds never became ready: the supervisor
   stopped it after the first one-second inspection and restarted it repeatedly.
   The isolated native test reproduced the timeout. A bounded ten-second startup
   deadline now allows readiness to appear; subsequent virtual-node loss still
   recovers the owner. This is a maximum readiness deadline, not a fixed settling
   sleep or a change to playback buffers.
2. If no normal sink existed on the initial DISCONNECTED transition, the saved
   presence state prevented fallback selection when that output appeared later.
   A unit test reproduced the missed `set-default-sink`. An unavailable fallback
   is no longer recorded as a completed controlled transition.
3. Inspection proved an installed resolver still uses the old flag protocol.
   Compatibility now accepts only a regular, current-user-owned flag under the
   actual user runtime directory. A successful verified repair acknowledges it.
   No external resolver is invoked, no `/tmp` fallback is used, and no Bluetooth
   or player command is added. Unit and native request tests cover this bridge.

No compensation, codec, clock, gain or sample-rate tuning was justified by the
read-only hardware evidence. Those settings were left unchanged.

## Test evidence

- Original regressions failed before fixes: fallback unit assertion and delayed
  native owner readiness timeout.
- Unit tests after fixes: 27 passed, including the prior 2,500 simulated states.
- Native tests run with private PipeWire/Pulse sockets, private WirePlumber policy
  and a deliberately delayed client. A 30-second dummy-sink audio capture was
  executed; it is not a two-hour test or evidence of acoustic alignment.
- ShellCheck, Bash/Python syntax and user-unit verification are rechecked in this
  follow-up. CI runs the delayed-start regression as part of native integration.
- A ten-second, two-snapshot read-only observation of the **old installed graph**
  was recorded locally. It was not classified as a candidate qualification pass.

## Status by requirement

| Requirement | Status | Evidence / remaining work |
| --- | --- | --- |
| Versions / basic stack compatibility | Approved | Installed versions match native-tested family |
| Real identities/profiles/codecs | Limited | BlueZ names and A2DP/AAC snapshot; no firmware audit |
| Initial backup and rollback preparation | Approved | Local copies + hashes and captured levels/default/graph |
| Candidate channel mapping | Limited | Captured dummy-sink samples; real listening pending |
| Recovery, concurrency, late fallback | Limited | Isolated tests passed; actual device transitions pending |
| Volume/mute/playback preservation | Limited | Isolated checks; actual candidate intervention pending |
| Native buffering and resampling configuration | Limited | Source/config and software validation; audible benefit pending |
| Compensation enabled vs disabled | Pending | Requires authorized candidate session and listening/capture |
| Acoustic offset/drift/jitter | Pending | No synchronized two-channel acoustic measurement |
| Dropouts, CPU load, profile changes, suspend/resume | Pending | No authorized real-device stress run |
| At least two hours of candidate reproduction | Pending | No such elapsed playback observation was performed |
| Definitive installation / merge readiness | Pending | Do not install/merge based only on software checks |

## Finite passive observation

After authorization and a controlled candidate session, run from the checkout:

```bash
python3 tools/observe-session.py \
  --config /absolute/path/to/candidate/config \
  --output /absolute/path/to/new-observation.jsonl \
  --seconds 7200 --interval 30
```

This command only reads the graph, codec/profile, default and levels. It does not
play media, connect Bluetooth, repair routes, restart services or change volume.
It exits after the requested real elapsed duration (or Ctrl+C), creates an
exclusive private output file and reports actual elapsed time. No background or
permanent process is installed. Keep the supervising test in a terminal and
stop it explicitly when finished. The output can contain device identifiers in
the current default name; review it before sharing.

A duration-completed result establishes only monitoring duration. It does not
prove continuous playback, lack of clicks/dropouts or acoustic alignment. Record
actual player start/end and observations separately. Periodic graph snapshots
can miss short failures. For acoustic A/B and prolonged playback acceptance,
follow VALIDATION.md with the same source material, codecs and device placement.

## Live test gate

The user's mission explicitly requires authorization before any action that can
interrupt audio, change the active service or replace the installation. Prepare
and review a temporary trial first: stop only the old watchdog, remove only its
confirmed null sink, start the candidate from a staged directory with automatic
default selection disabled, and select the test output deliberately. These actions
can interrupt current audio and have **not** been performed. Verify that service
control is available from the user's local terminal before proceeding.

Do not reconnect both devices or restart the whole audio stack as a test shortcut.
Test disconnects, supervisor restart, load and suspend/resume need their own
explicitly authorized scope. Definitive installation is a later decision after
real-device results. Use backed-up original files and recorded levels/defaults
for rollback; do not reuse stale numeric object IDs.
