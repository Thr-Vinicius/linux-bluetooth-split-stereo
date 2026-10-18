import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import test_controller as fixtures

spec = importlib.util.spec_from_file_location('observer', Path(__file__).resolve().parents[1] / 'tools/observe-session.py')
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)


class ObservationTests(unittest.TestCase):
    def test_other_backend_never_claims_native_health_or_acoustic_measurement(self):
        data = fixtures.fixture()
        data[0]['info']['props'].pop('split.owner')
        calls = []
        def run(*args):
            calls.append(args)
            return '[]' if 'list' in args else 'split_lr'
        with patch.object(o.c, 'snapshot', return_value=o.c.Graph(data)), patch.object(o.c, 'command', side_effect=run):
            result = o.sample(fixtures.CFG)
        self.assertEqual(result['backend'], 'other')
        self.assertEqual(result['state'], 'NOT_EVALUATED')
        self.assertEqual(result['acoustic_sync'], 'unmeasured')
        self.assertEqual(result['audio_continuity'], 'unmeasured')
        self.assertEqual(calls, [('pactl', '-f', 'json', 'list', 'sinks'), ('pactl', 'get-default-sink')])

    def test_interruption_does_not_claim_two_hours_elapsed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            config = path / 'config'
            config.write_text('LEFT_DEVICE="left"\nRIGHT_DEVICE="right"\n')
            output = path / 'observation.jsonl'
            args = ['observer', '--config', str(config), '--output', str(output), '--seconds', '7200']
            with patch.object(o.sys, 'argv', args), patch.object(o, 'sample', side_effect=KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(o.main(), 130)
            summary = json.loads(output.read_text())
            self.assertTrue(summary['interrupted'])
            self.assertFalse(summary['duration_completed'])
            self.assertEqual(summary['native_samples'], 0)
            self.assertLess(summary['elapsed_seconds'], 7200)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            with patch.object(o.sys, 'argv', args):
                with self.assertRaises(FileExistsError):
                    o.main()


if __name__ == '__main__':
    unittest.main()
