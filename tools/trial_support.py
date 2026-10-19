"""Rollback building blocks for an authorized, single-context trial supervisor.

Importing this module performs no I/O on audio or services. It deliberately has
no command-line entry point that can start a hardware trial. Cross-context
callers request return through a private directory; they never signal saved PIDs.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import stat
import time


class RollbackError(RuntimeError):
    pass


class ContextMismatch(RollbackError):
    pass


def context_identity():
    return (os.stat('/proc/self/ns/pid').st_ino,
            Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def process_identity(pid):
    try:
        # comm may contain spaces and parentheses; split after its final ')'.
        fields = Path(f'/proc/{pid}/stat').read_text().rpartition(')')[2].split()
        return dict(state=fields[0], group=int(fields[2]), session=int(fields[3]),
                    started=fields[19])
    except (FileNotFoundError, ProcessLookupError):
        return None


class OwnedGroup:
    """Keep the Popen handle and namespace, not a portable numeric PID lease."""
    def __init__(self, proc, identity=context_identity):
        self.proc, self.identity = proc, identity
        self.context = identity()
        leader = process_identity(proc.pid)
        if not leader or leader['group'] != proc.pid or leader['session'] != proc.pid:
            raise RollbackError('Candidate must be spawned with start_new_session=True')
        self.leader = leader
        self.members = {proc.pid: leader}
        self.refresh()

    def assert_context(self):
        if self.identity() != self.context:
            raise ContextMismatch('Use request_return; saved PIDs belong to another execution context')

    def matches(self, pid, saved):
        current = process_identity(pid)
        return bool(current and current['started'] == saved['started'] and
                    current['group'] == saved['group'] and current['session'] == saved['session'])

    def refresh(self):
        self.assert_context()
        if not self.matches(self.proc.pid, self.leader):
            return  # Never discover members of a reused numeric group.
        for path in Path('/proc').iterdir():
            if path.name.isdigit():
                item = process_identity(int(path.name))
                if item and item['group'] == self.proc.pid and item['session'] == self.proc.pid:
                    self.members[int(path.name)] = item

    def alive(self):
        self.assert_context()
        self.proc.poll()
        result=[]
        for pid,saved in self.members.items():
            current=process_identity(pid)
            if current and current['started']==saved['started'] and current['group']==saved['group'] and current['session']==saved['session'] and current['state']!='Z':
                result.append(pid)
        return result

    def send(self, pid, sig):
        # A pidfd pins the actual process across the check/signal race. There is
        # deliberately no kill-by-number fallback if the kernel lacks pidfds.
        try:
            fd=os.pidfd_open(pid)
        except ProcessLookupError:
            return
        try:
            if self.matches(pid,self.members[pid]):
                signal.pidfd_send_signal(fd,sig)
        except ProcessLookupError:
            pass
        finally:
            os.close(fd)

    def stop(self, grace=3):
        self.assert_context()
        self.refresh()
        # Controller first: it handles TERM and closes its native child. Captured
        # descendants are signalled too, including a hung child or orphan.
        for pid in self.alive():
            self.send(pid,signal.SIGTERM)
        deadline = time.monotonic() + grace
        while self.alive() and time.monotonic() < deadline:
            time.sleep(.05)
        for pid in self.alive():
            self.send(pid,signal.SIGKILL)
        deadline = time.monotonic() + 2
        while self.alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if self.alive():
            raise RollbackError('Owned processes did not terminate')


class Resources:
    """Remember serial-qualified nodes, clients, ports and connected links."""
    def __init__(self, token):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}', token):
            raise ValueError('A unique 16..64 character trial token is required')
        self.token, self.refs = token, set()

    @staticmethod
    def props(obj):
        return obj.get('info', {}).get('props', obj.get('props', {}))

    def remember(self, graph):
        ids = {i for i, p in graph.nodes.items() if p.get('split.session') == self.token}
        clients = {int(graph.nodes[i]['client.id']) for i in ids if 'client.id' in graph.nodes[i]}
        ports = {i for i, p in graph.ports.items() if int(p.get('node.id', -1)) in ids}
        links = {i for i, a, b, _ in graph.links if a in ports or b in ports}
        for i in ids | clients | ports | links:
            obj = graph.objects.get(i)
            if obj is None or 'object.serial' not in self.props(obj):
                raise RollbackError('Resource identity missing; cannot certify removal')
            self.refs.add((i, str(self.props(obj)['object.serial'])))

    def remaining(self, graph):
        self.remember(graph)
        return [(i, serial) for i, serial in self.refs if i in graph.objects
                and str(self.props(graph.objects[i]).get('object.serial')) == serial]


def private_directory(path):
    path = Path(path)
    item = path.lstat()
    if not stat.S_ISDIR(item.st_mode) or item.st_uid != os.getuid() or item.st_mode & 0o077:
        raise RollbackError('Trial directory must be a private, user-owned directory')
    return path


def request_return(path):
    """Safe from another PID namespace: only request; never signal or restore."""
    path = private_directory(path)
    fd = os.open(path / 'return.request', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)


def save_state(path, data):
    temporary = path / 'state.next'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(json.dumps(data, indent=2) + '\n')
    os.replace(temporary, path / 'state.json')


class ReturnSupervisor:
    """Only the original supervisor/companion in its PID context may restore.

    backend must expose graph(), mute(), restore(), verify(), resume(),
    verify_resumed(). restore() is never called until *all* remembered candidate
    resources vanish. verify() separates resources_ok from application limits.
    Exceptions leave FAILED, never a done flag; a retry repeats verification.
    """
    def __init__(self, path, group, resources, backend, timeout=8, sleep=time.sleep,
                 clock=time.monotonic):
        self.path = private_directory(path)
        self.group, self.resources, self.backend = group, resources, backend
        self.timeout, self.sleep, self.clock = timeout, sleep, clock

    def run(self):
        self.group.assert_context()  # Before muting or any service/audio write.
        with (self.path / 'return.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state_path=self.path/'state.json'
                if state_path.exists() and json.loads(state_path.read_text()).get('complete'):
                    result=self.backend.verify()
                    if not result['resources_ok'] or self.resources.remaining(self.backend.graph()) or self.group.alive() or not self.backend.verify_resumed():
                        raise RollbackError('Previously restored state no longer verified; no audio writes')
                    result=dict(phase='RESTORED' if result.get('applications_ok') else 'RESTORED_WITH_APP_LIMIT',complete=True,**result)
                    save_state(self.path,result)
                    return result
                save_state(self.path, {'phase': 'STOPPING', 'complete': False})
                self.resources.remember(self.backend.graph())
                self.backend.mute()
                self.group.stop()
                deadline = self.clock() + self.timeout
                while self.resources.remaining(self.backend.graph()):
                    if self.clock() >= deadline:
                        raise RollbackError('Candidate resources still exported; original watchdog remains paused')
                    self.sleep(.05)
                if self.group.alive():
                    raise RollbackError('Candidate process still alive')
                save_state(self.path, {'phase': 'RESTORING', 'complete': False})
                self.backend.restore()
                verification = self.backend.verify()
                if not verification['resources_ok']:
                    raise RollbackError('Original resources not verified; watchdog remains paused')
                # A concurrent new candidate invalidates the handoff too.
                if self.resources.remaining(self.backend.graph()):
                    raise RollbackError('Candidate returned before handoff')
                self.backend.resume()
                if not self.backend.verify_resumed():
                    raise RollbackError('Original watchdog did not resume as expected')
                # Verify again AFTER resume; a successful thaw is not proof.
                verification = self.backend.verify()
                if not verification['resources_ok'] or self.resources.remaining(self.backend.graph()):
                    raise RollbackError('State changed during watchdog handoff')
                result = dict(phase='RESTORED' if verification.get('applications_ok') else 'RESTORED_WITH_APP_LIMIT',
                              complete=True, **verification)
                save_state(self.path, result)
                return result
            except Exception as exc:
                save_state(self.path, {'phase': 'FAILED', 'complete': False, 'error': str(exc)})
                raise

    def poll(self, deadline):
        """Run in the persistent owning process, not in a new tool invocation."""
        self.group.assert_context()
        if (self.path / 'return.request').exists() or self.clock() >= deadline:
            return self.run()
        return None


def edges(graph):
    result = set()
    for _, a, b, _ in graph.links:
        pa, pb = graph.ports[a], graph.ports[b]
        result.add((graph.nodes[int(pa['node.id'])]['node.name'], pa['port.name'],
                    graph.nodes[int(pb['node.id'])]['node.name'], pb['port.name']))
    return result


def application_comparison(saved, current, owner):
    """A recreated stream is a limit to report, never permission to move by name."""
    current = {str(i['properties'].get('object.serial')): i for i in current
               if i['properties'].get('split.owner') != owner}
    result = []
    for item in saved:
        if item['properties'].get('split.owner') == owner:
            continue
        serial = str(item['properties'].get('object.serial'))
        live = current.get(serial)
        result.append(dict(serial=serial, same_stream=live is not None,
                           state_matches=bool(live and all(live[k] == item[k]
                                               for k in ('restore_sink', 'mute', 'corked')))))
    return result


class PulseRestore:
    """A narrow Pulse/graph adapter; service control is supplied by the owner.

    baseline: sinks to preserve, legacy {argument}, default, original outgoing
    virtual edges, and hashes. playback is the last pre-return snapshot (may
    include a video started after the trial began). No pairing/profile/media API.
    """
    def __init__(self, cfg, baseline, playback, run, read, watchdog):
        allowed={cfg['LEFT_DEVICE'], cfg['RIGHT_DEVICE'], cfg['VIRTUAL_SINK'], cfg.get('EFFECTS_SINK', 'easyeffects_sink')}
        if set(baseline['sinks']) - allowed:
            raise RollbackError('Refusing to write unrelated sink levels')
        self.cfg, self.before, self.playback = cfg, baseline, playback
        self.run, self.read, self.watchdog = run, read, watchdog
        self.module = None

    def graph(self):
        return self.read()

    def sinks(self):
        return {s['name']: s for s in json.loads(self.run('pactl', '-f', 'json', 'list', 'sinks'))}

    def inputs(self):
        names = {s['index']: name for name, s in self.sinks().items()}
        result = json.loads(self.run('pactl', '-f', 'json', 'list', 'sink-inputs'))
        for item in result:
            item['restore_sink'] = names.get(item['sink'])
        return result

    def signature(self, sinks):
        return tuple((sinks[self.cfg[side + '_DEVICE']]['index'],
                      sinks[self.cfg[side + '_DEVICE']]['properties']['object.serial'])
                     for side in ('LEFT', 'RIGHT'))

    def mute(self):
        if self.signature(self.sinks()) != self.signature(self.before['sinks']):
            raise RollbackError('Physical identity changed')
        if not self.watchdog.paused():
            raise RollbackError('Original watchdog is not paused')
        present=self.sinks()
        virtual=self.cfg['VIRTUAL_SINK']
        if virtual in present:
            graph=self.graph()
            nodes=graph.named(virtual)
            props=graph.nodes[nodes[0]] if len(nodes)==1 else {}
            candidate=(props.get('split.session')==self.cfg.get('TRIAL_TOKEN') and
                       bool(self.cfg.get('TRIAL_TOKEN')) and
                       props.get('split.owner')=='linux-bluetooth-split-stereo')
            legacy=self.modules()
            original=(len(legacy)==1 and legacy[0][1]==self.before['legacy']['argument'] and
                      str(present[virtual].get('owner_module'))==legacy[0][0])
            if not candidate and not original:
                raise RollbackError('Virtual identity is foreign or ambiguous; no levels changed')
        for name in self.before['sinks']:
            if name in present:
                self.run('pactl', 'set-sink-mute', name, '1')
            elif name!=self.cfg['VIRTUAL_SINK']:
                raise RollbackError('Preserved sink disappeared')

    def modules(self):
        result = []
        for line in self.run('pactl', 'list', 'short', 'modules').splitlines():
            parts = line.split('\t')
            if len(parts) >= 3 and parts[1] == 'module-null-sink' and ('sink_name=' + self.cfg['VIRTUAL_SINK']) in parts[2].split():
                result.append((parts[0], parts[2]))
        return result

    def restore(self):
        name = self.cfg['VIRTUAL_SINK']
        modules = self.modules()
        if len(modules) > 1 or (modules and modules[0][1] != self.before['legacy']['argument']):
            raise RollbackError('Ambiguous/foreign legacy module')
        if not modules:
            if self.graph().named(name):
                raise RollbackError('Virtual name occupied; no node removed')
            self.run('pactl', 'load-module', 'module-null-sink', self.before['legacy']['argument'])
        modules = self.modules()
        if len(modules) != 1:
            raise RollbackError('Legacy module not confirmed')
        if str(self.sinks().get(name,{}).get('owner_module'))!=modules[0][0]:
            raise RollbackError('Virtual sink does not belong to the confirmed legacy module')
        self.module = modules[0]
        deadline = time.monotonic() + 5
        while True:
            graph = self.graph()
            ids = graph.named(name)
            if len(ids) == 1 and sorted(p.get('audio.channel') for p in graph.ports_for(ids[0], 'in').values()) == ['FL', 'FR']:
                if graph.nodes[ids[0]].get('split.owner'):
                    raise RollbackError('Legacy sink is marked as candidate')
                break
            if time.monotonic() >= deadline:
                raise RollbackError('Legacy ports not ready')
            time.sleep(.05)
        # Set gains while all preserved outputs remain muted.
        for target, saved in self.before['sinks'].items():
            self.run('pactl', 'set-sink-volume', target, *[str(v['value']) for v in saved['volume'].values()])
        outgoing = [tuple(e) for e in self.before['edges'] if e[0] == name]
        incoming = [tuple(e) for e in self.playback['edges'] if e[2] == name]
        self.expected = set(outgoing + incoming)
        # Only these preidentified EE output ports may have acquired fallback links.
        controlled = {(e[0], e[1]) for e in incoming}
        graph = self.graph()
        for link, a, b, _ in graph.links:
            pa, pb = graph.ports[a], graph.ports[b]
            row = (graph.nodes[int(pa['node.id'])]['node.name'], pa['port.name'],
                   graph.nodes[int(pb['node.id'])]['node.name'], pb['port.name'])
            if (row[0], row[1]) in controlled and row not in self.expected:
                self.run('pw-link', '-d', str(link))
        for source, sp, target, tp in sorted(self.expected):
            graph = self.graph()
            if (source, sp, target, tp) in edges(graph):
                continue
            a = [i for n in graph.named(source) for i,p in graph.ports_for(n, 'out').items() if p['port.name'] == sp]
            b = [i for n in graph.named(target) for i,p in graph.ports_for(n, 'in').items() if p['port.name'] == tp]
            if len(a) != 1 or len(b) != 1:
                raise RollbackError('Cannot uniquely resolve original route')
            self.run('pw-link', str(a[0]), str(b[0]))
        # Move only the SAME surviving input that had a confirmed saved route.
        current = {str(i['properties'].get('object.serial')): i for i in self.inputs()}
        for saved in self.playback['inputs']:
            if saved['properties'].get('split.owner') == 'linux-bluetooth-split-stereo':
                continue
            serial=saved['properties'].get('object.serial')
            if serial is None:
                raise RollbackError('Application identity missing; refusing route write')
            live = current.get(str(serial))
            if live and live['restore_sink'] != saved['restore_sink']:
                self.run('pactl', 'move-sink-input', str(live['index']), saved['restore_sink'])
        self.run('pactl', 'set-default-sink', self.before['default'])
        for target, saved in self.before['sinks'].items():
            self.run('pactl', 'set-sink-mute', target, '1' if saved['mute'] else '0')

    def routes_match(self):
        current=edges(self.graph())
        controlled={(e[0],e[1]) for e in self.expected}
        actual={e for e in current if (e[0],e[1]) in controlled}
        virtual=self.cfg['VIRTUAL_SINK']
        temporary={virtual,virtual+'.left',virtual+'.right'}
        unrelated={tuple(e) for e in self.playback['edges']
                   if e[0] not in temporary and e[2] not in temporary}
        return actual==self.expected and unrelated<=current

    def verify(self):
        import hashlib
        sinks = self.sinks()
        checks = dict(module=self.modules() == [self.module],
                      sink_module=str(sinks[self.cfg['VIRTUAL_SINK']].get('owner_module'))==self.module[0],
                      signature=self.signature(sinks) == self.signature(self.before['sinks']),
                      levels=all(sinks[n]['volume'] == s['volume'] and sinks[n]['mute'] == s['mute']
                                 for n,s in self.before['sinks'].items()),
                      routes=self.routes_match(),
                      transport=all(all(sinks[self.cfg[side+'_DEVICE']].get('properties',{}).get(k)==self.before['sinks'][self.cfg[side+'_DEVICE']].get('properties',{}).get(k) for k in ('api.bluez5.codec','api.bluez5.profile')) for side in ('LEFT','RIGHT')),
                      default=self.run('pactl', 'get-default-sink').strip() == self.before['default'],
                      hashes=all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
                                 for p,digest in self.before.get('hashes', {}).items()))
        apps = application_comparison(self.playback['inputs'], self.inputs(), 'linux-bluetooth-split-stereo')
        return dict(resources_ok=all(checks.values()), checks=checks,
                    applications_ok=all(i['state_matches'] for i in apps), applications=apps)

    def resume(self):
        if self.signature(self.sinks()) != self.signature(self.before['sinks']):
            raise RollbackError('Physical identity changed before resume')
        self.watchdog.resume()

    def verify_resumed(self):
        return self.watchdog.verify_resumed()


class WatchdogLease:
    """Only resumes a preauthorized, still-paused original process; never starts it."""
    def __init__(self, run, prefix, unit, saved, request_flag):
        self.run, self.prefix, self.unit, self.saved = run, tuple(prefix), unit, saved
        self.request_flag = Path(request_flag)

    def state(self):
        output=self.run(*self.prefix,'show',self.unit,'-p','MainPID','-p','ActiveState',
                        '-p','SubState','-p','UnitFileState','-p','FreezerState')
        return dict(line.split('=',1) for line in output.splitlines())

    def paused(self):
        state=self.state()
        return state.get('MainPID')==self.saved['MainPID'] and state.get('FreezerState')=='frozen'

    def resume(self):
        if self.request_flag.exists() or not self.paused():
            raise RollbackError('Unsafe original watchdog state; no start or reconnect fallback')
        self.run(*self.prefix,'thaw',self.unit)

    def verify_resumed(self):
        state=self.state()
        return all(state.get(k)==self.saved[k] for k in ('MainPID','ActiveState','SubState','UnitFileState')) and state.get('FreezerState')=='running'
