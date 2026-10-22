import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import fcntl
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import trial_session as s


class SessionTests(unittest.TestCase):
    def test_invalid_duration_cannot_arm(self):
        for maximum,returned,ready in [(601,360,30),(600,600,30),(600,20,30),(0,0,0)]:
            with self.assertRaises(ValueError):s.Session('/unused',None,maximum,returned,ready)

    def test_missing_virtual_is_pending_readiness(self):
        adapter=s.AudioAdapter({'VIRTUAL_SINK':'split_lr'},None,{})
        adapter.graph=lambda:s.c.Graph([])
        self.assertFalse(adapter.ready())

    def test_cancelled_owner_has_no_audio_writes_and_complete_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'return.request').touch()
            adapter=Mock();adapter.cfg={'TRIAL_TOKEN':'trial_0123456789abcdef'};adapter.before={}
            result=s.Session(path,adapter).run()
            adapter.preflight.assert_called_once()
            adapter.freeze.assert_not_called();adapter.launch.assert_not_called()
            self.assertTrue(result['complete'])
            self.assertTrue(json.loads((path/'state.json').read_text())['complete'])

    def test_service_restart_identity_refuses_freeze(self):
        lease=s.ServiceWatchdog(Mock(),['systemctl'],'fixture.service',{'InvocationID':'before'},Path('/not-present-fixture'))
        lease.state=lambda:{'InvocationID':'after','FreezerState':'running'}
        with self.assertRaises(s.RollbackError):lease.freeze()
        lease.run.assert_not_called()

    def test_temporary_ee_fallback_is_not_required_as_unrelated_route(self):
        cfg=dict(LEFT_DEVICE='left',RIGHT_DEVICE='right',VIRTUAL_SINK='split_lr')
        desired=('ee','out_FL','split_lr','playback_FL')
        foreign=('foreign','out_FL','other','in_FL')
        fallback=('ee','out_FL','left','playback_FL')
        backend=s.PulseRestore(cfg,{'sinks':{}},{'edges':[fallback,foreign]},None,lambda:None,None)
        backend.expected={desired}
        from unittest.mock import patch
        with patch('trial_support.edges',return_value={desired,foreign}):self.assertTrue(backend.routes_match())
        with patch('trial_support.edges',return_value={desired}):self.assertFalse(backend.routes_match())

    def test_owner_lock_rejects_a_second_supervisor_before_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);adapter=Mock();adapter.cfg={'TRIAL_TOKEN':'trial_0123456789abcdef'}
            with (path/'owner.lock').open('w') as owner:
                fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):s.Session(path,adapter).run()
            adapter.preflight.assert_not_called()

    def test_start_request_requires_a_fresh_owner_heartbeat(self):
        spec=importlib.util.spec_from_file_location('runner',ROOT/'tools/trial-supervisor.py')
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'state.json').write_text(json.dumps({'phase':'ARMED'}))
            (path/'heartbeat.json').write_text(json.dumps({'monotonic':time.monotonic()-10}))
            from unittest.mock import patch
            args=['trial-supervisor.py','--request-start','--session',str(path)]
            with patch.object(sys,'argv',args):
                with self.assertRaises(RuntimeError):runner.main()
            self.assertFalse((path/'start.request').exists())
            (path/'heartbeat.json').write_text(json.dumps({'monotonic':time.monotonic()}))
            with patch.object(sys,'argv',args):runner.main()
            self.assertTrue((path/'start.request').exists())

    def test_unknown_media_is_explicit_application_limit(self):
        backend=s.SessionRestore(dict(LEFT_DEVICE='left',RIGHT_DEVICE='right',VIRTUAL_SINK='split_lr'), {'sinks':{}}, {},None,None,None)
        backend.media_before={'fixture':'Playing'}
        backend.media_read=Mock(side_effect=RuntimeError('bus lost'))
        from unittest.mock import patch
        with patch.object(s.PulseRestore,'verify',return_value={'resources_ok':True,'applications_ok':True}):
            result=backend.verify()
        self.assertTrue(result['resources_ok']);self.assertFalse(result['applications_ok'])
        self.assertIn('media_unknown',result)


if __name__=='__main__':unittest.main()
