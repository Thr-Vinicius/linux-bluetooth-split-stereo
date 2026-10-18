# Architecture decision: native buffering, conservative graph supervision

Baseline: upstream commit `79b55f4`; all tracked files were read. No prior audit
was treated as authoritative. Research and isolated execution used PipeWire
1.6.9. The local audio session and Bluetooth devices were not modified.

## Alternatives

| Choice | Advantages | Limits / decision |
| --- | --- | --- |
| Existing null sink + raw monitor links | Few processes, simple graph | No explicit per-output delay compensation; current code destroys healthy links, hardcodes stereo ports, confuses object IDs with sync |
| Repair only the old links | Small migration; fixes reconnection and volume bugs | Still leaves the latency architecture unchanged; valid fallback design, not selected here |
| Native combine-stream + targeted links | Per-output native buffering, independent stream lifecycle, explicit channel remapping, maintained upstream audio code | Adds a native client process; reported latency can be inaccurate; selected with isolated graph and sample tests |
| Server startup combine-stream fragment | Native virtual sink outlives watcher restart | Requires changing/restarting PipeWire and managing a separate persistent config; avoided for this migration |
| Custom latency/drift control | Could express measured device-specific corrections | No accurate acoustic sensor or benefit evidence; rejected |
| Bluetooth disconnect/reconnect | Sometimes changes perceived alignment on particular devices | Resets transport and interrupts audio; not a timing reference; rejected as normal recovery |

The controller generates a standalone client config using the official
filter-chain client module pattern: protocol-native, client-node, adapter, optional
RT module, plus combine-stream. It does not become another system audio server.
Native stream rules target only the configured sinks; exact names or anchored
MAC-derived node-name patterns are used. More than one match is an error.

Each side's native stream has `audio.position=[MONO]` and maps just FL or FR with
`combine.audio.position`. Its MONO port connects to a physical MONO port or both
physical FL/FR ports. This avoids depending on automatic channel remixing for
one-ear playback. Samples captured in dummy sinks verify the selected input
channel reaches both physical stereo inputs / the mono input.

Autoconnect is disabled for these two output streams. The supervisor controls
only their outgoing links; this prevents session-policy fallback of the left or
right stream into unrelated outputs. It never removes application links or
virtual-sink monitor consumers. A before/after graph snapshot and checked command
results prevent reporting success after an incomplete or raced correction.
Global IDs address objects within a snapshot only: they are not stored as proof
of synchronization. CLI operations are not transactional; a graph mutation can
still race a command and be recovered on the next audit.

## Timing research and limits

The official combine-stream documentation defines compensation as delay buffers
matching stream latencies. `audio.position` and `combine.audio.position` map the
combine channel positions to stream positions one by one. This supports a clean
split without reconnecting transports.

Source inspection of PipeWire 1.6.9 `module-combine-stream.c`, particularly
`get_stream_delay`, `update_delay`, `resize_delay` and `create_stream`, confirms
that compensation uses stream timing to derive differences and resize delay
buffers. It does not contain an acoustic measurement of headphone output.
Buffer changes can themselves affect audio; no claim is made that enabling the
option is always inaudibly beneficial. It is configurable and needs A/B testing.

The same source defaults `resample.disable` to true in this module. This project
explicitly sets it false rather than assuming resampling is enabled. Native
adapter resamplers handle rate/clock adaptation; `clock.name` is not forced equal
on independent devices. No high-frequency external delay adjustments, quantum
forcing or codec selection is imposed. Native compensation is enabled by default
as a technically supported experiment, not a validated acoustic correction.

A fixed difference can come from unequal device/codec/DSP/transport buffers;
these are plausible causes, not measured diagnoses of the user's pair. Clock
rate mismatch can accumulate drift. Radio scheduling and load can add jitter.
Reported PipeWire latency can omit or misestimate downstream delay, so matching
it does not guarantee matching acoustic onset. A fixed external measurement would
justify a separate device-specific delay; this revision does not invent one or
apply a global offset that might compensate the wrong path.

## Lifecycle and policy tradeoffs

The owner remains alive through device changes and selective link repair. On
PipeWire loss it exits or is detected stale and is restarted with backoff. Lost
virtual nodes restart only this client. Watchdog restarts intentionally recreate
its client and can briefly interrupt audio; no Bluetooth reconnection occurs.
A future separate persistent owner could avoid that interruption, at the cost
of another lifecycle component. That complexity has not been introduced here.

Pulse subscriptions accelerate device changes; not every PipeWire link event is
available through Pulse, so a bounded low-rate full graph audit remains. It is
not a latency sampler. Invalid commands/timeouts produce visible errors, not
fake readiness. Connection attempts remain under the desktop/BlueZ policy: an
absent sink is not evidence that a Bluetooth disconnect/reconnect is needed.

The supervisor never moves individual streams. Selecting defaults on transitions
preserves the useful single-device/fallback behavior, but respects a changed
default and application-specific routing. Pinned applications may need manual
selection after a physical disconnect. Physical volumes/mute and media playback
are not touched. A conservative initial virtual gain plus WirePlumber's normal
restore policy replaces unconditional volume normalization.

## Primary references (consulted 2026-10-18)

- [PipeWire combine-stream options and channel maps](https://docs.pipewire.org/page_module_combine_stream.html)
- [PipeWire 1.6.9 implementation](https://github.com/PipeWire/pipewire/blob/1.6.9/src/modules/module-combine-stream.c)
- [PipeWire property reference: resamplers, clocks, target and fallback policy](https://docs.pipewire.org/page_man_pipewire-props_7.html)
- [PipeWire latency propagation](https://docs.pipewire.org/page_latency.html)
- [Native client configuration pattern](https://github.com/PipeWire/pipewire/blob/1.6.9/src/daemon/filter-chain.conf.in)
- [WirePlumber Bluetooth monitors, profiles and logind](https://pipewire.pages.freedesktop.org/wireplumber/daemon/configuration/bluetooth.html)
- [BlueZ Device API: connection/profile success is not audio timing](https://bluez.readthedocs.io/en/latest/device-api/)
