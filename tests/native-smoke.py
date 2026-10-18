#!/usr/bin/env python3
"""Real PipeWire graph in a private runtime, no Bluetooth/session services touched."""
import array
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controller', ROOT / 'bluetooth-split-controller.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

LEFT_NODE = 'bluez_output.AA_BB_CC_DD_EE_01.1' if os.environ.get('SPLIT_TEST_MAC_TARGETS') else 'test_left'
RIGHT_NODE = 'bluez_output.AA_BB_CC_DD_EE_02.1' if os.environ.get('SPLIT_TEST_MAC_TARGETS') else 'test_right'


def wait_for(test, timeout=8):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            value = test()
            if value:
                return value
        except (c.SplitError, AssertionError) as exc:
            error = exc
        time.sleep(0.1)
    raise AssertionError(f'Timed out: {error}')


def daemon_config():
    modules = ['protocol-native', 'spa-node-factory', 'client-node', 'adapter',
               'link-factory', 'metadata', 'access', 'protocol-pulse']
    objects = [{'factory': 'spa-node-factory', 'args': {
        'factory.name': 'support.node.driver', 'node.name': 'Dummy-Driver',
        'node.group': 'pipewire.dummy', 'priority.driver': 20000}}]
    for name, positions in [(LEFT_NODE, ['FL', 'FR']), (RIGHT_NODE, ['MONO'])]:
        objects.append({'factory': 'adapter', 'args': {
            'factory.name': 'support.null-audio-sink', 'node.name': name,
            'media.class': 'Audio/Sink', 'audio.position': positions,
            'adapter.auto-port-config': {'mode': 'dsp', 'monitor': True,
                                         'position': 'preserve'}}})
    if not os.environ.get('SPLIT_TEST_WIREPLUMBER'):
        # WirePlumber owns this store in policy tests; never create a duplicate.
        objects.append({'factory': 'metadata', 'args': {
            'metadata.name': 'default',
            'metadata.values': [{'key': 'test.fixture', 'value': 'ready'}]}})
    return c.spa({'pulse.properties': {'server.address': ['unix:' + os.environ['XDG_RUNTIME_DIR'] + '/pulse/native']},
                       'context.properties': {'core.daemon': True, 'core.name': 'pipewire-0'},
                       'context.spa-libs': {'audio.convert.*': 'audioconvert/libspa-audioconvert',
                                            'support.*': 'support/libspa-support'},
                       'context.modules': [{'name': 'libpipewire-module-' + m} for m in modules],
                       'context.objects': objects})


def healthy(cfg, expected):
    state, missing, extra, _ = c.snapshot().plan(cfg)
    return state == expected and not missing and not extra


def check_audio(runtime, processes, log):
    source = runtime / 'signal.raw'
    duration = min(120, max(1.5, float(os.environ.get('SPLIT_AUDIO_SECONDS', '1.5'))))
    samples = array.array('f', [0.25, -0.5] * (48000 * int(duration + 3)))
    source.write_bytes(samples.tobytes())
    for name, channels in [('record_left', 2), ('record_right', 1)]:
        output = open(runtime / (name + '.raw'), 'wb')
        proc = subprocess.Popen(['pw-cat', '--record', '--raw', '--format', 'f32',
                                 '--channels', str(channels), '--target', '0',
                                 '--properties', c.spa({'node.name': name,
                                 'adapter.auto-port-config': {'mode': 'dsp'}}), '-'],
                                stdout=output, stderr=log)
        output.close()
        processes.append(proc)
    processes.append(subprocess.Popen(['pw-cat', '--playback', '--raw', '--format', 'f32',
                         '--channels', '2', '--target', '0', '--properties',
                         c.spa({'node.name': 'test_player',
                                'adapter.auto-port-config': {'mode': 'dsp'}}), str(source)],
                         stdout=log, stderr=log))
    wait_for(lambda: c.snapshot().named('test_player') and
             c.snapshot().named('record_left') and c.snapshot().named('record_right'))
    graph = c.snapshot()
    def connect(source_name, target_name):
        source_id = graph.named(source_name)[0]
        target_id = graph.named(target_name)[0]
        outputs = graph.ports_for(source_id, 'out')
        inputs = graph.ports_for(target_id, 'in')
        assert outputs and inputs, (source_name, target_name, graph.ports)
        for out_id, props in outputs.items():
            for in_id, target_props in inputs.items():
                if props.get('audio.channel') == target_props.get('audio.channel'):
                    c.command('pw-link', str(out_id), str(in_id))
    connect(LEFT_NODE, 'record_left')
    connect(RIGHT_NODE, 'record_right')
    connect('test_player', 'split_lr')
    time.sleep(duration)
    for proc in processes[-3:]:
        c.stop_process(proc)
    for side, sign in [('left', 1), ('right', -1)]:
        data = array.array('f')
        data.frombytes((runtime / ('record_' + side + '.raw')).read_bytes())
        nonzero = [v for v in data if abs(v) > 0.0001]
        assert len(nonzero) > 10000, (side, len(data), len(nonzero))
        assert all(v * sign > 0 for v in nonzero), (side, min(nonzero), max(nonzero))
        expected = 0.016 if side == 'left' else 0.032
        measured = sorted(abs(v) for v in nonzero)[len(nonzero) // 2]
        assert abs(measured - expected) < 0.0005, (side, measured, expected)
    print('PASS: recorded samples contain only the selected left/right input channel')


def main():
    processes = []
    with tempfile.TemporaryDirectory(prefix='split-native-') as temp:
        runtime = Path(temp)
        (runtime / 'pulse').mkdir()
        os.environ['XDG_RUNTIME_DIR'] = temp
        os.environ['PIPEWIRE_RUNTIME_DIR'] = temp
        os.environ['PIPEWIRE_REMOTE'] = 'pipewire-0'
        os.environ['PULSE_SERVER'] = 'unix:' + temp + '/pulse/native'
        # No real session bus or configuration fragments are used.
        os.environ['PIPEWIRE_CONFIG_DIR'] = temp
        os.environ['PIPEWIRE_CONFIG_PREFIX'] = ''
        os.environ['XDG_CONFIG_HOME'] = temp + '/config'
        os.environ['XDG_STATE_HOME'] = temp + '/state'
        os.environ['XDG_DATA_HOME'] = temp + '/data'
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = 'unix:path=' + temp + '/no-system-bus'
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + temp + '/no-session-bus'
        os.environ['GIO_USE_VFS'] = 'local'
        os.environ.pop('PIPEWIRE_CONFIG_NAME', None)
        (runtime / 'client.conf').write_text(Path('/usr/share/pipewire/client.conf').read_text())
        cfg = dict(LEFT_DEVICE=LEFT_NODE, RIGHT_DEVICE=RIGHT_NODE, VIRTUAL_SINK='split_lr',
                   LATENCY_COMPENSATE='true', AUTO_DEFAULT='false', CHECK_INTERVAL='10',
                   ACTION_RETRY_DELAY='1', FALLBACK_SINK='')
        if os.environ.get('SPLIT_TEST_MAC_TARGETS'):
            cfg.update(LEFT_MAC='AA:BB:CC:DD:EE:01', RIGHT_MAC='AA:BB:CC:DD:EE:02')
        (runtime / 'daemon.conf').write_text(daemon_config())
        (runtime / 'combine.conf').write_text(c.native_config(cfg))
        log = open(runtime / 'log', 'w+')
        try:
            daemon = subprocess.Popen(['pipewire', '-c', 'daemon.conf'], stdout=log, stderr=log)
            processes.append(daemon)
            wait_for(lambda: len(c.snapshot().nodes) >= 3)
            early_policy = None
            if os.environ.get('SPLIT_TEST_WIREPLUMBER'):
                address = 'unix:path=' + temp + '/early-session-bus'
                processes.append(subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--address=' + address], stdout=log, stderr=log))
                os.environ['DBUS_SESSION_BUS_ADDRESS'] = address
                early_policy = subprocess.Popen(['wireplumber', '-p', 'policy'], stdout=log, stderr=log)
                processes.append(early_policy)
                time.sleep(1)
                assert early_policy.poll() is None
            direct = subprocess.Popen(['pipewire', '-c', 'combine.conf'], stdout=log, stderr=log)
            processes.append(direct)
            wait_for(lambda: len(c.snapshot().named('split_lr')) == 1)
            requests = c.NativeStreams(cfg)
            initial = c.snapshot()
            virtual = initial.named('split_lr')[0]
            assert not initial.named('split_lr.left') and not initial.named('split_lr.right')
            try:
                initial.plan(cfg)
            except c.OwnerError:
                pass
            else:
                raise AssertionError('Missing native streams were reported ready')
            # Delay discovery of one target without changing the real fixture.
            def only_left():
                graph = c.snapshot()
                right = graph.named(RIGHT_NODE)[0]
                requests.update(c.Graph([o for i, o in graph.objects.items() if i != right]))
                return c.snapshot().named('split_lr.left')
            left = wait_for(only_left)[0]
            assert not c.snapshot().named('split_lr.right')
            def initial_route():
                requests.update(c.snapshot())
                return c.reconcile(cfg)
            result = wait_for(initial_route)
            assert result[0] == 'ROUTED', result
            assert c.snapshot().named('split_lr') == [virtual]
            assert c.snapshot().named('split_lr.left') == [left]
            print('PASS: initially absent/delayed children become ready without replacing virtual or earlier child')
            before = c.snapshot()
            links_before = before.links
            for _ in range(10):
                assert c.reconcile(cfg)[0] == 'ROUTED'
            assert c.snapshot().links == links_before, 'Healthy links were recreated'
            assert len(links_before) == 3, links_before
            c.command('pw-link', '-d', str(links_before[0][0]))
            wait_for(lambda: c.reconcile(cfg))
            assert len(c.snapshot().links) == 3
            # Crosswire an owned stream and verify selective removal.
            graph = c.snapshot()
            left = graph.named('split_lr.left')[0]
            right = graph.named(RIGHT_NODE)[0]
            out = next(iter(graph.ports_for(left, 'out')))
            inp = next(iter(graph.ports_for(right, 'in')))
            c.command('pw-link', str(out), str(inp))
            c.reconcile(cfg)
            assert len(c.snapshot().links) == 3
            print('PASS: native mono/stereo ports, idempotence, lost-link and crosswire recovery')
            check_audio(runtime, processes, log)
            # Manual independent levels and mute survive route recovery.
            for name, volume in [(LEFT_NODE, '25%'), (RIGHT_NODE, '35%'), ('split_lr', '20%')]:
                c.command('pactl', 'set-sink-volume', name, volume)
            c.command('pactl', 'set-sink-mute', LEFT_NODE, '1')
            settings = {(name, prop): c.command('pactl', 'get-sink-' + prop, name)
                        for name in (LEFT_NODE, RIGHT_NODE, 'split_lr') for prop in ('volume', 'mute')}
            graph = c.snapshot()
            owned_link = next(i for i, source, _, _ in graph.links
                              if int(graph.ports[source]['node.id']) == graph.named('split_lr.left')[0])
            c.command('pw-link', '-d', str(owned_link))
            c.reconcile(cfg)
            assert all(c.command('pactl', 'get-sink-' + prop, name) == value
                       for (name, prop), value in settings.items())
            print('PASS: real Pulse manual volumes and mute preserved during link recovery')
            # Stop the direct native client and exercise the actual supervisor.
            c.stop_process(direct)
            wait_for(lambda: not c.snapshot().named('split_lr'))
            cfg_file = runtime / 'user.conf'
            cfg_file.write_text('\n'.join(f'{k}="{v}"' for k, v in dict(
                cfg, CHECK_INTERVAL='1', ACTION_RETRY_DELAY='1').items()) + '\n')
            os.environ['BLUETOOTH_SPLIT_CONFIG'] = str(cfg_file)
            if os.environ.get('SPLIT_TEST_STARTUP_DELAY'):
                wrapper = runtime / 'bin'
                wrapper.mkdir()
                real_pipewire = shutil.which('pipewire')
                (wrapper / 'pipewire').write_text('#!/bin/sh\nsleep 2\nexec ' + real_pipewire + ' "$@"\n')
                (wrapper / 'pipewire').chmod(0o700)
                os.environ['PATH'] = str(wrapper) + os.pathsep + os.environ['PATH']
            def start_watch():
                proc = subprocess.Popen(['python3', str(ROOT / 'bluetooth-split-controller.py'), 'watch'],
                                        stdout=log, stderr=log)
                processes.append(proc)
                return proc
            watch = start_watch()
            wait_for(lambda: healthy(cfg, 'ROUTED'))
            flag = runtime / f'fones-watchdog-resync-request-{os.getuid()}.flag'
            graph = c.snapshot()
            c.command('pw-link', '-d', str(graph.links[0][0]))
            flag.touch()
            wait_for(lambda: healthy(cfg, 'ROUTED') and not flag.exists())
            print('PASS: legacy resolver request acknowledged after verified graph repair')
            duplicate = subprocess.run(['python3', str(ROOT / 'bluetooth-split-controller.py'), 'watch'],
                                       capture_output=True, text=True, timeout=5)
            assert duplicate.returncode != 0
            assert 'Another controller' in duplicate.stderr
            graph = c.snapshot()
            c.command('pw-cli', 'destroy', str(graph.named(RIGHT_NODE)[0]))
            wait_for(lambda: healthy(cfg, 'PARTIAL'))
            # Recreate a different mono sink object with the same stable name.
            c.command('pw-cli', 'create-node', 'adapter', c.spa({
                'factory.name': 'support.null-audio-sink', 'node.name': RIGHT_NODE,
                'media.class': 'Audio/Sink', 'audio.position': ['MONO'], 'object.linger': True,
                'adapter.auto-port-config': {'mode': 'dsp', 'monitor': True, 'position': 'preserve'}}))
            wait_for(lambda: healthy(cfg, 'ROUTED'))
            c.stop_process(watch)
            wait_for(lambda: not c.snapshot().named('split_lr'))
            watch = start_watch()
            wait_for(lambda: healthy(cfg, 'ROUTED'))
            # Simulate the server disappearing under a running supervisor.
            c.stop_process(daemon)
            processes.append(subprocess.Popen(['pipewire', '-c', 'daemon.conf'], stdout=log, stderr=log))
            if early_policy is not None:
                # The real user unit restarts WP after server loss; emulate that
                # lifecycle explicitly in this private server, not on the host.
                c.stop_process(early_policy)
                wait_for(lambda: len(c.snapshot().nodes) >= 3)
                early_policy = subprocess.Popen(['wireplumber', '-p', 'policy'], stdout=log, stderr=log)
                processes.append(early_policy)
            wait_for(lambda: healthy(cfg, 'ROUTED'), timeout=12)
            # Destroy only our virtual node; owner must be recreated without Bluetooth.
            old_virtual = c.snapshot().named('split_lr')[0]
            c.command('pw-cli', 'destroy', str(old_virtual))
            wait_for(lambda: healthy(cfg, 'ROUTED'), timeout=12)
            for name, volume in [(LEFT_NODE, '25%'), (RIGHT_NODE, '35%'), ('split_lr', '20%')]:
                c.command('pactl', 'set-sink-volume', name, volume)
            c.command('pactl', 'set-sink-mute', LEFT_NODE, '1')
            settings = {(name, prop): c.command('pactl', 'get-sink-' + prop, name)
                        for name in (LEFT_NODE, RIGHT_NODE, 'split_lr') for prop in ('volume', 'mute')}
            graph = c.snapshot()
            virtual_id = graph.named('split_lr')[0]
            right_node = graph.named('split_lr.right')[0]
            right_links = {i for i,a,_,_ in graph.links if int(graph.ports[a]['node.id']) == right_node}
            c.command('pw-cli', 'destroy', str(graph.named('split_lr.left')[0]))
            wait_for(lambda: healthy(cfg, 'ROUTED'), timeout=8)
            after = c.snapshot()
            assert after.named('split_lr') == [virtual_id], 'Child recovery replaced the virtual sink'
            assert after.named('split_lr.right') == [right_node], 'Child recovery replaced the healthy side'
            assert right_links <= {i for i,_,_,_ in after.links}, 'Healthy-side links changed'
            assert all(c.command('pactl', 'get-sink-' + prop, name) == value
                       for (name, prop), value in settings.items()), 'Child recovery changed levels/mute'
            print('PASS: missing child recovered without replacing virtual/healthy side or changing levels/mute')
            assert watch.poll() is None
            # Isolated WirePlumber policy only: never load physical monitors.
            if os.environ.get('SPLIT_TEST_WIREPLUMBER'):
                c.stop_process(early_policy)
                address = 'unix:path=' + temp + '/session-bus'
                bus = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--address=' + address],
                                       stdout=log, stderr=log)
                processes.append(bus)
                os.environ['DBUS_SESSION_BUS_ADDRESS'] = address
                def start_policy():
                    proc = subprocess.Popen(['wireplumber', '-p', 'policy'], stdout=log, stderr=log)
                    processes.append(proc)
                    time.sleep(1)
                    assert proc.poll() is None, 'WirePlumber policy did not start'
                    return proc
                policy = start_policy()
                wait_for(lambda: healthy(cfg, 'ROUTED'))
                c.stop_process(policy)
                policy = start_policy()
                wait_for(lambda: healthy(cfg, 'ROUTED'))
                print('PASS: isolated WirePlumber policy restart preserves correct owned routes')
            print('PASS: supervisor exclusion, hotplug, watchdog/server restart and native-node recovery')
        finally:
            for proc in reversed(processes):
                c.stop_process(proc)
            log.seek(0)
            if os.environ.get('SPLIT_TEST_LOG') or __import__('sys').exc_info()[0]:
                print(log.read())
            log.close()


if __name__ == '__main__':
    main()
