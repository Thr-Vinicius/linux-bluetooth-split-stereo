# Audit of baseline 79b55f4

All baseline tracked files were inspected: three audio scripts, media shortcut,
legacy waiter, README, config, user unit, both examples, gitignore and MIT license.
Severity below describes playback/recovery impact, not a separate vulnerability
scan. Findings came directly from code; hardware hypotheses are listed separately.

| Severity | Proven defect in baseline | Change |
| --- | --- | --- |
| High | Watchdog invokes full disconnect/reconnect for new sink IDs; resync explicitly disconnects both devices | No Bluetooth commands in any recovery path |
| High | Readiness only checks presence of sinks; ready loop never checks audio links | Inspect ports and every required/extraneous owned link; verify after mutation |
| High | split script deletes and recreates correct links on every execution | Set-difference repair; stable graph produces zero link writes |
| High | Repeated volume reset, unmute, default takeover and move of every sink-input | Preserve physical/virtual manual settings; transition-only defaults; no stream moves |
| High | `playerctl play` after resync can resume intentionally paused media | Recovery never invokes playerctl |
| Medium | Saved `LEFT_INDEX:RIGHT_INDEX` described as synchronized | No persisted ID signature or acoustic-health assertion |
| Medium | Hardcoded playback_FL/FR fails on mono endpoints | Native mono-per-side stream, verified MONO or stereo physical layout |
| Medium | Most command errors ignored and Bluetooth commands unbounded | Checked subprocesses with five-second command deadlines, backoff and graph verification |
| Medium | Watchdog lock doesn't serialize direct split/resync calls | Lifetime lock plus shared operation lock across entry points |
| Medium | Fixed sleeps/periodic checks and per-tick shell process pipelines | Native hotplug lifecycle, event coalescing, bounded graph audit; no custom latency probes |
| Medium | Global predictable /tmp media lock/state; watchdog falls back to /tmp | Private runtime directories, owner/mode/symlink checks; user session required |
| Medium | Config sourced as arbitrary shell in three processes | Parse assignment data; validate addresses/names/booleans/timers; migration documented |
| Low | Legacy waiter has placeholder names, relative CWD dependency and regex substring matching | Stable script-relative controller call; waits for validated ROUTED state |
| Low | smart-prev accepts unvalidated timestamp/position and no player scoping | Strict mode, input validation, optional PLAYER and command deadlines |
| Low | Service does not order after pipewire-pulse; README omits new lifecycle and limitations | Updated unit and install/diagnostic/rollback guides |

The license did not need changes. gitignore now excludes Python cache files.
Examples now describe the native graph rather than the removed null-sink wiring.
No legacy entry point was deleted; repair semantics intentionally replace
transport reset, and the old waiter requires the supervisor to be running.

## Risks and hypotheses, not measured defects

- Unequal codec/firmware/transport delays, hardware clock drift, radio jitter and
  inaccurate reported latencies can cause audible offset. Their contributions
  have not been measured on the user's headphones.
- Native compensation may reduce reported delay differences but may resize
  buffers when reports change. Acoustic benefit/artifacts require hardware A/B.
- WirePlumber profile switching and active-session policy can remove sinks.
  Matching MAC-derived names tolerates suffix changes, but multiple matches or
  unsupported channel layouts are rejected; codecs and profiles are not forced.
- Physical/virtual volume restoration across full session resets depends on
  WirePlumber. The project does not impose levels during recovery.
- CLI graph operations are not atomic. Checked results and post-validation detect
  incomplete updates; a rapidly changing graph can remain DEGRADED until stable.
- A supervisor restart recreates its native sink and may briefly interrupt audio.
  Native client crash loops are rate-limited, but hardware listening is required
  before calling this version daily-use qualified.
- Default selection respects manual and session-policy changes conservatively;
  pinned application outputs are deliberately not overridden.

The final architecture has better verified software recovery properties; no
claim is made that it has already solved the user's acoustic alignment problem.
