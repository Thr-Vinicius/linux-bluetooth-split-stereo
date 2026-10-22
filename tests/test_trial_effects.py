import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import trial_session as s
from trial_effects import classify, APP, EffectsPending
from test_trial_identity import fixture


def effects_fixture(active=True, linked=True):
    cfg, raw, g, mods=fixture()
    # Complete stereo paths: player -> EE sink -> output meter -> virtual.
    for node,direction,prefix in [(1040,'out','monitor'),(5000,'in','input'),(5000,'out','output')]:
        for n,ch in enumerate(('FL','FR')):
            i=node*100+(0 if direction=='in' else 10)+n
            g.ports[i]={'node.id':node,'port.direction':direction,'port.name':prefix+'_'+ch,'audio.channel':ch,'object.serial':str(i)}
    g.nodes[7000]={'node.name':'fixture_player','object.serial':'7000','media.class':'Stream/Output/Audio'}
    g.objects[7000]={'id':7000,'type':'PipeWire:Interface:Node','info':{'props':g.nodes[7000],'state':'running' if active else 'idle'}}
    for n,ch in enumerate(('FL','FR')):
        g.ports[70000+n]={'node.id':7000,'port.direction':'out','port.name':'out_'+ch,'audio.channel':ch}
    def link(a,b):g.links.append((90000+len(g.links),a,b,'active' if active else 'paused'))
    if active:
        for n in range(2):
            link(70000+n,10400+n)
            link(104010+n,500000+n)
    if linked:
        for n in range(2):link(500010+n,10300+n)
    inputs=[dict(index=7000,properties={'object.serial':'7000'},restore_sink='easyeffects_sink',corked=not active,mute=False)]
    return cfg,raw,g,mods,inputs


class EffectsTests(unittest.TestCase):
    def test_active_requires_both_processing_paths_and_matching_output_channels(self):
        cfg,raw,g,mods,inputs=effects_fixture()
        self.assertEqual(classify(cfg,g,inputs)['state'],'ACTIVE_VERIFIED')
        g.links=[e for e in g.links if e[1]!=104011]
        with self.assertRaises(s.RollbackError):classify(cfg,g,inputs)

    def test_idle_without_links_is_preparable_but_not_playback_ready(self):
        cfg,raw,g,mods,inputs=effects_fixture(False,False)
        self.assertEqual(classify(cfg,g,[])['state'],'IDLE_UNPROVEN')
        self.assertFalse(classify(cfg,g,inputs)['playback_ready'])

    def test_mpris_playing_cannot_replace_an_audio_stream(self):
        cfg,raw,g,mods,inputs=effects_fixture(False,False)
        cfg['MPRIS_STATUS']='Playing'
        self.assertFalse(classify(cfg,g,[])['playback_ready'])

    def test_late_stream_requires_full_path_then_becomes_ready(self):
        cfg,raw,g,mods,inputs=effects_fixture(False,False)
        self.assertFalse(classify(cfg,g,[])['playback_ready'])
        cfg,raw,g,mods,inputs=effects_fixture(True,False)
        with self.assertRaises(s.RollbackError):classify(cfg,g,inputs)
        cfg,raw,g,mods,inputs=effects_fixture()
        self.assertTrue(classify(cfg,g,inputs)['playback_ready'])

    def test_removed_stream_makes_idle_not_missing_processing_failure(self):
        cfg,raw,g,mods,inputs=effects_fixture()
        self.assertTrue(classify(cfg,g,inputs)['playback_ready'])
        g.links=[];g.nodes.pop(7000);g.objects.pop(7000)
        self.assertFalse(classify(cfg,g,[])['playback_ready'])
        with self.assertRaises(s.RollbackError):classify(cfg,g,inputs)

    def test_wrong_target_crossed_duplicate_and_partial_routes_fail_even_idle(self):
        for mode in ('wrong','crossed','duplicate','partial'):
            cfg,raw,g,mods,inputs=effects_fixture(False,True)
            link,a,b,state=g.links[0]
            if mode=='wrong':g.links[0]=(link,a,10100,state)
            if mode=='crossed':g.links[0]=(link,a,10301,state)
            if mode=='duplicate':g.links.append((99999,a,b,state))
            if mode=='partial':g.links.pop()
            with self.subTest(mode=mode),self.assertRaises(s.RollbackError):classify(cfg,g,[])

    def test_native_stream_without_pulse_input_is_still_effective_activity(self):
        cfg,raw,g,mods,inputs=effects_fixture()
        self.assertTrue(classify(cfg,g,[])['playback_ready'])

    def test_paused_links_cannot_prove_active_playback_readiness(self):
        cfg,raw,g,mods,inputs=effects_fixture()
        g.links=[(i,a,b,'paused') for i,a,b,state in g.links]
        with self.assertRaises(s.RollbackError):classify(cfg,g,inputs)

    def test_active_without_output_and_wrong_stream_destination_fail(self):
        cfg,raw,g,mods,inputs=effects_fixture(True,False)
        with self.assertRaises(s.RollbackError):classify(cfg,g,inputs)
        cfg,raw,g,mods,inputs=effects_fixture()
        inputs[0]['restore_sink']='another_sink'
        with self.assertRaises(s.RollbackError):classify(cfg,g,inputs)

    def test_foreign_output_or_processing_owner_and_ambiguity_fail(self):
        for mode in ('output','processing','ambiguous','client'):
            cfg,raw,g,mods,inputs=effects_fixture()
            if mode=='output':g.nodes[5000]['client.id']=6001
            if mode=='processing':
                g.nodes[8000]={'node.name':'foreign','application.id':'other','client.id':6001}
                g.ports[500000]['node.id']=8000
                g.ports[500010]['node.id']=8000
            if mode=='ambiguous':g.nodes[8000]=dict(g.nodes[5000])
            if mode=='client':g.objects[6000]['info']['props']['application.process.binary']='other'
            with self.subTest(mode=mode),self.assertRaises(s.RollbackError):classify(cfg,g,inputs)

    def test_owner_client_recreation_inside_window_fails(self):
        from trial_identity import identify, check_window
        cfg,raw,g,mods,inputs=effects_fixture()
        identity=identify(cfg,raw,g,mods)
        g.objects[6000]['info']['props']['object.serial']='replacement'
        with self.assertRaises(s.RollbackError):check_window(identity['cfg'],raw,g,identity)

    def test_foreign_stream_marker_is_not_a_candidate_exemption(self):
        cfg,raw,g,mods,inputs=effects_fixture()
        inputs[0]['properties']['split.owner']='another-project'
        with self.assertRaises(s.RollbackError):classify(cfg,g,inputs)

    def test_idle_start_is_rejected_before_watchdog_freeze(self):
        cfg,raw,g,mods,inputs=effects_fixture(False,False)
        lease=Mock();a=s.AudioAdapter(cfg,lease,{})
        a.identity={'current':{}}
        a.before={'edges':[],'inputs':[]}
        a.assert_identity=Mock()
        a.capture=Mock(return_value=dict(identity=a.identity,effects={'playback_ready':False},edges=[],inputs=[]))
        with self.assertRaises(s.RollbackError):a.freeze()
        lease.freeze.assert_not_called();self.assertFalse(a.intervention_started)

    def test_final_preflight_failure_never_runs_rollback_or_any_audio_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'start.request').touch()
            a=Mock();a.cfg={'TRIAL_TOKEN':'trial_0123456789abcdef'};a.before={};a.intervention_started=False
            a.preflight.side_effect=[None,s.RollbackError('Playback changed')]
            result=s.Session(path,a).run()
            self.assertEqual(result['phase'],'ABORTED_UNCHANGED')
            self.assertFalse(result['audio_changed']);a.freeze.assert_not_called();a.capture_playback.assert_not_called()

    def test_torn_capture_retries_only_reads_and_never_accepts_continuous_changes(self):
        a=s.AudioAdapter({},None,{})
        a.capture_once=Mock(side_effect=[s.RollbackError('stream disappeared'),{'effects':{'state':'IDLE_UNPROVEN'}}])
        self.assertEqual(a.capture()['effects']['state'],'IDLE_UNPROVEN')
        a.capture_once=Mock(side_effect=s.RollbackError('stream disappeared'))
        with self.assertRaises(s.RollbackError):a.capture()
        self.assertEqual(a.capture_once.call_count,3)

    def test_monitor_settles_late_stream_using_reads_only_and_wrong_routes_fail_immediately(self):
        a=s.AudioAdapter({},None,{})
        a.read_effects_once=Mock(side_effect=[EffectsPending('building'),{'state':'ACTIVE_VERIFIED'}])
        with patch('trial_session.time.sleep'):
            self.assertEqual(a.read_effects()['state'],'ACTIVE_VERIFIED')
        a.read_effects_once=Mock(side_effect=s.RollbackError('wrong destination'))
        with self.assertRaises(s.RollbackError):a.read_effects()
        self.assertEqual(a.read_effects_once.call_count,1)

    def test_monitor_never_accepts_a_permanently_incomplete_path(self):
        a=s.AudioAdapter({},None,{})
        a.read_effects_once=Mock(side_effect=EffectsPending('building'))
        with patch('trial_session.time.monotonic',side_effect=[0,0,2]),patch('trial_session.time.sleep'):
            with self.assertRaises(EffectsPending):a.read_effects()
        self.assertEqual(a.read_effects_once.call_count,2)

    def test_native_only_playback_recovers_known_route_after_candidate_loss(self):
        cfg,raw,g,mods,inputs=effects_fixture(True,False)
        g.nodes.pop(1030)
        a=s.AudioAdapter(cfg,None,{})
        known=['ee_soe_output_level','output_FL','split_lr','playback_FL']
        a.before={'inputs':[],'edges':[known]}
        a.backend=Mock();a.graph=lambda:g;a.media=lambda:{}
        a.run=lambda *args:json.dumps(raw if args[-1]=='sinks' else [])
        a.capture_playback()
        self.assertIn(known,a.backend.playback['edges'])

    def test_idle_return_does_not_invent_historical_input_links(self):
        cfg,raw,g,mods,inputs=effects_fixture(False,False)
        a=s.AudioAdapter(cfg,None,{})
        a.before={'inputs':[],'edges':[['ee_soe_output_level','output_FL','split_lr','playback_FL']]}
        a.backend=Mock();a.graph=lambda:g;a.media=lambda:{}
        a.run=lambda *args:json.dumps(raw if args[-1]=='sinks' else [])
        a.capture_playback()
        self.assertFalse(any(e[2]=='split_lr' for e in a.backend.playback['edges']))


if __name__=='__main__':unittest.main()
