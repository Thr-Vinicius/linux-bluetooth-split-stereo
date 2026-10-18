#!/usr/bin/env python3
"""Supervise a native combine-stream client; reconcile only its output links."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import time

OWNER = 'linux-bluetooth-split-stereo'


class SplitError(Exception):
    pass


class OwnerError(SplitError):
    """Native owner is alive but a required stream/port is missing."""
    pass


def command(*args, timeout=5):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              check=True).stdout
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or '').strip()[:1000]
        raise SplitError(f'{args[0]} failed ({exc.returncode}): {detail}') from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise SplitError(f'{args[0]} failed: {exc}') from exc


def config(path):
    """Assignments only: old config files are data, never executable shell."""
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            tokens = shlex.split(line, comments=True)
            if not tokens:
                continue
            if len(tokens) != 1 or not re.fullmatch(r'[A-Z_]+=.*', tokens[0]):
                raise SplitError(f'{path}:{number}: expected KEY="value" assignment')
            key, value = tokens[0].split('=', 1)
            values[key] = value
    for key, default in [('VIRTUAL_SINK', 'split_lr'), ('FALLBACK_SINK', ''),
                         ('LATENCY_COMPENSATE', 'true'), ('AUTO_DEFAULT', 'true'),
                         ('CHECK_INTERVAL', '10'), ('ACTION_RETRY_DELAY', '5')]:
        values.setdefault(key, default)
    for side in ('LEFT', 'RIGHT'):
        mac = values.get(f'{side}_MAC', '')
        device = values.get(f'{side}_DEVICE', '')
        if mac and not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', mac):
            raise SplitError(f'{side}_MAC must be a Bluetooth MAC address')
        if not mac and not device:
            raise SplitError(f'Configure {side}_MAC or {side}_DEVICE in {path}')
        if device and not re.fullmatch(r'[A-Za-z0-9_.-]+', device):
            raise SplitError(f'Invalid {side}_DEVICE')
    if selector(values, 'LEFT') == selector(values, 'RIGHT'):
        raise SplitError('Left and right must be different devices')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', values['VIRTUAL_SINK']):
        raise SplitError('VIRTUAL_SINK must use letters, digits, underscore or hyphen')
    for key in ('LATENCY_COMPENSATE', 'AUTO_DEFAULT'):
        if values[key] not in ('true', 'false'):
            raise SplitError(f'{key} must be true or false')
    for key in ('CHECK_INTERVAL', 'ACTION_RETRY_DELAY'):
        try:
            value = float(values[key])
        except ValueError as exc:
            raise SplitError(f'{key} must be numeric') from exc
        if not 1 <= value <= 300:
            raise SplitError(f'{key} must be between 1 and 300 seconds')
    return values


def selector(cfg, side):
    mac = cfg.get(f'{side}_MAC')
    if mac:
        return '^bluez_output[.]' + mac.upper().replace(':', '_') + '[.].*$'
    return '^' + re.escape(cfg[f'{side}_DEVICE']) + '$'


def spa(value):
    """Emit SPA-JSON without JSON commas (PipeWire config section iterators)."""
    if isinstance(value, dict):
        return '{ ' + ' '.join(json.dumps(k) + ' = ' + spa(v) for k, v in value.items()) + ' }'
    if isinstance(value, list):
        return '[ ' + ' '.join(spa(v) for v in value) + ' ]'
    return json.dumps(value)


def native_config(cfg):
    # A mono stream per side makes the split independent of the physical layout.
    # Its one channel is fanned out to one MONO or both FL/FR device ports.
    name = cfg['VIRTUAL_SINK']
    rules = []
    for side, channel in [('LEFT', 'FL'), ('RIGHT', 'FR')]:
        rules.append({'matches': [{'media.class': 'Audio/Sink',
                                   'node.name': '~' + selector(cfg, side)}],
                      'actions': {'create-stream': {
                          'node.name': f'{name}.{side.lower()}',
                          'split.owner': OWNER,
                          'audio.position': ['MONO'],
                          'combine.audio.position': [channel]}}})
    return spa({
        'context.properties': {'core.daemon': False},
        'context.spa-libs': {'audio.convert.*': 'audioconvert/libspa-audioconvert',
                             'support.*': 'support/libspa-support'},
        'context.modules': [
            {'name': 'libpipewire-module-rt', 'flags': ['ifexists', 'nofail']},
            {'name': 'libpipewire-module-protocol-native'},
            {'name': 'libpipewire-module-client-node'},
            {'name': 'libpipewire-module-adapter'},
            {'name': 'libpipewire-module-combine-stream', 'args': {
                'combine.mode': 'sink', 'node.name': name,
                'node.description': 'Bluetooth L/R Split',
                'combine.latency-compensate': cfg['LATENCY_COMPENSATE'] == 'true',
                'resample.disable': False,
                'combine.props': {'audio.position': ['FL', 'FR'],
                                  'adapter.auto-port-config': {'mode': 'dsp'},
                                  'split.owner': OWNER,
                                  'priority.session': 0,
                                  # Safe initial level; WirePlumber restores saved values.
                                  'node.param.Props': {'volume': 0.064}},
                'stream.props': {'node.autoconnect': False,
                                 'node.dont-fallback': True,
                                 'node.dont-reconnect': True,
                                 'node.dont-move': True,
                                 'stream.dont-remix': True,
                                 'adapter.auto-port-config': {'mode': 'dsp'}},
                'stream.rules': rules}}]})


class Graph:
    def __init__(self, objects):
        self.objects = {int(o['id']): o for o in objects}
        self.nodes = {i: o['info']['props'] for i, o in self.objects.items()
                      if o['type'].endswith(':Node') and o.get('info')}
        self.ports = {i: o['info']['props'] for i, o in self.objects.items()
                      if o['type'].endswith(':Port') and o.get('info')}
        self.links = []
        for i, obj in self.objects.items():
            if obj['type'].endswith(':Link') and obj.get('info'):
                info = obj['info']
                self.links.append((i, int(info['output-port-id']),
                                   int(info['input-port-id']), info.get('state')))

    def named(self, name):
        return [i for i, p in self.nodes.items() if p.get('node.name') == name]

    def physical(self, cfg, side):
        return [i for i, p in self.nodes.items()
                if p.get('media.class') == 'Audio/Sink'
                and re.fullmatch(selector(cfg, side), p.get('node.name', ''))]

    def ports_for(self, node, direction):
        return {i: p for i, p in self.ports.items()
                if int(p.get('node.id', -1)) == node and p.get('port.direction') == direction}

    def plan(self, cfg):
        name = cfg['VIRTUAL_SINK']
        virtual = self.named(name)
        if len(virtual) != 1 or self.nodes[virtual[0]].get('split.owner') != OWNER:
            raise SplitError('Native virtual sink missing or name occupied; start the watchdog / migrate old sink')
        if self.objects[virtual[0]]['info'].get('state') == 'error':
            raise SplitError('Virtual sink reports an error')
        virtual_ports = self.ports_for(virtual[0], 'in')
        if sorted(p.get('audio.channel', '') for p in virtual_ports.values()) != ['FL', 'FR']:
            raise OwnerError('Native virtual sink must expose exactly FL/FR')
        if set(self.physical(cfg, 'LEFT')) & set(self.physical(cfg, 'RIGHT')):
            raise SplitError('Left and right resolve to the same physical sink')
        desired, owned_ports, available = set(), set(), []
        for side in ('LEFT', 'RIGHT'):
            devices = self.physical(cfg, side)
            streams = self.named(f'{name}.{side.lower()}')
            if len(devices) > 1 or len(streams) > 1:
                raise SplitError(f'Ambiguous {side} nodes; configure an exact device name without MAC')
            if streams:
                if self.nodes[streams[0]].get('split.owner') != OWNER:
                    raise SplitError('Foreign stream occupies split name')
                outputs = self.ports_for(streams[0], 'out')
                owned_ports.update(outputs)
            else:
                outputs = {}
            if not devices:
                continue
            if self.objects[devices[0]]['info'].get('state') == 'error':
                raise SplitError(f'{side}: physical sink reports an error')
            available.append(self.nodes[devices[0]]['node.name'])
            inputs = self.ports_for(devices[0], 'in')
            channels = [p.get('audio.channel') for p in inputs.values()]
            if sorted(channels or ['']) not in (['MONO'], ['FL', 'FR']):
                raise SplitError(f'{side}: expected MONO or FL/FR playback ports, found {channels}')
            if len(outputs) != 1:
                raise OwnerError(f'{side}: native mono stream not ready')
            source = next(iter(outputs))
            desired.update((source, target) for target in inputs)
        # Only links originating in our playback streams are ours to remove.
        # Monitor consumers and unrelated application streams are left alone.
        remove, kept = [], set()
        for link, source, target, state in self.links:
            if source not in owned_ports:
                continue
            pair = (source, target)
            if state not in ('active', 'paused', 'error'):
                raise SplitError(f'DEGRADED: link {link} is {state}; waiting for negotiation')
            if pair not in desired or pair in kept or state == 'error':
                remove.append(link)
            else:
                kept.add(pair)
        state = ('DISCONNECTED' if not available else
                 'PARTIAL' if len(available) == 1 else 'ROUTED')
        return state, desired - kept, remove, available


def snapshot():
    try:
        return Graph(json.loads(command('pw-dump')))
    except (ValueError, KeyError, TypeError) as exc:
        raise SplitError('Invalid PipeWire graph snapshot') from exc


def reconcile(cfg, read=snapshot, run=command):
    graph = read()
    state, missing, unwanted, available = graph.plan(cfg)
    for link in unwanted:
        run('pw-link', '-d', str(link))
    for source, target in sorted(missing):
        run('pw-link', str(source), str(target))
    # A successful command is not proof the graph remained valid after a race.
    after = read()
    state, missing, unwanted, available = after.plan(cfg)
    if missing or unwanted:
        raise SplitError('DEGRADED: routes changed during reconciliation; will retry')
    owned = {i for i, p in after.nodes.items() if p.get('split.owner') == OWNER}
    for _, source, _, link_state in after.links:
        if int(after.ports.get(source, {}).get('node.id', -1)) in owned:
            if link_state not in ('active', 'paused'):
                raise SplitError(f'DEGRADED: link state {link_state}')
    return state, available


def private_runtime():
    root = os.environ.get('XDG_RUNTIME_DIR')
    if not root:
        raise SplitError('XDG_RUNTIME_DIR is required; run inside your user session')
    path = Path(root) / OWNER
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SplitError(f'Unsafe runtime directory: {path}')
    return path


def lock(path, blocking=False):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        os.close(fd)
        raise SplitError('Another controller operation is running') from None
    return fd


def legacy_request(runtime):
    """Compatibility with installed resolvers: request route repair, never reconnect."""
    path = runtime.parent / f'fones-watchdog-resync-request-{os.getuid()}.flag'
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid():
        return path
    return None


class Defaults:
    """Take the default only on presence transitions; respect manual changes."""
    def __init__(self, cfg, path, run=command):
        self.cfg, self.path, self.run = cfg, path, run
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def update(self, state, available, graph):
        if self.cfg['AUTO_DEFAULT'] != 'true':
            return
        old_data = json.dumps(self.data)
        current = self.run('pactl', 'get-default-sink').strip()
        normal = [p['node.name'] for p in graph.nodes.values()
                  if p.get('media.class') == 'Audio/Sink' and 'node.name' in p
                  and not p['node.name'].startswith('bluez_output.')
                  and p.get('split.owner') != OWNER]
        if current in normal:
            self.data['fallback'] = current
        previous = self.data.get('presence')
        presence = state + ':' + ','.join(sorted(available))
        last = self.data.get('selected')
        if previous != presence:
            fallback = self.cfg['FALLBACK_SINK'] or self.data.get('fallback')
            if fallback not in normal:
                # Never choose arbitrary virtual effects sinks or speakers.
                fallback = next((n for n in normal if n.startswith('alsa_output.')), None)
            target = (self.cfg['VIRTUAL_SINK'] if state == 'ROUTED' else
                      available[0] if state == 'PARTIAL' else fallback)
            # A manual choice survives future hotplug until the user selects us.
            controlled = previous is None or current == last or current == self.cfg['VIRTUAL_SINK']
            if target and target != current and controlled:
                self.run('pactl', 'set-default-sink', target)
                self.data['selected'] = target
            elif current == target:
                self.data['selected'] = current
            # An unavailable fallback is not a completed transition. Retry when
            # its node appears, even if headphone presence stayed unchanged.
            if target or not controlled:
                self.data['presence'] = presence
        if json.dumps(self.data) == old_data:
            return
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data))
        temp.replace(self.path)


def stop_process(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def watch(cfg, runtime):
    # Separate lifetime lock from the short shared graph-operation lock.
    lifetime = lock(runtime / 'watchdog.lock')
    native = events = None
    stopped = False
    previous = None
    defaults = Defaults(cfg, runtime / 'defaults.json')
    config_path = runtime / 'native.conf'
    config_path.write_text(native_config(cfg))
    def stopping(_signum, _frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    retry_at = 0.0
    owner_failure_since = None
    starting_until = 0.0
    try:
        with selectors.DefaultSelector() as poll:
            while not stopped:
                now = time.monotonic()
                try:
                    if now < retry_at:
                        time.sleep(min(0.2, retry_at - now))
                        continue
                    graph = snapshot()
                    if native is not None and native.poll() is not None:
                        code = native.returncode
                        native = None
                        raise SplitError(f'Native client exited ({code}); check combine-stream module availability')
                    if native is None:
                        if graph.named(cfg['VIRTUAL_SINK']):
                            raise SplitError('Virtual sink name already exists; migrate old sink before starting')
                        env = os.environ.copy()
                        env['PIPEWIRE_CONFIG_DIR'] = str(runtime)
                        env.pop('PIPEWIRE_CONFIG_NAME', None)
                        env.pop('PIPEWIRE_CONFIG_PREFIX', None)
                        native = subprocess.Popen(['pipewire', '-c', config_path.name], env=env)
                        starting_until = time.monotonic() + 10
                        retry_at = now + 1
                        continue
                    if not graph.named(cfg['VIRTUAL_SINK']):
                        if time.monotonic() < starting_until:
                            raise SplitError('Native client initializing; waiting for virtual sink')
                        # Owner alive but its node was removed: restart only our client.
                        stop_process(native)
                        native = None
                        raise SplitError('Native sink disappeared; restarting its owner')
                    starting_until = 0.0
                    fd = lock(runtime / 'operation.lock')
                    try:
                        state, available = reconcile(cfg)
                        defaults.update(state, available, snapshot())
                        request = legacy_request(runtime)
                        if request is not None:
                            request.unlink(missing_ok=True)
                    finally:
                        os.close(fd)
                    owner_failure_since = None
                    message = state + ' (acoustic synchronization unmeasured)'
                    if events is None or events.poll() is not None:
                        if events is not None:
                            poll.unregister(events.stdout)
                            events.stdout.close()
                        events = subprocess.Popen(['pactl', 'subscribe'], stdout=subprocess.PIPE,
                                                  stderr=subprocess.DEVNULL)
                        os.set_blocking(events.stdout.fileno(), False)
                        poll.register(events.stdout, selectors.EVENT_READ)
                except SplitError as exc:
                    if isinstance(exc, OwnerError):
                        if owner_failure_since is None:
                            owner_failure_since = time.monotonic()
                        elif time.monotonic() - owner_failure_since >= 10:
                            stop_process(native)
                            native = None
                            owner_failure_since = None
                    else:
                        owner_failure_since = None
                    message = f'ERROR: {exc}'
                    retry_at = time.monotonic() + float(cfg['ACTION_RETRY_DELAY'])
                if message != previous:
                    print(message, flush=True)
                    previous = message
                # Pulse events accelerate hotplug; the periodic graph audit catches
                # link-only changes. Ignore client churn caused by graph inspection.
                deadline = time.monotonic() + float(cfg['CHECK_INTERVAL'])
                while not stopped and time.monotonic() < deadline:
                    if legacy_request(runtime) is not None:
                        break
                    delay = max(0, min(1, deadline - time.monotonic()))
                    if events and events.poll() is None:
                        if poll.select(timeout=delay):
                            payload = os.read(events.stdout.fileno(), 65536)
                            if not payload or re.search(rb" on (sink|card|server) #", payload):
                                time.sleep(0.15)
                                break
                    else:
                        time.sleep(min(delay, 1))
                        break
    finally:
        stop_process(events)
        stop_process(native)
        os.close(lifetime)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['watch', 'repair', 'status', 'print-config'])
    args = parser.parse_args()
    path = Path(os.environ.get('BLUETOOTH_SPLIT_CONFIG',
                str(Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) /
                    OWNER / 'config')))
    try:
        cfg = config(path)
        if args.action == 'print-config':
            print(native_config(cfg))
            return 0
        runtime = private_runtime()
        if args.action == 'watch':
            watch(cfg, runtime)
        elif args.action == 'status':
            state, missing, extra, _ = snapshot().plan(cfg)
            print(json.dumps({'state': 'DEGRADED' if missing or extra else state,
                              'missing_links': len(missing), 'unwanted_links': len(extra),
                              'acoustic_sync': 'unmeasured'}))
            return int(bool(missing or extra))
        else:
            fd = lock(runtime / 'operation.lock')
            try:
                state, _ = reconcile(cfg)
                print(f'{state}; routes checked; acoustic synchronization unmeasured')
            finally:
                os.close(fd)
        return 0
    except (SplitError, OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
