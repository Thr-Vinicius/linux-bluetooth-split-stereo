import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('controller', Path(__file__).resolve().parents[1] / 'bluetooth-split-controller.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
CFG = dict(LEFT_DEVICE='left', RIGHT_DEVICE='right', VIRTUAL_SINK='split_lr',
           FALLBACK_SINK='normal', AUTO_DEFAULT='true', LATENCY_COMPENSATE='true',
           CHECK_INTERVAL='10', ACTION_RETRY_DELAY='5')


def node(i, name, owned=False):
    return {'id': i, 'type': 'PipeWire:Interface:Node', 'info': {'props': {
        'node.name': name, 'media.class': 'Audio/Sink',
        **({'split.owner': c.OWNER} if owned else {})}}}


def port(i, n, direction, channel):
    return {'id': i, 'type': 'PipeWire:Interface:Port', 'info': {'props': {
        'node.id': n, 'port.direction': direction, 'audio.channel': channel}}}


def link(i, source, target, state='active'):
    return {'id': i, 'type': 'PipeWire:Interface:Link', 'info': {
        'output-port-id': source, 'input-port-id': target, 'state': state}}


def fixture(left=True, right=True):
    objects = [node(1, 'split_lr', True), port(11, 1, 'in', 'FL'), port(12, 1, 'in', 'FR'),
               node(9, 'normal')]
    if left:
        objects += [node(2, 'left'), node(4, 'split_lr.left', True),
                    port(21, 2, 'in', 'FL'), port(22, 2, 'in', 'FR'),
                    port(41, 4, 'out', 'MONO'), link(101, 41, 21), link(102, 41, 22)]
    if right:
        objects += [node(3, 'right'), node(5, 'split_lr.right', True),
                    port(31, 3, 'in', 'MONO'), port(51, 5, 'out', 'MONO'), link(103, 51, 31)]
    return objects


class RoutingTests(unittest.TestCase):
    def test_presence_matrix_and_noop(self):
        for left, right, state in [(1, 1, 'ROUTED'), (1, 0, 'PARTIAL'),
                                    (0, 1, 'PARTIAL'), (0, 0, 'DISCONNECTED')]:
            with self.subTest(left=left, right=right):
                graph = c.Graph(fixture(left, right))
                calls = []
                self.assertEqual(c.reconcile(CFG, lambda: graph, lambda *a: calls.append(a))[0], state)
                self.assertEqual(calls, [])

    def test_missing_wrong_duplicate_and_foreign_links(self):
        objects = fixture()
        objects = [o for o in objects if o['id'] != 102]
        objects += [link(104, 41, 31), link(105, 41, 21), link(106, 999, 31)]
        state, missing, remove, _ = c.Graph(objects).plan(CFG)
        self.assertEqual(state, 'ROUTED')
        self.assertEqual(missing, {(41, 22)})
        self.assertEqual(remove, [104, 105])
        self.assertNotIn(106, remove)

    def test_lost_link_repaired_only_once(self):
        before = c.Graph([o for o in fixture() if o['id'] != 102])
        reads = iter([before, c.Graph(fixture())])
        calls = []
        c.reconcile(CFG, lambda: next(reads), lambda *a: calls.append(a))
        self.assertEqual(calls, [('pw-link', '41', '22')])

    def test_command_failure_propagates(self):
        graph = c.Graph([o for o in fixture() if o['id'] != 102])
        with self.assertRaises(c.SplitError):
            c.reconcile(CFG, lambda: graph, lambda *a: (_ for _ in ()).throw(c.SplitError('pw-link failed')))

    def test_race_does_not_report_ready(self):
        with self.assertRaises(c.SplitError):
            c.reconcile(CFG, lambda: c.Graph([o for o in fixture() if o['id'] != 102]), lambda *a: None)

    def test_server_or_virtual_disappearance_is_error(self):
        for objects in ([], fixture()[1:]):
            with self.assertRaises(c.SplitError):
                c.Graph(objects).plan(CFG)

    def test_profile_node_id_changes_are_not_sync_evidence(self):
        for shift in (0, 1000, 2000):
            objects = copy.deepcopy(fixture())
            for obj in objects:
                obj['id'] += shift
                props = obj['info'].get('props', {})
                if 'node.id' in props:
                    props['node.id'] += shift
                if 'output-port-id' in obj['info']:
                    obj['info']['output-port-id'] += shift
                    obj['info']['input-port-id'] += shift
            self.assertEqual(c.Graph(objects).plan(CFG)[:3], ('ROUTED', set(), []))

    def test_unsupported_layout_fails_closed(self):
        objects = fixture()
        objects.append(port(23, 2, 'in', 'LFE'))
        with self.assertRaises(c.SplitError):
            c.Graph(objects).plan(CFG)

    def test_ambiguous_and_same_device_rejected(self):
        with self.assertRaises(c.SplitError):
            c.Graph(fixture() + [node(6, 'left')]).plan(CFG)
        with self.assertRaises(c.SplitError):
            c.Graph(fixture()).plan(dict(CFG, RIGHT_DEVICE='left'))

    def test_error_link_replaced(self):
        objects = fixture()
        objects[-1]['info']['state'] = 'error'
        self.assertEqual(c.Graph(objects).plan(CFG)[1:3], ({(51, 31)}, [103]))

    def test_repeated_hotplug(self):
        for _ in range(500):
            for left, right in [(1, 1), (1, 0), (0, 0), (0, 1), (1, 1)]:
                graph = c.Graph(fixture(left, right))
                c.reconcile(CFG, lambda: graph, lambda *a: self.fail('Unexpected mutation'))

    def test_paused_links_are_healthy(self):
        objects = fixture()
        for obj in objects:
            if obj['type'].endswith(':Link'):
                obj['info']['state'] = 'paused'
        self.assertEqual(c.Graph(objects).plan(CFG)[1:3], (set(), []))

    def test_physical_error_not_healthy(self):
        objects = fixture()
        next(o for o in objects if o['id'] == 2)['info']['state'] = 'error'
        with self.assertRaises(c.SplitError):
            c.Graph(objects).plan(CFG)

    def test_negotiating_link_waits_without_churn(self):
        objects = fixture()
        objects[-1]['info']['state'] = 'init'
        with self.assertRaises(c.SplitError):
            c.Graph(objects).plan(CFG)

    def test_missing_native_stream_requests_owner_recovery(self):
        objects = [o for o in fixture() if o['id'] != 4]
        with self.assertRaises(c.OwnerError):
            c.Graph(objects).plan(CFG)



class PolicyTests(unittest.TestCase):
    def test_defaults_volume_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'defaults.json'
            calls = []
            current = ['normal']
            def run(*args):
                calls.append(args)
                if args[1] == 'get-default-sink':
                    return current[0]
                current[0] = args[2]
                return ''
            defaults = c.Defaults(CFG, path, run)
            defaults.update('ROUTED', ['left', 'right'], c.Graph(fixture()))
            self.assertEqual(current[0], 'split_lr')
            calls.clear()
            c.Defaults(CFG, path, run).update('ROUTED', ['left', 'right'], c.Graph(fixture()))
            self.assertEqual(calls, [('pactl', 'get-default-sink')])
            defaults.update('PARTIAL', ['right'], c.Graph(fixture(False, True)))
            self.assertEqual(current[0], 'right')
            defaults.update('DISCONNECTED', [], c.Graph(fixture(False, False)))
            self.assertEqual(current[0], 'normal')
            self.assertFalse(any('volume' in ' '.join(a) or 'move-sink-input' in a for a in calls))

    def test_manual_default_survives_reconciliation_and_hotplug(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            current = ['split_lr']
            def run(*a):
                calls.append(a)
                return current[0]
            defaults = c.Defaults(CFG, Path(temp) / 'defaults.json', run)
            defaults.update('ROUTED', ['left', 'right'], c.Graph(fixture()))
            current[0] = 'normal'
            defaults.update('ROUTED', ['left', 'right'], c.Graph(fixture()))
            defaults.update('PARTIAL', ['left'], c.Graph(fixture(True, False)))
            self.assertFalse(any(a[1] == 'set-default-sink' for a in calls))

    def test_failed_pactl_does_not_save_success(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'defaults.json'
            def run(*args):
                if args[1] == 'set-default-sink':
                    raise c.SplitError('pactl failed')
                return 'normal'
            with self.assertRaises(c.SplitError):
                c.Defaults(CFG, path, run).update('ROUTED', ['left', 'right'], c.Graph(fixture()))
            self.assertFalse(path.exists())

    def test_concurrent_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'lock'
            fd = c.lock(path)
            try:
                with self.assertRaises(c.SplitError):
                    c.lock(path)
            finally:
                os.close(fd)
            os.close(c.lock(path))

    def test_runtime_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / c.OWNER).symlink_to(temp)
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': temp}):
                with self.assertRaises(c.SplitError):
                    c.private_runtime()

    def test_config_is_not_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config'
            path.write_text('LEFT_DEVICE="left"\nRIGHT_DEVICE="right"\n')
            self.assertEqual(c.config(path)['LEFT_DEVICE'], 'left')
            for invalid in ['touch /tmp/never-create-split-test', 'LEFT_DEVICE="$(whoami)"',
                            'LEFT_DEVICE="left"; echo hello']:
                path.write_text(invalid)
                with self.assertRaises(c.SplitError):
                    c.config(path)

    def test_command_deadline_and_nonzero(self):
        for error in (c.subprocess.TimeoutExpired('pactl', 5),
                      c.subprocess.CalledProcessError(1, 'pw-link')):
            with patch.object(c.subprocess, 'run', side_effect=error) as run:
                with self.assertRaises(c.SplitError):
                    c.command('pactl', 'get-default-sink')
                self.assertEqual(run.call_args.kwargs['timeout'], 5)

    def test_native_config_explicit_channel_and_resampler(self):
        text = c.native_config(CFG)
        self.assertIn('"combine.audio.position" = [ "FL" ]', text)
        self.assertIn('"combine.audio.position" = [ "FR" ]', text)
        self.assertIn('"resample.disable" = false', text)
        self.assertNotIn('clock.name', text)
        self.assertNotIn('force-quantum', text)


if __name__ == '__main__':
    unittest.main()
