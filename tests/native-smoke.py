#!/usr/bin/env python3
"""Real PipeWire graph in a private runtime, no Bluetooth/session services touched."""
import array
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('controller', ROOT / 'bluetooth-split-controller.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


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
    for name, positions in [('test_left', ['FL', 'FR']), ('test_right', ['MONO'])]:
        objects.append({'factory': 'adapter', 'args': {
            'factory.name': 'support.null-audio-sink', 'node.name': name,
            'media.class': 'Audio/Sink', 'audio.position': positions,
            'adapter.auto-port-config': {'mode': 'dsp', 'monitor': True,
                                         'position': 'preserve'}}})
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
    connect('test_left', 'record_left')
    connect('test_right', 'record_right')
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
        cfg = dict(LEFT_DEVICE='test_left', RIGHT_DEVICE='test_right', VIRTUAL_SINK='split_lr',
                   LATENCY_COMPENSATE='true', AUTO_DEFAULT='false', CHECK_INTERVAL='10',
                   ACTION_RETRY_DELAY='1', FALLBACK_SINK='')
        (runtime / 'daemon.conf').write_text(daemon_config())
        (runtime / 'combine.conf').write_text(c.native_config(cfg))
        log = open(runtime / 'log', 'w+')
        try:
            processes.append(subprocess.Popen(['pipewire', '-c', 'daemon.conf'],
                                              stdout=log, stderr=log))
            wait_for(lambda: len(c.snapshot().nodes) >= 3)
            processes.append(subprocess.Popen(['pipewire', '-c', 'combine.conf'],
                                              stdout=log, stderr=log))
            wait_for(lambda: len(c.snapshot().named('split_lr.right')) == 1)
            result = wait_for(lambda: c.reconcile(cfg))
            assert result[0] == 'ROUTED', result
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
            right = graph.named('test_right')[0]
            out = next(iter(graph.ports_for(left, 'out')))
            inp = next(iter(graph.ports_for(right, 'in')))
            c.command('pw-link', str(out), str(inp))
            c.reconcile(cfg)
            assert len(c.snapshot().links) == 3
            print('PASS: native mono/stereo ports, idempotence, lost-link and crosswire recovery')
            check_audio(runtime, processes, log)
            # Manual independent levels and mute survive route recovery.
            for name, volume in [('test_left', '25%'), ('test_right', '35%'), ('split_lr', '20%')]:
                c.command('pactl', 'set-sink-volume', name, volume)
            c.command('pactl', 'set-sink-mute', 'test_left', '1')
            settings = {(name, prop): c.command('pactl', 'get-sink-' + prop, name)
                        for name in ('test_left', 'test_right', 'split_lr') for prop in ('volume', 'mute')}
            graph = c.snapshot()
            owned_link = next(i for i, source, _, _ in graph.links
                              if int(graph.ports[source]['node.id']) == graph.named('split_lr.left')[0])
            c.command('pw-link', '-d', str(owned_link))
            c.reconcile(cfg)
            assert all(c.command('pactl', 'get-sink-' + prop, name) == value
                       for (name, prop), value in settings.items())
            print('PASS: real Pulse manual volumes and mute preserved during link recovery')
            # Stop the direct native client and exercise the actual supervisor.
            c.stop_process(processes[1])
            wait_for(lambda: not c.snapshot().named('split_lr'))
            cfg_file = runtime / 'user.conf'
            cfg_file.write_text('\n'.join(f'{k}="{v}"' for k, v in dict(
                cfg, CHECK_INTERVAL='1', ACTION_RETRY_DELAY='1').items()) + '\n')
            os.environ['BLUETOOTH_SPLIT_CONFIG'] = str(cfg_file)
            def start_watch():
                proc = subprocess.Popen(['python3', str(ROOT / 'bluetooth-split-controller.py'), 'watch'],
                                        stdout=log, stderr=log)
                processes.append(proc)
                return proc
            watch = start_watch()
            wait_for(lambda: healthy(cfg, 'ROUTED'))
            duplicate = subprocess.run(['python3', str(ROOT / 'bluetooth-split-controller.py'), 'watch'],
                                       capture_output=True, text=True, timeout=5)
            assert duplicate.returncode != 0
            assert 'Another controller' in duplicate.stderr
            graph = c.snapshot()
            c.command('pw-cli', 'destroy', str(graph.named('test_right')[0]))
            wait_for(lambda: healthy(cfg, 'PARTIAL'))
            # Recreate a different mono sink object with the same stable name.
            c.command('pw-cli', 'create-node', 'adapter', c.spa({
                'factory.name': 'support.null-audio-sink', 'node.name': 'test_right',
                'media.class': 'Audio/Sink', 'audio.position': ['MONO'], 'object.linger': True,
                'adapter.auto-port-config': {'mode': 'dsp', 'monitor': True, 'position': 'preserve'}}))
            wait_for(lambda: healthy(cfg, 'ROUTED'))
            c.stop_process(watch)
            wait_for(lambda: not c.snapshot().named('split_lr'))
            watch = start_watch()
            wait_for(lambda: healthy(cfg, 'ROUTED'))
            # Simulate the server disappearing under a running supervisor.
            c.stop_process(processes[0])
            processes.append(subprocess.Popen(['pipewire', '-c', 'daemon.conf'], stdout=log, stderr=log))
            wait_for(lambda: healthy(cfg, 'ROUTED'), timeout=12)
            # Destroy only our virtual node; owner must be recreated without Bluetooth.
            old_virtual = c.snapshot().named('split_lr')[0]
            c.command('pw-cli', 'destroy', str(old_virtual))
            wait_for(lambda: healthy(cfg, 'ROUTED'), timeout=12)
            graph = c.snapshot()
            c.command('pw-cli', 'destroy', str(graph.named('split_lr.left')[0]))
            wait_for(lambda: healthy(cfg, 'ROUTED'), timeout=20)
            assert watch.poll() is None
            # Isolated WirePlumber policy only: never load physical monitors.
            if os.environ.get('SPLIT_TEST_WIREPLUMBER'):
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
