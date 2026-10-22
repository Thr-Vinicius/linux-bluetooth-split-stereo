#!/usr/bin/env python3
"""Finite read-only graph/volume sampler. Does not measure acoustic sync or play audio."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

spec = importlib.util.spec_from_file_location('controller', Path(__file__).resolve().parents[1] / 'bluetooth-split-controller.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def sample(cfg):
    graph = c.snapshot()
    sinks = json.loads(c.command('pactl', '-f', 'json', 'list', 'sinks'))
    levels = {s['name']: {'volume': s.get('volume'), 'mute': s.get('mute')} for s in sinks}
    sides = {}
    for side in ('LEFT', 'RIGHT'):
        nodes = graph.physical(cfg, side)
        sides[side.lower()] = [{'codec': graph.nodes[n].get('api.bluez5.codec'),
                                'profile': graph.nodes[n].get('api.bluez5.profile'),
                                'node_serial': graph.nodes[n].get('object.serial'),
                                **levels.get(graph.nodes[n].get('node.name'), {})} for n in nodes]
    result = {'devices': sides, 'default': c.command('pactl', 'get-default-sink').strip(),
              'virtual': levels.get(cfg['VIRTUAL_SINK']), 'acoustic_sync': 'unmeasured',
              'audio_continuity': 'unmeasured'}
    virtual = graph.named(cfg['VIRTUAL_SINK'])
    result['backend'] = ('native' if len(virtual) == 1 and
                         graph.nodes[virtual[0]].get('split.owner') == c.OWNER else 'other')
    if result['backend'] == 'native':
        try:
            state, missing, extra, _ = graph.plan(cfg)
            result.update(state='DEGRADED' if missing or extra else state,
                          missing_links=len(missing), extra_links=len(extra))
        except c.SplitError as exc:
            result.update(state='ERROR', error=str(exc))
    else:
        result.update(state='NOT_EVALUATED', note='Current sink is not the native candidate')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=60)
    parser.add_argument('--interval', type=float, default=30)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 86400 or not 1 <= args.interval <= 300:
        parser.error('seconds must be 1..86400; interval must be 1..300')
    os.umask(0o077)
    cfg = c.config(args.config)
    started = time.monotonic()
    deadline = started + args.seconds
    count = failures = native_samples = 0
    interrupted = False
    # Exclusive creation prevents overwriting a prior observation.
    with args.output.open('x') as output:
        try:
            while time.monotonic() < deadline:
                tick = time.monotonic()
                try:
                    row = sample(cfg)
                except (c.SplitError, ValueError, OSError) as exc:
                    row = {'state': 'ERROR', 'error': str(exc), 'acoustic_sync': 'unmeasured'}
                failures += int(row['state'] in ('ERROR', 'DEGRADED'))
                native_samples += int(row.get('backend') == 'native')
                count += 1
                row.update(timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           elapsed_seconds=round(time.monotonic() - started, 3))
                output.write(json.dumps(row, ensure_ascii=False) + '\n')
                output.flush()
                time.sleep(max(0, min(deadline - time.monotonic(), args.interval - (time.monotonic() - tick))))
        except KeyboardInterrupt:
            interrupted = True
        elapsed = time.monotonic() - started
        summary = {'kind': 'summary', 'elapsed_seconds': round(elapsed, 3),
                   'requested_seconds': args.seconds, 'interrupted': interrupted,
                   'duration_completed': not interrupted and elapsed >= args.seconds,
                   'samples': count, 'native_samples': native_samples,
                   'unhealthy_samples': failures,
                   'acoustic_sync': 'unmeasured', 'audio_continuity': 'unmeasured',
                   'note': 'Periodic snapshots cannot detect every dropout or establish acoustic alignment'}
        output.write(json.dumps(summary) + '\n')
        print(json.dumps(summary))
    return 130 if interrupted else int(bool(failures))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (c.SplitError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
