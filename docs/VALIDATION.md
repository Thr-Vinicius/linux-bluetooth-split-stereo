# Validation record and hardware acceptance procedure

## Executed in isolation

Environment: PipeWire 1.6.9, WirePlumber 0.5.17, Python 3.14.7 and ShellCheck
0.11.0. The real session's audio services/configuration and Bluetooth connections
were not changed. No real Bluetooth devices were used.

- 23 Python unit tests passed, including 500 repetitions of five presence
  transitions (2,500 simulated states), missing/crossed/duplicate links, command
  nonzero/timeout, graph races, invalid layouts, ambiguity, node errors, locks,
  config parsing, default policy and restart state.
- Real native module test passed against private PipeWire/Pulse sockets and dummy
  stereo-left/mono-right sinks. Repeated reconciliation preserved link IDs;
  deleting one link and adding a crosswire caused only selective correction.
- Raw known stereo samples were captured from both dummy sinks and checked for
  selected channel sign and expected gain. This verifies software channel
  mapping, not acoustic timing. The extended run used ten seconds of playback;
  it is not an hours-long soak or a radio test.
- Independent manual physical/virtual levels and mute set through the private
  Pulse server survived a lost-link repair unchanged.
- Actual supervisor tests passed: duplicate process exclusion, physical node
  disappearance/reappearance with a new ID, supervisor restart, server restart,
  deleted virtual node and missing native child stream. Test assertions observe
  the graph without repairing it on behalf of the supervisor.
- WirePlumber **policy-only** start/restart passed with its physical monitors
  disabled, private state/config directories and an isolated D-Bus session.
  Routes remained correct; this does not exercise BlueZ/ALSA device monitors,
  logind seat transitions or real profile negotiations.
- ShellCheck passed on all shell entry points including legacy/media scripts.
  Bash syntax, Python compilation, `git diff --check`, and systemd unit verification
  passed. Unit verification checks configuration, not a real service deployment.
- The first Ubuntu native CI run failed with PipeWire 1.0.5 / WirePlumber 0.4.17:
  the standalone virtual sink did not expose the expected FL/FR ports. This is
  recorded as a compatibility limit, not discarded as a successful test. CI now
  keeps unit/static tests on Ubuntu and targets current Arch packages for native
  tests, matching the modern PipeWire / WirePlumber 0.5 environment. Older-stack
  production compatibility has not been established.

Native tests may log expected connection errors when deliberately destroying the
server/streams. Missing system-bus/RT scheduling messages are expected in the
isolated policy test; no claims about real-time scheduling qualification follow
from it.

## Required scenario coverage

| Requested case | Software evidence | Hardware qualification still needed |
| --- | --- | --- |
| Two headphones | Unit + native stereo/mono sinks and captured samples | Actual pair, codec and profile |
| Only left | Presence unit matrix | Listen for ordinary full-program partial behavior |
| Only right | Unit matrix + real dummy hotplug | Same on right physical device |
| Neither | Presence/default unit tests | Confirm desktop fallback and desired level |
| Disconnect while playing | Simulated graph transitions | Bluetooth interruption, remaining-side behavior |
| Reconnect one | Actual dummy sink recreated with a new ID | A2DP transport, buffered delay after reconnect |
| Restart watchdog | Actual isolated supervisor restart + persisted-policy tests | Audible interruption duration, volume restore |
| Restart PipeWire | Actual private server restart | Desktop clients and hardware reconnect policy |
| Restart WirePlumber | Actual policy-only restart + changed-ID tests | BlueZ monitors/profile negotiation |
| Lose audio link | Native deletion, observed selective repair | No unnecessary interruption on healthy side |
| Manual volume | Real private Pulse levels/mute preserved + no-write policy tests | Device hardware-volume/AVRCP quirks |
| Change default | Mocked default policy and restart persistence | Desktop controls and pinned applications |
| pactl/pw-link failure | Nonzero/deadline tests, real missing servers | Unusual distro error conditions |
| Simultaneous scripts | Shared-lock unit test + real duplicate supervisor | Desktop shortcut/service contention |
| Repeated connect/disconnect | 2,500 simulated states + native node hotplug | Repeated real Bluetooth transport cycles |
| Prolonged reproduction | Ten-second native sample test only | Hours-long listening and measurement, pending |

No software test validates acoustic synchronization, noise-free radio behavior or
long-term clock alignment. The test suite does not validate `smart-prev` against
an actual media player; that standalone shortcut is never used by recovery.

## On the user's Linux: staged acceptance

1. Follow MIGRATION.md with a backup and playback stopped. Start in foreground;
   manually set conservative physical levels. Verify `status` reports ROUTED
   only when both sides have valid links. Inspect `pw-link -l` for unexpected
   outputs from `split_lr.left/right`. Confirm no old owner remains.
2. Play separate FL-only, FR-only and alternating impulses. FL must reach only
   the chosen left device and FR only the right, through both channels of a
   stereo endpoint or the sole mono endpoint. Use test material with clear
   known channel assignments, not ordinary music to infer routing.
3. Change each physical volume independently and mute one side. Run both repair
   shortcuts repeatedly. Check unchanged levels/mute, no extra links and no
   transport reconnection. Pause a player, repair, and confirm it stays paused.
4. Change the default to the normal output and route one application explicitly
   elsewhere. Repair and hotplug must not drag those streams back. With automatic
   control still selected, test each partial/no-device default transition. Apps
   explicitly pinned to the old split may require manual rerouting by design.
5. Delete one owned link manually after inspecting its current endpoints and ID.
   Wait up to CHECK_INTERVAL for repair; verify the other healthy links retain
   their IDs. Do not delete unrelated application links. Reconnect one actual
   headphone, test restart of the user service, then separately restart PipeWire
   and WirePlumber with playback voluntarily stopped. Record recovery time,
   errors and any profile/codec change. These explicit service restarts may
   interrupt sound and are not ordinary resynchronization actions.
6. Compare compensation enabled/disabled under the same codec, sample material,
   placement, levels and load. Change the setting only between runs with playback
   stopped. Use a synchronized **two-channel recording interface** with one
   microphone/coupler at each earphone, capturing simultaneous repeated impulses.
   Separate recording-device clocks cannot establish sub-millisecond alignment.
   Measure onset/cross-correlation differences at the start and periodically
   during the recording. Account for microphone placement, acoustic path length
   and interface channel offset. Record sample rate, software versions, firmware,
   codecs, adapter and radio conditions. Report fixed offset, drift over time,
   jitter and dropouts separately. PipeWire's latency value is a diagnostic, not
   a substitute for this capture.
7. Run at least two hours, preferably a full workday, including ordinary CPU load,
   radio interference conditions and device battery changes. Record audible
   artifacts and simultaneous acoustic captures where available. Repeat real
   disconnect/reconnect cycles. Choose an acceptable audible offset and dropout
   rate with the user; no universal hardware threshold is claimed by this repo.
   Do not enable custom feedback correction based on an uncalibrated measurement.

If native compensation causes audible buffer changes, compare it disabled before
changing any other variable. If one device's hidden latency dominates, report
that limit rather than resetting both transports or promising perfect sync.
