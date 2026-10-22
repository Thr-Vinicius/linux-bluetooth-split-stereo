import copy
import importlib.util
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('trial',ROOT/'tools/trial_support.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
spec=importlib.util.spec_from_file_location('controller',ROOT/'bluetooth-split-controller.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
TOKEN='trial_0123456789abcdef'


def owned_graph(serial=44):
    return c.Graph([
        {'id':1,'type':'PipeWire:Interface:Node','info':{'props':{'node.name':'split_lr','split.session':TOKEN,'client.id':2,'object.serial':serial}}},
        {'id':2,'type':'PipeWire:Interface:Client','info':{'props':{'object.serial':45}}},
        {'id':3,'type':'PipeWire:Interface:Port','info':{'props':{'node.id':1,'port.direction':'in','object.serial':46}}},
    ])


class Group:
    def __init__(self):self.stopped=False
    def assert_context(self):pass
    def stop(self):self.stopped=True
    def alive(self):return not self.stopped


class Backend:
    def __init__(self, group, delay=0):
        self.group=group;self.delay=delay;self.calls=[];self.valid=True;self.apps=True;self.resumed=True
    def graph(self):
        if not self.group.stopped:return owned_graph()
        if self.delay:
            self.delay-=1;return owned_graph()
        return c.Graph([])
    def mute(self):self.calls.append('mute')
    def restore(self):self.calls.append('restore')
    def verify(self):return dict(resources_ok=self.valid,applications_ok=self.apps)
    def resume(self):self.calls.append('resume')
    def verify_resumed(self):return self.resumed


class ReturnTests(unittest.TestCase):
    def setup_engine(self,path,delay=0):
        os.chmod(path,0o700);group=Group();backend=Backend(group,delay)
        return t.ReturnSupervisor(Path(path),group,t.Resources(TOKEN),backend,timeout=.05),backend

    def test_normal_return_orders_restore_before_resume_and_verifies(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path);result=engine.run()
            self.assertTrue(result['complete']);self.assertEqual(b.calls,['mute','restore','resume'])
            self.assertEqual(json.loads((Path(path)/'state.json').read_text())['phase'],'RESTORED')

    def test_repeat_return_is_read_only_when_state_remains_valid(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path);engine.run();calls=list(b.calls)
            engine.run();self.assertEqual(b.calls,calls)

    def test_async_removal_waits_without_recreating_or_resuming_early(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path,delay=2);engine.timeout=1
            def delay(_):self.assertEqual(b.calls,['mute'])
            engine.sleep=delay;self.assertTrue(engine.run()['complete'])

    def test_timeout_never_thaws_or_claims_completion_and_retry_recovers(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path,delay=1000);engine.timeout=0
            with self.assertRaises(t.RollbackError):engine.run()
            self.assertEqual(b.calls,['mute']);self.assertFalse(json.loads((Path(path)/'state.json').read_text())['complete'])
            b.delay=0;self.assertTrue(engine.run()['complete'])

    def test_failed_restore_does_not_resume_and_retry_is_possible(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path);b.valid=False
            with self.assertRaises(t.RollbackError):engine.run()
            self.assertNotIn('resume',b.calls);b.valid=True;self.assertTrue(engine.run()['complete'])

    def test_failed_thaw_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path);b.resumed=False
            with self.assertRaises(t.RollbackError):engine.run()
            self.assertEqual(json.loads((Path(path)/'state.json').read_text())['phase'],'FAILED')

    def test_cross_context_refused_before_audio_writes(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path)
            def fail():raise t.ContextMismatch('different namespace')
            engine.group.assert_context=fail
            with self.assertRaises(t.ContextMismatch):engine.run()
            self.assertEqual(b.calls,[])

    def test_recreated_application_is_reported_as_limit(self):
        with tempfile.TemporaryDirectory() as path:
            engine,b=self.setup_engine(path);b.apps=False
            self.assertEqual(engine.run()['phase'],'RESTORED_WITH_APP_LIMIT')

    def test_file_request_performs_no_signalling(self):
        with tempfile.TemporaryDirectory() as path,patch.object(t.os,'killpg') as kill:
            os.chmod(path,0o700);t.request_return(path)
            self.assertTrue((Path(path)/'return.request').exists());kill.assert_not_called()
            engine,b=self.setup_engine(path);self.assertTrue(engine.poll(time.monotonic()+100)['complete'])

    def test_resources_include_client_after_node_disappears_and_ignore_reused_ids(self):
        resources=t.Resources(TOKEN);resources.remember(owned_graph())
        client=c.Graph([owned_graph().objects[2]])
        self.assertEqual(resources.remaining(client),[(2,'45')])
        foreign=copy.deepcopy(owned_graph().objects[2]);foreign['info']['props']['object.serial']=999
        self.assertEqual(resources.remaining(c.Graph([foreign])),[])

    def test_resources_reject_unqualified_identity(self):
        g=owned_graph();del g.objects[2]['info']['props']['object.serial']
        with self.assertRaises(t.RollbackError):t.Resources(TOKEN).remember(g)

    def test_no_internal_streams_in_application_comparison(self):
        app=dict(properties={'object.serial':'50'},restore_sink='ee',mute=False,corked=False)
        child=dict(properties={'object.serial':'51','split.owner':c.OWNER})
        self.assertEqual(t.application_comparison([app,child],[app],c.OWNER),[dict(serial='50',same_stream=True,state_matches=True)])
        self.assertFalse(t.application_comparison([app],[],c.OWNER)[0]['same_stream'])

    def test_trial_token_is_optional_and_does_not_change_audio_options(self):
        with tempfile.TemporaryDirectory() as path:
            p=Path(path)/'config';p.write_text('LEFT_DEVICE="left"\nRIGHT_DEVICE="right"\n')
            cfg=c.config(p);original=c.native_config(cfg);cfg['TRIAL_TOKEN']=TOKEN
            text=c.native_config(cfg);self.assertIn('"split.session" = "'+TOKEN+'"',text)
            calls=[];manager=c.NativeStreams(cfg,lambda *a:calls.append(a))
            graph=c.Graph([{'id':1,'type':'PipeWire:Interface:Node','info':{'props':{'node.name':'split_lr','split.owner':c.OWNER}}},
              {'id':2,'type':'PipeWire:Interface:Node','info':{'props':{'node.name':'left','media.class':'Audio/Sink','object.serial':88}}},
              {'id':3,'type':'PipeWire:Interface:Metadata','props':{'metadata.name':'default'}}])
            manager.update(graph);self.assertIn('"split.session" = "'+TOKEN+'"',calls[0][-2])
            self.assertNotIn('split.session',original)
            p.write_text(p.read_text()+'TRIAL_TOKEN="bad"\n')
            with self.assertRaises(c.SplitError):c.config(p)


class PulseIdentityTests(unittest.TestCase):
    def test_foreign_virtual_is_rejected_before_any_volume_write(self):
        cfg=dict(LEFT_DEVICE='left',RIGHT_DEVICE='right',VIRTUAL_SINK='split_lr',TRIAL_TOKEN=TOKEN)
        sinks={name:dict(index=i,properties={'object.serial':str(i)}) for i,name in enumerate(['left','right','split_lr'])}
        baseline=dict(sinks=sinks,legacy={'argument':'sink_name=split_lr'})
        calls=[]
        graph=c.Graph([{'id':1,'type':'PipeWire:Interface:Node','info':{'props':{'node.name':'split_lr','split.owner':'foreign'}}}])
        backend=t.PulseRestore(cfg,baseline,{},lambda *a:calls.append(a),lambda:graph,None)
        backend.sinks=lambda:sinks
        backend.modules=lambda:[]
        backend.watchdog=type('Lease',(),{'paused':lambda self:True})()
        with self.assertRaises(t.RollbackError):backend.mute()
        self.assertEqual(calls,[])

    def test_same_pulse_index_with_different_serial_changes_identity(self):
        cfg=dict(LEFT_DEVICE='left',RIGHT_DEVICE='right',VIRTUAL_SINK='split_lr')
        before={n:dict(index=i,properties={'object.serial':str(i)}) for i,n in enumerate(['left','right'])}
        backend=t.PulseRestore(cfg,{'sinks':before},{},None,None,None)
        after=copy.deepcopy(before);after['left']['properties']['object.serial']='999'
        self.assertNotEqual(backend.signature(before),backend.signature(after))


class WatchdogTests(unittest.TestCase):
    def test_resume_only_same_paused_process_and_verify_again(self):
        with tempfile.TemporaryDirectory() as path:
            saved=dict(MainPID='123',ActiveState='active',SubState='running',UnitFileState='enabled')
            state=dict(saved,FreezerState='frozen');calls=[]
            def run(*args):
                calls.append(args)
                if 'thaw' in args:state['FreezerState']='running';return ''
                return '\n'.join(k+'='+v for k,v in state.items())
            lease=t.WatchdogLease(run,['systemctl','--user'],'fixture.service',saved,Path(path)/'request')
            self.assertTrue(lease.paused());lease.resume();self.assertTrue(lease.verify_resumed())
            state['MainPID']='999';self.assertFalse(lease.verify_resumed())

    def test_pending_request_never_thaws_original(self):
        with tempfile.TemporaryDirectory() as path:
            flag=Path(path)/'request';flag.touch();calls=[]
            lease=t.WatchdogLease(lambda *args:calls.append(args),['systemctl'],'fixture.service',{},flag)
            with self.assertRaises(t.RollbackError):lease.resume()
            self.assertEqual(calls,[])


class ProcessTests(unittest.TestCase):
    def test_owned_group_stops_child_and_parent_in_original_context(self):
        with tempfile.TemporaryDirectory() as path:
            child=Path(path)/'child'
            code='import subprocess,time,pathlib; p=subprocess.Popen(["sleep","60"]); pathlib.Path('+repr(str(child))+').write_text(str(p.pid)); time.sleep(60)'
            proc=subprocess.Popen([sys.executable,'-c',code],start_new_session=True)
            try:
                deadline=time.monotonic()+3
                while not child.exists() and time.monotonic()<deadline:time.sleep(.01)
                group=t.OwnedGroup(proc);group.refresh();self.assertGreaterEqual(len(group.members),2)
                group.stop();self.assertFalse(group.alive());proc.wait(timeout=2)
            finally:
                if proc.poll() is None:os.killpg(proc.pid,signal.SIGKILL);proc.wait()

    def test_context_mismatch_never_signals_a_pid(self):
        proc=subprocess.Popen(['sleep','60'],start_new_session=True)
        try:
            group=t.OwnedGroup(proc)
            group.identity=lambda:('other','context')
            with patch.object(t.os,'killpg') as kill:
                with self.assertRaises(t.ContextMismatch):group.stop()
                kill.assert_not_called()
        finally:proc.terminate();proc.wait()

    def test_reused_pid_is_not_signalled(self):
        proc=subprocess.Popen(['sleep','60'],start_new_session=True)
        try:
            group=t.OwnedGroup(proc);group.leader['started']='wrong';group.members={proc.pid:dict(group.leader)}
            with patch.object(t.os,'killpg') as kill:
                group.stop();kill.assert_not_called()
        finally:proc.terminate();proc.wait()


if __name__=='__main__':unittest.main()
