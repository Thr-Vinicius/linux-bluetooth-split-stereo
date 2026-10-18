# Safe migration and rollback

Development used a separate clone/branch. It did not install scripts, change live
services, disconnect devices or modify your personal configuration.

1. Stop playback voluntarily. Record the current output and volume settings.
   Stop `fones-watchdog.service` with `systemctl --user stop fones-watchdog.service`.
   Stop any legacy watcher/resolver that still calls the old reconnect scripts.
2. Back up `~/.config/linux-bluetooth-split-stereo/config`, the installed scripts
   and `~/.config/systemd/user/fones-watchdog.service` into a dated directory.
   Keep an old checkout/commit (`79b55f4`) for rollback. Do not overwrite your only
   config with `config.example`.
3. Inspect `pactl list short modules`. If the **old** `module-null-sink` with
   `sink_name=split_lr` is present, unload just that numeric module with
   `pactl unload-module ID`. Confirm its name/arguments first. Do not unload other
   null sinks or restart PipeWire globally. The new service rejects a preexisting
   sink with the same name instead of deleting it. Existing monitor links vanish
   with the old sink. Remove only project-specific old persistent null-sink or
   combine config fragments if you previously added them manually, after backing
   them up. No installer in this revision edits those files for you.
4. Merge your real LEFT/RIGHT MAC or DEVICE values into the new example. MACs
   take precedence over exact names, so remove MAC assignments to pin exact names.
   Keep a real `FALLBACK_SINK` if you already use one. Config is now declarative:
   replace shell commands/variable expansion with their literal values.
5. Old `PHYSICAL_VOLUME`, `PHYSICAL_BASE`, `NON_SPLIT_VOLUME`, `VIRTUAL_VOLUME`,
   `RESOLVER`, `SPLIT_SCRIPT`, `RESYNC_SCRIPT`, `RESYNC_LOG`, `READY_TIMEOUT`,
   `IDLE_CHECK_INTERVAL`, `CONNECT_TIMEOUT`, `CONNECT_RETRY_INTERVAL` and
   `POST_CONNECT_SETTLE` assignments are ignored, not executed. Remove them after
   preserving the backup. `CHECK_INTERVAL` now means graph audit interval; use
   10 seconds normally. `ACTION_RETRY_DELAY` remains a failure backoff.
6. Follow the README install steps, including `bluetooth-split-controller.py`
   alongside the three wrappers. Update the unit and run
   `systemctl --user daemon-reload`. First test in the foreground with the service
   stopped. Choose a low physical volume manually before listening.
7. Replace shortcut/voice integrations that touch
   `/tmp/fones-watchdog-resync-request-UID.flag` or its runtime equivalent with a
   call to `~/.local/bin/resync-fones.sh`. The old flag protocol is retired; flags
   are not consumed, and arbitrary external resolver programs are not executed.
   Do not use this operation to resume paused players.
8. After checking left-only/right-only audio and fallback behavior, stop the
   foreground instance, then enable/start the user service. Run the hardware
   checklist before relying on it daily.

## Rollback

Stop the new service first; its child native sink/streams disappear on shutdown.
Restore the backed-up scripts, unit and config, then reload systemd. Recreate the
old sink using the old split script only after choosing the old architecture.
Start only one architecture at a time. The old version includes forced Bluetooth
reconnections and volume normalization; consider those behaviors before enabling
it again. The new runtime directory can be removed after stopping every new
controller; it contains locks, generated native config and default-output state,
not your personal permanent config. Never reuse a numeric module/node ID from an
old log when removing a live object.
