"""Persistent A-B-A orchestration. Importing this module has no session effects."""
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys
import time

from trial_identity import identify, check_window, audit_difference, stamp, unique_node

from trial_support import (OwnedGroup, Resources, ReturnSupervisor, PulseRestore,
                           WatchdogLease, RollbackError, context_identity,
                           edges, private_directory, save_state)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('split_controller', ROOT/'bluetooth-split-controller.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class EmptyGroup:
    def __init__(self):
        self.context = context_identity()
    def assert_context(self):
        if context_identity() != self.context:
            raise RollbackError('Owner context changed')
    def alive(self):
        return []
    def stop(self, deadline=None):
        self.assert_context()


class Session:
    """One persistent owner drives swap, monitoring, deadline and verified return.

    adapter implements audio/service details; the SAME Session is used privately
    and by the explicit real executor. No numeric PID is sent over the file IPC.
    """
    def __init__(self, path, adapter, maximum=600, return_after=360, ready_timeout=30):
        if not (0 < ready_timeout < return_after < maximum <= 600) or maximum <= 2:
            raise ValueError('Require 0 < readiness < return < maximum <= 600')
        self.path = private_directory(path)
        self.adapter = adapter
        self.maximum, self.return_after, self.ready_timeout = maximum, return_after, ready_timeout
        self.context = context_identity()
        self.group = EmptyGroup()
        self.resources = Resources(adapter.cfg['TRIAL_TOKEN'])
        self.reason = None
        self.started = None
        self.stop_requested = False

    def event(self, phase, **fields):
        row = dict(phase=phase, owner_context=self.context,
                   monotonic=time.monotonic(), **fields)
        with (self.path/'events.jsonl').open('a') as output:
            output.write(json.dumps(row)+'\n')
        save_state(self.path, dict(complete=False, **row))
        try:
            print(json.dumps(row),flush=True)
        except (BrokenPipeError,OSError):
            pass  # Loss of the requesting terminal must not skip return.

    def heartbeat(self):
        temporary=self.path/'heartbeat.next'
        temporary.write_text(json.dumps(dict(monotonic=time.monotonic(),context=self.context)))
        os.replace(temporary,self.path/'heartbeat.json')

    def requested(self):
        return self.stop_requested or (self.path/'return.request').exists()

    def run(self):
        fd=os.open(self.path/'owner.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if (self.path/'events.jsonl').exists():
                raise RollbackError('Session already used; prepare a new private directory')
            return self._run()
        finally:os.close(fd)

    def _run(self):
        # Complete preflight, then prove a live IPC round trip before any write.
        self.adapter.preflight()
        (self.path/'before.json').write_text(json.dumps(self.adapter.before,indent=2)+'\n')
        self.started=time.monotonic()
        self.adapter.deadline=self.started+self.maximum-2
        self.heartbeat()
        self.event('ARMED', pid=os.getpid())
        arm_deadline = min(time.monotonic()+30,self.started+self.return_after)
        while not (self.path/'start.request').exists():
            self.heartbeat()
            if self.requested() or time.monotonic() >= arm_deadline:
                result=dict(phase='CANCELLED_UNCHANGED',complete=True,audio_changed=False)
                save_state(self.path,result)
                self.event_result(result)
                return result
            time.sleep(.05)
        self.event('A_SNAPSHOT')
        failure = None
        try:
            # The user may have changed levels or started A while ARMED. Capture
            # again immediately before the first intervention.
            self.adapter.preflight()
            (self.path/'before.json').write_text(json.dumps(self.adapter.before,indent=2)+'\n')
            self.adapter.freeze()
            self.event('FROZEN')
            self.adapter.remove_original()
            self.event('ORIGINAL_REMOVED')
            proc = self.adapter.launch(self.path)
            self.group = OwnedGroup(proc)
            self.event('CANDIDATE_STARTED', pid=proc.pid)
            ready_by = min(self.started+self.return_after, time.monotonic()+self.ready_timeout)
            while True:
                self.heartbeat()
                self.group.refresh()
                self.resources.remember(self.adapter.backend.graph())
                (self.path/'ownership.json').write_text(json.dumps(dict(context=self.context,processes=self.group.members,resources=sorted(self.resources.refs)))+'\n')
                if proc.poll() is not None:
                    raise RollbackError('Candidate exited before readiness')
                if self.requested():
                    self.reason='requested-before-ready'
                    break
                if self.adapter.ready():
                    self.adapter.route_candidate()
                    self.event('ROUTED')
                    break
                if time.monotonic() >= ready_by:
                    raise RollbackError('Readiness timeout')
                time.sleep(.1)
            warned=False
            while self.reason is None:
                self.heartbeat()
                remaining=self.started+self.return_after-time.monotonic()
                if not warned and remaining<=min(30,max(1,self.return_after/5)):
                    self.event('RETURN_DUE_SOON',seconds_remaining=max(0,remaining))
                    warned=True
                self.group.refresh()
                self.resources.remember(self.adapter.backend.graph())
                (self.path/'ownership.json').write_text(json.dumps(dict(context=self.context,processes=self.group.members,resources=sorted(self.resources.refs)))+'\n')
                if self.requested():
                    self.reason='requested'
                elif time.monotonic() >= self.started+self.return_after:
                    self.reason='deadline'
                elif proc.poll() is not None or not self.adapter.ready():
                    raise RollbackError('Candidate or route lost during evaluation')
                else:
                    self.adapter.observe(self.path)
                    time.sleep(.2)
        except Exception as exc:
            failure = str(exc)
            self.reason='failure'
            self.event('TRIAL_FAILED', error=failure)
        # Always owned here, even if no candidate was spawned or swap failed.
        self.event('RETURN_REQUESTED', reason=self.reason or 'failure')
        try:
            self.adapter.capture_playback()
        except Exception as exc:
            self.event('PLAYBACK_CAPTURE_FAILED',error=str(exc))
            self.adapter.backend.capture_unknown=True
        engine = ReturnSupervisor(self.path, self.group, self.resources, self.adapter.backend, deadline=self.adapter.deadline)
        result = None
        attempts = 0
        return_error=None
        while time.monotonic() < self.adapter.deadline:
            attempts += 1
            try:
                result = engine.run()
                break
            except Exception as exc:
                return_error=str(exc)
                self.event('RETURN_RETRY', attempt=attempts, error=str(exc))
                if attempts >= 3:
                    break
                time.sleep(.1)
        elapsed = time.monotonic()-self.started
        if result is None:
            result=dict(phase='FAILED',complete=False,resources_ok=False,return_error=return_error)
        result.update(reason=self.reason, trial_error=failure, attempts=attempts,
                      elapsed=elapsed, within_limit=elapsed <= self.maximum,
                      owner_context=self.context)
        if not result['within_limit']:
            result.update(phase='FAILED', complete=False)
        save_state(self.path, result)
        self.event_result(result)
        return result

    def event_result(self, result):
        with (self.path/'events.jsonl').open('a') as output:
            output.write(json.dumps(dict(monotonic=time.monotonic(), **result))+'\n')


class AudioAdapter:
    """Bounded commands, narrow original-resource ownership, no media commands."""
    def __init__(self, cfg, watchdog, hashes, run=None):
        self.cfg, self.watchdog, self.hashes = cfg, watchdog, hashes
        self.path = None
        self.deadline = None
        self.injected_run = run
        self.backend = None
        self.log = None
        self.expected_policy = None
        self.identity = None
        self.old_removal_requested = False
        self.candidate_requested = False
        self.native_stamp = None
        self.restored_module = None
        self.restored_stamp = None
        self.history = None

    def run(self, *args):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise RollbackError('Hard command deadline reached')
        timeout = 2 if self.deadline is None else max(.01,min(2,self.deadline-time.monotonic()))
        args=self.guard_write(args)
        if self.deadline is not None:
            if time.monotonic()>=self.deadline:raise RollbackError('Deadline reached during identity validation')
            timeout=max(.01,min(2,self.deadline-time.monotonic()))
        if self.injected_run:
            return self.injected_run(*args)
        try:
            result=c.command(*args,timeout=timeout)
        except Exception as exc:
            if self.path:
                with (self.path/'commands.jsonl').open('a') as output:
                    output.write(json.dumps(dict(monotonic=time.monotonic(),args=args,error=str(exc)))+'\n')
            raise
        if args[:3]==('pactl','load-module','module-null-sink'):
            self.restored_module=result.strip()
        if self.path:
            with (self.path/'commands.jsonl').open('a') as output:
                output.write(json.dumps(dict(monotonic=time.monotonic(),args=args,ok=True))+'\n')
        return result

    def null_modules(self):
        rows=[]
        for line in self.run('pactl','list','short','modules').splitlines():
            parts=line.split('\t')
            if len(parts)>=3 and parts[1]=='module-null-sink' and ('sink_name='+self.cfg['VIRTUAL_SINK']) in parts[2].split():
                rows.append((parts[0],parts[2]))
        return rows

    def assert_identity(self):
        if self.identity is None:
            raise RollbackError('No final current identity has been captured')
        raw=json.loads(self.run('pactl','-f','json','list','sinks'))
        graph=self.graph()
        sinks=check_window(self.cfg,raw,graph,self.identity)
        virtual=self.cfg['VIRTUAL_SINK']
        if virtual not in sinks:
            if graph.named(virtual) or not self.old_removal_requested:
                raise RollbackError('Original disappeared outside the controlled transition')
            return sinks,graph
        node,props=unique_node(graph,virtual)
        current=stamp(sinks[virtual],node,props)
        old=dict(self.identity['current']['legacy']);old_module=old.pop('module_id')
        if (current==old and str(sinks[virtual]['owner_module'])==old_module and
                not props.get('split.owner') and not props.get('split.session') and
                props.get('factory.name')==self.identity['stable']['legacy']['factory'] and
                props.get('media.class')=='Audio/Sink' and
                sinks[virtual].get('channel_map')==self.identity['stable']['legacy']['channel_map']):
            if self.null_modules()!=[(old_module,self.identity['stable']['legacy']['argument'])]:
                raise RollbackError('Original module identity/arguments changed')
        elif (self.candidate_requested and props.get('split.owner')==c.OWNER and
              props.get('split.session')==self.cfg['TRIAL_TOKEN']):
            if self.native_stamp is None:self.native_stamp=current
            elif self.native_stamp!=current:raise RollbackError('Candidate virtual was unexpectedly replaced')
        elif (self.restored_module is not None and str(sinks[virtual]['owner_module'])==self.restored_module and
              str(props.get('pulse.module.id'))==self.restored_module and
              props.get('factory.name')=='support.null-audio-sink' and not props.get('split.owner') and not props.get('split.session')):
            if self.restored_stamp is None:self.restored_stamp=current
            elif self.restored_stamp!=current:raise RollbackError('Restored virtual was replaced')
            if self.null_modules()!=[(self.restored_module,self.before['legacy']['argument'])]:
                raise RollbackError('Restored module arguments changed')
        else:
            raise RollbackError('Foreign or substituted virtual sink')
        return sinks,graph

    def guard_write(self,args):
        pulse_write=args[:2] in [('pactl',action) for action in ('unload-module','load-module','set-sink-volume','set-sink-mute','move-sink-input','set-default-sink')]
        link_write=args and args[0]=='pw-link'
        if not pulse_write and not link_write:return args
        sinks,graph=self.assert_identity()
        if not self.watchdog.paused():raise RollbackError('Write refused: original watchdog is not paused')
        if args[:2]==('pactl','unload-module'):
            if args[2]!=self.old_module[0] or self.null_modules()!=[self.old_module]:
                raise RollbackError('Refusing to unload an unowned module')
            self.old_removal_requested=True
        elif args[:2]==('pactl','load-module'):
            if args[2:]!=('module-null-sink',self.before['legacy']['argument']) or graph.named(self.cfg['VIRTUAL_SINK']) or self.null_modules():
                raise RollbackError('Refusing to replace an occupied or foreign virtual')
        elif args[:2] in [('pactl','set-sink-volume'),('pactl','set-sink-mute')]:
            target=args[2]
            if target not in self.before['sinks'] or target not in sinks:
                raise RollbackError('Unrecognized level target')
            # Use this window's checked numeric index; never resolve a stale name
            # again in pactl after the check.
            args=(*args[:2],str(sinks[target]['index']),*args[3:])
        elif args[:2] in [('pactl','move-sink-input'),('pactl','set-default-sink')]:
            target=args[3] if args[1]=='move-sink-input' else args[2]
            if args[1]=='move-sink-input':
                inputs=json.loads(self.run('pactl','-f','json','list','sink-inputs'))
                live=[i for i in inputs if str(i['index'])==args[2]]
                saved={str(i['properties'].get('object.serial')):i for i in self.backend.playback['inputs']}
                expected=saved.get(str(live[0]['properties'].get('object.serial'))) if len(live)==1 else None
                if not expected or expected['restore_sink']!=target:
                    raise RollbackError('Application route identity changed before move')
            elif target!=self.before['default']:
                raise RollbackError('Unrecognized default output')
            if target not in sinks:raise RollbackError('Route destination disappeared')
            if target not in self.before['sinks']:
                node,props=unique_node(graph,target)
                if stamp(sinks[target],node,props)!=self.before.get('route_targets',{}).get(target):
                    raise RollbackError('Unrelated route destination was replaced')
            args=(*args[:3],str(sinks[target]['index'])) if args[1]=='move-sink-input' else (*args[:2],str(sinks[target]['index']))
        elif link_write:
            desired={tuple(e) for e in self.before['edges'] if e[0]==self.cfg['VIRTUAL_SINK'] or e[2]==self.cfg['VIRTUAL_SINK']}
            incoming={e for e in desired if e[2]==self.cfg['VIRTUAL_SINK']}
            if args[1]=='-d':
                matches=[(a,b) for i,a,b,_ in graph.links if str(i)==args[2]]
                if len(matches)!=1:raise RollbackError('Link identity changed before deletion')
                a,b=matches[0]
            else:
                a,b=map(int,args[1:])
            pa,pb=graph.ports[a],graph.ports[b]
            row=(graph.nodes[int(pa['node.id'])]['node.name'],pa['port.name'],graph.nodes[int(pb['node.id'])]['node.name'],pb['port.name'])
            if args[1]=='-d':
                if (row[0],row[1]) not in {(e[0],e[1]) for e in incoming} or row in incoming:
                    raise RollbackError('Refusing to remove a valid or unrelated link')
            elif row not in desired:
                raise RollbackError('Refusing to create an unexpected route')
        return args

    def graph(self):
        return c.Graph(json.loads(self.run('pw-dump')))

    def capture(self):
        raw=json.loads(self.run('pactl','-f','json','list','sinks'))
        graph=self.graph()
        identity=identify(self.cfg,raw,graph,self.null_modules(),self.expected_policy)
        self.cfg.update(identity['cfg'])
        sinks={s['name']:s for s in raw}
        names={s['index']:n for n,s in sinks.items()}
        inputs=json.loads(self.run('pactl','-f','json','list','sink-inputs'))
        for item in inputs:
            item['restore_sink']=names.get(item['sink'])
        wanted=[self.cfg['LEFT_DEVICE'],self.cfg['RIGHT_DEVICE'],self.cfg['VIRTUAL_SINK'],self.cfg.get('EFFECTS_SINK','easyeffects_sink')]
        default=self.run('pactl','get-default-sink').strip()
        routes={}
        for name in {default}|{i['restore_sink'] for i in inputs if i.get('restore_sink')}:
            if name in wanted:continue
            node,props=unique_node(graph,name)
            routes[name]=stamp(sinks[name],node,props)
        return dict(sinks={n:sinks[n] for n in wanted},inputs=inputs,
                    edges=sorted(edges(self.graph())),default=default,route_targets=routes,
                    hashes=self.hashes,identity=identity)

    def preflight(self):
        if self.cfg['AUTO_DEFAULT']!='false':
            raise RollbackError('Trial must not automatically select default output')
        self.before=self.capture()
        if not all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in self.hashes.items()):
            raise RollbackError('Original hash changed')
        self.watchdog.preflight()
        self.identity=self.before['identity']
        self.old_removal_requested=False
        self.candidate_requested=False
        self.native_stamp=None
        self.restored_module=None
        self.restored_stamp=None
        # A read-only adapter before freeze, reused by return after any failure.
        self.backend=SessionRestore(self.cfg,self.before,self.before,self.run,self.graph,self.watchdog)
        self.backend.media_read=self.media
        self.backend.identity_read=self.assert_identity
        modules=self.backend.modules()
        virtual=self.cfg['VIRTUAL_SINK']
        if len(modules)!=1 or str(self.before['sinks'][virtual]['owner_module'])!=modules[0][0]:
            raise RollbackError('Original null sink not uniquely identified')
        self.old_module=modules[0]
        if str(self.old_module[0])!=self.identity['current']['legacy']['module_id']:
            raise RollbackError('Original module changed during snapshot')
        self.before['legacy']=dict(argument=self.old_module[1])
        self.backend.module=self.old_module
        self.backend.expected={tuple(e) for e in self.before['edges'] if e[0]==virtual or e[2]==virtual}
        if not self.backend.verify()['resources_ok']:
            raise RollbackError('Original baseline cannot be verified')
        # Require exact old split channel fan-out, not an arbitrary named sink.
        graph=self.graph()
        c.require_metadata(graph)
        incoming=[e for e in self.before['edges'] if e[2]==virtual]
        if len(incoming)!=2 or any(e[0]!=self.cfg.get('EFFECTS_OUTPUT_NAME','ee_soe_output_level') for e in incoming):
            raise RollbackError('Expected exclusive stereo EasyEffects input route')
        expected=set()
        for side,channel in [('LEFT','FL'),('RIGHT','FR')]:
            sources=[(n,p) for n,p in graph.ports.items() if graph.nodes[int(p['node.id'])].get('node.name')==virtual and p.get('port.direction')=='out' and p.get('audio.channel')==channel]
            target=graph.named(self.cfg[side+'_DEVICE'])
            if len(sources)!=1 or len(target)!=1:
                raise RollbackError('Original endpoint ambiguous')
            outputs=graph.ports_for(target[0],'in')
            if sorted(p.get('audio.channel') for p in outputs.values())!=['FL','FR']:
                raise RollbackError('Trial requires the confirmed stereo device layout')
            for p in outputs.values():
                expected.add((virtual,sources[0][1]['port.name'],self.cfg[side+'_DEVICE'],p['port.name']))
        if {tuple(e) for e in self.before['edges'] if e[0]==virtual}!=expected:
            raise RollbackError('Original split links differ from the preauthorized layout')
        if self.path and self.history is not None:
            audit=dict(monotonic=time.monotonic(),stable_policy_verified=True,
                       changes=audit_difference(self.history,self.before),
                       current_identity=self.identity['current'],
                       current_watchdog=getattr(self.watchdog,'saved',{}))
            with (self.path/'revalidation-audit.jsonl').open('a') as output:
                output.write(json.dumps(audit)+'\n')

    def freeze(self):
        self.assert_identity()
        self.watchdog.freeze()
        self.assert_identity()
        self.backend.mute()

    def remove_original(self):
        if not self.watchdog.paused() or self.backend.modules()!=[self.old_module]:
            raise RollbackError('Original changed before removal')
        self.run('pactl','unload-module',self.old_module[0])
        deadline=time.monotonic()+5
        while self.graph().named(self.cfg['VIRTUAL_SINK']):
            if time.monotonic()>=deadline:
                raise RollbackError('Original sink removal pending')
            time.sleep(.05)

    def launch(self,path):
        self.candidate_requested=True
        # Candidate-only XDG dirs prevent stale lock/state from earlier trials.
        config=path/'candidate.conf'
        config.write_text('\n'.join(k+'='+json.dumps(v) for k,v in self.cfg.items())+'\n')
        env=os.environ.copy()
        runtime=path/'candidate-runtime'
        runtime.mkdir(mode=0o700,exist_ok=True)
        original_runtime=os.environ['XDG_RUNTIME_DIR']
        env.update(BLUETOOTH_SPLIT_CONFIG=str(config),XDG_STATE_HOME=str(path/'candidate-state'),
                   XDG_RUNTIME_DIR=str(runtime),PIPEWIRE_RUNTIME_DIR=os.environ.get('PIPEWIRE_RUNTIME_DIR',original_runtime),
                   PULSE_SERVER=os.environ.get('PULSE_SERVER','unix:'+original_runtime+'/pulse/native'))
        self.log=(path/'candidate.log').open('w')
        proc=subprocess.Popen([sys.executable,str(ROOT/'bluetooth-split-controller.py'),'watch'],
                              env=env,stdout=self.log,stderr=self.log,start_new_session=True)
        self.log.close()
        return proc

    def ready(self):
        graph=self.graph()
        try:
            state,missing,extra,_=graph.plan(self.cfg)
        except c.SplitError:
            return False
        ids=graph.named(self.cfg['VIRTUAL_SINK'])
        return state=='ROUTED' and not missing and not extra and len(ids)==1 and graph.nodes[ids[0]].get('split.session')==self.cfg['TRIAL_TOKEN']

    def route_candidate(self):
        virtual=self.cfg['VIRTUAL_SINK']
        # Same sources as the captured EE route; remove only their fallback links.
        incoming={tuple(e) for e in self.before['edges'] if e[2]==virtual}
        controlled={(e[0],e[1]) for e in incoming}
        graph=self.graph()
        for link,a,b,_ in graph.links:
            pa,pb=graph.ports[a],graph.ports[b]
            row=(graph.nodes[int(pa['node.id'])]['node.name'],pa['port.name'],graph.nodes[int(pb['node.id'])]['node.name'],pb['port.name'])
            if (row[0],row[1]) in controlled and row not in incoming:
                self.run('pw-link','-d',str(link))
        for source,sp,target,tp in incoming:
            graph=self.graph()
            if (source,sp,target,tp) in edges(graph):continue
            a=[i for n in graph.named(source) for i,p in graph.ports_for(n,'out').items() if p['port.name']==sp]
            b=[i for n in graph.named(target) for i,p in graph.ports_for(n,'in').items() if p['port.name']==tp]
            if len(a)!=1 or len(b)!=1:raise RollbackError('EE route is ambiguous')
            self.run('pw-link',str(a[0]),str(b[0]))
        # Preserve all saved levels; only the candidate virtual is recreated.
        for name,sink in self.before['sinks'].items():
            self.run('pactl','set-sink-volume',name,*[str(v['value']) for v in sink['volume'].values()])
            self.run('pactl','set-sink-mute',name,'1' if sink['mute'] else '0')

    def capture_playback(self):
        sinks=json.loads(self.run('pactl','-f','json','list','sinks'))
        names={s['index']:s['name'] for s in sinks}
        inputs=json.loads(self.run('pactl','-f','json','list','sink-inputs'))
        previous={str(i['properties'].get('object.serial')):i for i in self.before['inputs']}
        for item in inputs:
            item['restore_sink']=names.get(item['sink'])
            saved=previous.get(str(item['properties'].get('object.serial')))
            if saved and saved['restore_sink']==self.cfg['VIRTUAL_SINK']:
                item['restore_sink']=self.cfg['VIRTUAL_SINK']
        rows=sorted(edges(self.graph()))
        # If candidate vanished, recover only the previously identified EE ports;
        # do not turn a spontaneous fallback destination into the desired route.
        virtual=self.cfg['VIRTUAL_SINK']
        if not any(e[2]==virtual for e in rows):
            rows += [e for e in self.before['edges'] if e[2]==virtual]
        self.backend.playback=dict(inputs=inputs,edges=rows)
        self.backend.media_before=self.media()

    def media(self):
        address=os.environ.get('DBUS_SESSION_BUS_ADDRESS')
        if not address:raise RollbackError('No explicit session bus for media verification')
        prefix=['busctl','--address='+address,'--json=short']
        names=json.loads(self.run(*prefix,'call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames'))['data'][0]
        return {name:json.loads(self.run(*prefix,'get-property',name,'/org/mpris/MediaPlayer2','org.mpris.MediaPlayer2.Player','PlaybackStatus'))['data'] for name in names if name.startswith('org.mpris.MediaPlayer2.')}

    def observe(self,path):
        with (path/'observations.jsonl').open('a') as output:
            output.write(json.dumps(dict(monotonic=time.monotonic(),routed=self.ready()))+'\n')


class ServiceWatchdog(WatchdogLease):
    def enable_verified_process(self, script, expected=None):
        self.expected_script=str(Path(script).resolve())
        self.expected_service=expected
        self.current_bound=False

    def effective_state(self):
        state=self.state()
        extra=self.run(*self.prefix,'show',self.unit,'-p','Id','-p','ExecMainPID',
                       '-p','ExecMainStartTimestampMonotonic','-p','ExecStart','-p','ControlGroup')
        state.update(dict(line.split('=',1) for line in extra.splitlines()))
        match=re.search(r'path=([^ ;]+)',state.pop('ExecStart',''))
        state['ExecPath']=match.group(1) if match else ''
        address=os.environ.get('DBUS_SESSION_BUS_ADDRESS')
        if not address:raise RollbackError('No explicit user manager bus')
        rows=json.loads(self.run('busctl','--address='+address,'--json=short','call',
             'org.freedesktop.systemd1','/org/freedesktop/systemd1',
             'org.freedesktop.systemd1.Manager','GetUnitProcesses','s',self.unit))['data'][0]
        actual=[command for group,pid,command in rows
                if str(pid)==state['MainPID'] and group==state.get('ControlGroup')]
        if len(actual)!=1:raise RollbackError('Cannot identify effective watchdog process in its unit')
        state['MainCommandLine']=actual[0]
        argv=shlex.split(actual[0])
        if (state.get('Id')!=self.unit or state.get('ExecMainPID')!=state['MainPID'] or
                not state.get('InvocationID') or int(state.get('MainPID','0'))<=0 or
                int(state.get('ExecMainStartTimestampMonotonic','0'))<=0 or
                state['ExecPath']!=self.expected_script or len(argv)!=2 or
                Path(argv[0]).name not in ('bash','sh') or argv[1]!=self.expected_script):
            raise RollbackError('Unexpected watchdog unit or effective process')
        stable={k:state[k] for k in ('Id','ExecPath','MainCommandLine')}
        if self.expected_service is not None and stable!=self.expected_service:
            raise RollbackError('Watchdog stable identity changed')
        return state

    def preflight(self):
        current=self.effective_state() if hasattr(self,'expected_script') else self.state()
        if hasattr(self,'expected_script') and not self.current_bound:
            self.saved={k:v for k,v in current.items() if k!='FreezerState'}
            self.current_bound=True
        if (any(current.get(k)!=self.saved[k] for k in self.saved) or
                current.get('ActiveState')!='active' or current.get('SubState')!='running' or
                current.get('FreezerState')!='running' or self.request_flag.exists()):
            raise RollbackError('Watchdog baseline changed or resync pending')

    def paused(self):
        if not hasattr(self,'expected_script'):return super().paused()
        current=self.effective_state()
        return all(current.get(k)==v for k,v in self.saved.items()) and current.get('FreezerState')=='frozen'

    def verify_resumed(self):
        if not hasattr(self,'expected_script'):return super().verify_resumed()
        current=self.effective_state()
        return all(current.get(k)==v for k,v in self.saved.items()) and current.get('FreezerState')=='running'

    def freeze(self):
        self.preflight()
        self.run(*self.prefix,'freeze',self.unit)
        if not self.paused():
            raise RollbackError('Freeze not confirmed')


class SessionRestore(PulseRestore):
    identity_read=None
    capture_unknown=False
    media_before=None
    def verify(self):
        result=super().verify()
        if self.identity_read:
            try:
                self.identity_read()
                result['checks']['current_identity']=True
            except Exception as exc:
                result['checks']['current_identity']=False
                result['identity_error']=str(exc)
                result['resources_ok']=False
        if self.capture_unknown:
            result.update(applications_ok=False,playback_capture_unknown=True)
        if self.media_before is not None:
            try:
                current=self.media_read()
            except Exception as exc:
                result.update(applications_ok=False,media_unknown=str(exc))
                return result
            result['media_before']=self.media_before
            result['media_after']=current
            result['applications_ok']=result['applications_ok'] and current==self.media_before
        return result
