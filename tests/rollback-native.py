#!/usr/bin/env python3
"""Rollback integration: private PipeWire/Pulse/D-Bus, no host services."""
import hashlib
import array
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load('smoke', ROOT / 'tests/native-smoke.py')
c = smoke.c
t = load('trial', ROOT / 'tools/trial_support.py')


class Watchdog:
    """Models an already-paused original; never calls systemd."""
    def __init__(self):
        self.frozen, self.resumes = True, 0

    def paused(self):
        return self.frozen

    def resume(self):
        self.frozen = False
        self.resumes += 1

    def verify_resumed(self):
        return not self.frozen


def main():
    processes = []
    with tempfile.TemporaryDirectory(prefix='split-return-') as temp:
        runtime = Path(temp)
        (runtime / 'pulse').mkdir()
        os.environ.update(XDG_RUNTIME_DIR=temp, PIPEWIRE_RUNTIME_DIR=temp,
            PIPEWIRE_REMOTE='pipewire-0', PULSE_SERVER='unix:' + temp + '/pulse/native',
            PIPEWIRE_CONFIG_DIR=temp, PIPEWIRE_CONFIG_PREFIX='',
            XDG_CONFIG_HOME=temp + '/config', XDG_STATE_HOME=temp + '/state',
            XDG_DATA_HOME=temp + '/data', XDG_CACHE_HOME=temp + '/cache',
            DBUS_SYSTEM_BUS_ADDRESS='unix:path=' + temp + '/no-system-bus',
            DBUS_SESSION_BUS_ADDRESS='unix:path=' + temp + '/session-bus',
            GIO_USE_VFS='local', SPLIT_TEST_WIREPLUMBER='1')
        os.environ.pop('PIPEWIRE_CONFIG_NAME', None)
        (runtime / 'client.conf').write_text(Path('/usr/share/pipewire/client.conf').read_text())
        # Both endpoints stereo, as on the actual pair; the other smoke test also
        # exercises a MONO endpoint. No Bluetooth device is used here.
        daemon = smoke.daemon_config().replace('"audio.position" = [ "MONO" ]',
                                               '"audio.position" = [ "FL" "FR" ]')
        (runtime / 'daemon.conf').write_text(daemon)
        log = (runtime / 'log').open('w+')
        try:
            for args in [['dbus-daemon', '--session', '--nofork',
                          '--address=' + os.environ['DBUS_SESSION_BUS_ADDRESS']],
                         ['pipewire', '-c', 'daemon.conf']]:
                processes.append(subprocess.Popen(args, stdout=log, stderr=log))
            smoke.wait_for(lambda: len(c.snapshot().nodes) >= 3)
            processes.append(subprocess.Popen(['wireplumber', '-p', 'policy'], stdout=log, stderr=log))
            smoke.wait_for(lambda: any(o['type'].endswith(':Metadata') and
                t.Resources.props(o).get('metadata.name') == 'default'
                for o in c.snapshot().objects.values()))
            real_ee='--easyeffects' in sys.argv
            if real_ee:
                os.environ.update(QT_QPA_PLATFORM='offscreen',QT_QUICK_BACKEND='software',GTK_USE_PORTAL='0',QT_NO_XDG_DESKTOP_PORTAL='1')
                os.environ.pop('DISPLAY',None);os.environ.pop('WAYLAND_DISPLAY',None)
                processes.append(subprocess.Popen(['easyeffects','--hide-window'],stdout=log,stderr=log,start_new_session=True))
                smoke.wait_for(lambda:c.snapshot().named('easyeffects_sink'),timeout=15)
                data=array.array('f',[.1,-.2]*(48000*120))
                (runtime/'audio.raw').write_bytes(data.tobytes())
                processes.append(subprocess.Popen(['pw-cat','--playback','--raw','--format','f32','--channels','2','--target','easyeffects_sink','--properties','{ node.name = fixture_player }',str(runtime/'audio.raw')],stdout=log,stderr=log))
                smoke.wait_for(lambda:c.snapshot().named('ee_soe_output_level'),timeout=15)
            ee_output='ee_soe_output_level' if real_ee else 'easyeffects_sink'
            # An EE stand-in and an independent graph. Real EasyEffects has a
            # separate optional test; no personal preset is loaded here.
            for name in (['independent_source','independent_target'] if real_ee else ['easyeffects_sink','independent_source','independent_target']):
                c.command('pactl', 'load-module', 'module-null-sink',
                          'sink_name=' + name + ' channels=2 channel_map=front-left,front-right')

            def port_ready(name):
                graph = c.snapshot()
                ids = graph.named(name)
                return ids and len(graph.ports_for(ids[0], 'in')) == 2 and len(graph.ports_for(ids[0], 'out')) == 2

            for name in (['independent_source','independent_target'] if real_ee else ['easyeffects_sink','independent_source','independent_target']):
                smoke.wait_for(lambda name=name: port_ready(name))

            def connect(source, target):
                graph = c.snapshot()
                a = graph.ports_for(graph.named(source)[0], 'out')
                b = graph.ports_for(graph.named(target)[0], 'in')
                for i, p in a.items():
                    for j, q in b.items():
                        if p.get('audio.channel') == q.get('audio.channel'):
                            c.command('pw-link', str(i), str(j))

            if '--supervisor' in sys.argv and not real_ee:
                data=array.array('f',[.1,-.2]*(48000*120))
                (runtime/'fixture-player.raw').write_bytes(data.tobytes())
                processes.append(subprocess.Popen(['pw-cat','--playback','--raw','--format','f32','--channels','2','--target','easyeffects_sink',str(runtime/'fixture-player.raw')],stdout=log,stderr=log))
                smoke.wait_for(lambda:bool(json.loads(c.command('pactl','-f','json','list','sink-inputs'))))

            connect('independent_source', 'independent_target')
            graph = c.snapshot()
            independent = {i for i, a, _, _ in graph.links if
                graph.nodes[int(graph.ports[a]['node.id'])]['node.name'] == 'independent_source'}
            argument = 'sink_name=split_lr channels=2 channel_map=front-left,front-right sink_properties=device.description=Trial'
            cfg = dict(LEFT_DEVICE=smoke.LEFT_NODE, RIGHT_DEVICE=smoke.RIGHT_NODE,
                VIRTUAL_SINK='split_lr', LATENCY_COMPENSATE='true', AUTO_DEFAULT='false',
                CHECK_INTERVAL='1', ACTION_RETRY_DELAY='1', FALLBACK_SINK='',
                TRIAL_TOKEN='return_0123456789abcdef')

            def capture():
                sinks = {s['name']: s for s in json.loads(c.command('pactl', '-f', 'json', 'list', 'sinks'))}
                names = {s['index']: n for n, s in sinks.items()}
                inputs = json.loads(c.command('pactl', '-f', 'json', 'list', 'sink-inputs'))
                for item in inputs:
                    item['restore_sink'] = names[item['sink']]
                return dict(sinks={n: sinks[n] for n in [cfg['LEFT_DEVICE'], cfg['RIGHT_DEVICE'],
                    'split_lr', 'easyeffects_sink']}, inputs=inputs,
                    edges=sorted(t.edges(c.snapshot())),
                    default=c.command('pactl', 'get-default-sink').strip(), legacy=dict(argument=argument),
                    hashes={str(runtime / 'client.conf'): hashlib.sha256((runtime / 'client.conf').read_bytes()).hexdigest()})

            scenarios=(['requested','deadline','candidate-failure','swap-failure','return-failure','readiness-timeout','cancelled','requester-exit','signal','command-timeout','return-persistent-failure']
                       if '--supervisor' in sys.argv else ['normal','partial-startup','no-sink'])
            if os.environ.get('SPLIT_E2E_SCENARIO'):scenarios=[os.environ['SPLIT_E2E_SCENARIO']]
            for scenario in scenarios:
                c.command('pactl', 'load-module', 'module-null-sink', argument)
                smoke.wait_for(lambda: port_ready('split_lr'))
                for side, channel in [('LEFT', 'FL'), ('RIGHT', 'FR')]:
                    graph = c.snapshot()
                    source = next(i for i, p in graph.ports_for(graph.named('split_lr')[0], 'out').items()
                                  if p['audio.channel'] == channel)
                    for target in graph.ports_for(graph.named(cfg[side + '_DEVICE'])[0], 'in'):
                        c.command('pw-link', str(source), str(target))
                c.command('pactl','set-default-sink','split_lr')
                smoke.wait_for(lambda:c.snapshot().named(ee_output))
                # Policy may already have connected these ports.
                graph=c.snapshot()
                for i,a,b,_ in list(graph.links):
                    if graph.nodes[int(graph.ports[a]['node.id'])]['node.name']==ee_output:
                        c.command('pw-link','-d',str(i))
                connect(ee_output,'split_lr')
                for name, value in [(cfg['LEFT_DEVICE'], '25%'), (cfg['RIGHT_DEVICE'], '35%'),
                                    ('split_lr', '20%'), ('easyeffects_sink', '30%')]:
                    c.command('pactl', 'set-sink-volume', name, value)
                c.command('pactl', 'set-sink-mute', cfg['LEFT_DEVICE'], '1')
                c.command('pactl', 'set-default-sink', 'split_lr')
                before = capture()
                if '--supervisor' in sys.argv:
                    import session_native
                    session_native.run(runtime,cfg,scenario,c,independent,ee_output)
                    restored=[line.split('\t')[0] for line in c.command('pactl','list','short','modules').splitlines() if '\tmodule-null-sink\tsink_name=split_lr ' in line]
                    assert len(restored)==1
                    c.command('pactl','unload-module',restored[0])
                    smoke.wait_for(lambda:not c.snapshot().named('split_lr'))
                    continue
                old = [line.split('\t')[0] for line in c.command('pactl', 'list', 'short', 'modules').splitlines()
                       if '\tmodule-null-sink\tsink_name=split_lr ' in line]
                assert len(old) == 1
                c.command('pactl', 'unload-module', old[0])
                smoke.wait_for(lambda: not c.snapshot().named('split_lr'))
                if scenario == 'normal':
                    (runtime / 'user.conf').write_text('\n'.join(k + '=' + json.dumps(v) for k, v in cfg.items()) + '\n')
                    env = os.environ.copy()
                    env['BLUETOOTH_SPLIT_CONFIG'] = str(runtime / 'user.conf')
                    args = [sys.executable, str(ROOT / 'bluetooth-split-controller.py'), 'watch']
                elif scenario=='no-sink':
                    env=os.environ.copy()
                    args=[sys.executable,'-c','import time;time.sleep(60)']
                else:
                    (runtime / 'combine.conf').write_text(c.native_config(cfg))
                    env = c.native_environment(cfg, runtime)
                    args = ['pipewire', '-c', 'combine.conf']
                proc = subprocess.Popen(args, env=env, stdout=log, stderr=log, start_new_session=True)
                processes.append(proc)
                group = t.OwnedGroup(proc)
                if scenario!='no-sink':
                    smoke.wait_for(lambda: c.snapshot().named('split_lr'))
                if scenario == 'normal':
                    smoke.wait_for(lambda: smoke.healthy(cfg, 'ROUTED'))
                else:
                    assert not c.snapshot().named('split_lr.left')
                group.refresh()
                resources = t.Resources(cfg['TRIAL_TOKEN'])
                resources.remember(c.snapshot())
                if scenario!='no-sink':
                    assert resources.refs
                    c.command('pactl','set-default-sink','split_lr')
                    smoke.wait_for(lambda:c.snapshot().named(ee_output))
                    # Policy may already have connected these ports.
                    graph=c.snapshot()
                    for i,a,b,_ in list(graph.links):
                        if graph.nodes[int(graph.ports[a]['node.id'])]['node.name']==ee_output:
                            c.command('pw-link','-d',str(i))
                    connect(ee_output,'split_lr')
                    playback=capture()
                    c.command('pactl','set-sink-volume','split_lr','55%')
                else:
                    playback=before
                watchdog = Watchdog()
                injected=[False]
                def checked_run(*args):
                    if scenario=='partial-startup' and args[0]=='pw-link' and len(args)==3 and not injected[0]:
                        injected[0]=True
                        raise c.SplitError('Injected first route creation failure')
                    return c.command(*args)
                backend = t.PulseRestore(cfg, before, playback, checked_run, c.snapshot, watchdog)
                output = runtime / scenario
                output.mkdir(mode=0o700)
                engine = t.ReturnSupervisor(output, group, resources, backend)
                t.request_return(output)
                if scenario=='partial-startup':
                    try:engine.poll(time.monotonic()+60)
                    except c.SplitError:pass
                    else:raise AssertionError('Injected failure was not exercised')
                    assert injected[0] and watchdog.resumes==0
                    assert not json.loads((output/'state.json').read_text())['complete']
                result = engine.poll(time.monotonic() + 60)
                assert result['complete'] and result['resources_ok'] and watchdog.resumes == 1, result
                assert not resources.remaining(c.snapshot()) and not group.alive()
                assert independent <= {i for i, _, _, _ in c.snapshot().links}
                ids = {i for i, _, _, _ in c.snapshot().links}
                assert engine.run()['resources_ok']
                assert watchdog.resumes==1
                assert ids == {i for i, _, _, _ in c.snapshot().links}
                print('PASS: private rollback', scenario,
                      'resources removed before restore; levels/routes/unrelated IDs and retry preserved', flush=True)
                c.command('pactl', 'unload-module', backend.modules()[0][0])
                smoke.wait_for(lambda: not c.snapshot().named('split_lr'))
        finally:
            for proc in reversed(processes):
                c.stop_process(proc)
            if sys.exc_info()[0]:
                log.seek(0)
                print(log.read())
            log.close()


if __name__ == '__main__':
    main()
