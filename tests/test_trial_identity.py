import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import trial_session as s
import trial_identity as ident

LEFT='AA:BB:CC:DD:EE:01'
RIGHT='AA:BB:CC:DD:EE:02'
ARG='sink_name=split_lr channels=2 channel_map=front-left,front-right'


def fixture(seed=0, volume=1000, mute=False):
    cfg=dict(LEFT_MAC=LEFT,RIGHT_MAC=RIGHT,LEFT_DEVICE='old-left-name',RIGHT_DEVICE='old-right-name',
             VIRTUAL_SINK='split_lr',AUTO_DEFAULT='false',TRIAL_TOKEN='trial_0123456789abcdef')
    sinks=[];objects=[]
    def add(name,serial,props,owner=4294967295):
        node=serial+1000
        props=dict(props,**{'node.name':name,'object.serial':str(serial)})
        sinks.append(dict(name=name,index=serial,owner_module=owner,properties=dict(props),channel_map='front-left,front-right',
                          volume={'front-left':{'value':volume},'front-right':{'value':volume}},mute=mute))
        objects.append({'id':node,'type':'PipeWire:Interface:Node','info':{'props':props}})
        for i,ch in enumerate(('FL','FR')):
            objects.append({'id':node*10+i,'type':'PipeWire:Interface:Port','info':{'props':{'node.id':node,'object.serial':str(node*10+i),'port.direction':'in','port.name':'playback_'+ch,'audio.channel':ch}}})
    for side,mac,n in [('LEFT',LEFT,10),('RIGHT',RIGHT,20)]:
        add('bluez_output.'+mac.replace(':','_')+'.'+str(seed+1),n+seed,
            dict(dict(zip(ident.BT_KEYS,('bluez5','Audio/Sink',mac,'a2dp-sink','aac'))),**{'factory.name':'api.bluez5.a2dp.sink'}))
    module=str(900+seed)
    add('split_lr',30+seed,{'pulse.module.id':module,'factory.name':'support.null-audio-sink','media.class':'Audio/Sink'},int(module))
    add('easyeffects_sink',40+seed,{'factory.name':'support.null-audio-sink','media.class':'Audio/Sink','application.id':'com.github.wwmm.easyeffects','client.id':6000})
    objects.append({'id':5000+seed,'type':'PipeWire:Interface:Node','info':{'props':{'node.name':'ee_soe_output_level','object.serial':str(5000+seed),'application.id':'com.github.wwmm.easyeffects','client.id':6000}}})
    objects.append({'id':6000,'type':'PipeWire:Interface:Client','info':{'props':{'object.serial':'6000','application.name':'easyeffects','application.process.binary':'easyeffects'}}})
    return cfg,sinks,s.c.Graph(objects),[(module,ARG)]


class IdentityTests(unittest.TestCase):
    def test_changed_ids_serials_and_endpoint_names_are_accepted_between_sessions(self):
        cfg,raw,g,mods=fixture();old=ident.identify(cfg,raw,g,mods)
        cfg,raw,g,mods=fixture(100)
        new=ident.identify(cfg,raw,g,mods,old['stable'])
        self.assertEqual(new['stable'],old['stable'])
        self.assertNotEqual(new['current'],old['current'])
        self.assertEqual(new['cfg']['LEFT_DEVICE'],'bluez_output.AA_BB_CC_DD_EE_01.101')
        self.assertEqual(new['current']['legacy']['module_id'],'1000')

    def test_current_volume_and_mute_are_audited_and_not_historical_gates(self):
        cfg,old,g,mods=fixture(volume=1000)
        policy=ident.identify(cfg,old,g,mods)['stable']
        cfg,current,g,mods=fixture(100,volume=5000,mute=True)
        ident.identify(cfg,current,g,mods,policy)
        delta=ident.audit_difference({'sinks':old},{'sinks':current})
        self.assertEqual(delta['sinks']['current'][0]['volume']['front-left']['value'],5000)
        self.assertTrue(delta['sinks']['current'][0]['mute'])

    def test_different_mac_under_expected_name_is_not_the_expected_device(self):
        cfg,raw,g,mods=fixture()
        raw[0]['properties']['api.bluez5.address']='AA:BB:CC:DD:EE:99'
        with self.assertRaises(s.RollbackError):ident.identify(cfg,raw,g,mods)

    def test_duplicate_mac_and_duplicate_names_fail(self):
        cfg,raw,g,mods=fixture()
        for duplicate in (dict(raw[0]),dict(raw[0],name='another-name')):
            with self.assertRaises(s.RollbackError):ident.identify(cfg,raw+[duplicate],g,mods)

    def test_graph_address_disagreement_and_foreign_ownership_fail(self):
        for key,value in [('api.bluez5.address','AA:BB:CC:DD:EE:99'),('split.owner','foreign')]:
            cfg,raw,g,mods=fixture();g.nodes[1010][key]=value
            with self.assertRaises(s.RollbackError):ident.identify(cfg,raw,g,mods)

    def test_null_owner_and_stable_module_arguments_are_verified(self):
        cfg,raw,g,mods=fixture();policy=ident.identify(cfg,raw,g,mods)['stable']
        raw[2]['owner_module']=777
        with self.assertRaises(s.RollbackError):ident.identify(cfg,raw,g,mods)
        cfg,raw,g,mods=fixture(100)
        with self.assertRaises(s.RollbackError):ident.identify(cfg,raw,g,[(mods[0][0],ARG+' rate=44100')],policy)
        g.nodes[1130]['split.owner']='foreign'
        with self.assertRaises(s.RollbackError):ident.identify(cfg,raw,g,mods)

    def adapter(self,seed=0):
        cfg,raw,g,mods=fixture(seed)
        identity=ident.identify(cfg,raw,g,mods)
        lease=Mock();lease.paused.return_value=True
        adapter=s.AudioAdapter(identity['cfg'],lease,{})
        adapter.identity=identity;adapter.old_module=mods[0]
        adapter.before=dict(sinks={x['name']:x for x in raw},legacy={'argument':ARG},edges=[])
        calls=[]
        def run(*args):
            calls.append(args)
            if args[0]=='pw-dump':return json.dumps(list(g.objects.values()))
            if args[:4]==('pactl','-f','json','list'):return json.dumps(raw)
            if args==('pactl','list','short','modules'):return '\t'.join([mods[0][0],'module-null-sink',ARG])
            raise AssertionError('Unexpected write: '+str(args))
        adapter.injected_run=run
        return adapter,raw,g,calls

    def test_final_window_blocks_same_mac_recreation_before_any_audio_write(self):
        adapter,raw,g,calls=self.adapter()
        # A valid MAC is not permission to silently adopt new IDs INSIDE a window.
        raw[0]['index']+=1;raw[0]['properties']['object.serial']='999'
        with self.assertRaises(s.RollbackError):adapter.run('pactl','set-sink-mute',adapter.cfg['LEFT_DEVICE'],'1')
        self.assertFalse(any(a[:2]==('pactl','set-sink-mute') for a in calls))

    def test_same_mac_recreation_blocks_freeze_before_intervention(self):
        adapter,raw,g,calls=self.adapter();raw[0]['index']+=1
        with self.assertRaises(s.RollbackError):adapter.freeze()
        adapter.watchdog.freeze.assert_not_called()

    def test_current_numeric_target_not_historical_name_or_index(self):
        adapter,raw,g,calls=self.adapter(100)
        command=adapter.guard_write(('pactl','set-sink-volume',adapter.cfg['LEFT_DEVICE'],'5000'))
        self.assertEqual(command,('pactl','set-sink-volume','110','5000'))

    def test_identity_guard_blocks_replaced_port(self):
        cfg,raw,g,mods=fixture();identity=ident.identify(cfg,raw,g,mods)
        g.ports[10100]['object.serial']='replacement'
        with self.assertRaises(s.RollbackError):ident.check_window(identity['cfg'],raw,g,identity)

    def test_levels_can_change_before_capture_without_becoming_identity(self):
        cfg,raw,g,mods=fixture();identity=ident.identify(cfg,raw,g,mods)
        raw[0]['volume']['front-left']['value']=5000;raw[0]['mute']=True
        ident.check_window(identity['cfg'],raw,g,identity)

    def test_old_snapshot_policy_discards_ids_and_levels_but_preserves_constraints(self):
        cfg,raw,g,mods=fixture()
        original=ident.identify(cfg,raw,g,mods)
        old=dict(sinks={v['name']:v for v in raw},legacy={'argument':ARG})
        policy=ident.policy_from_history(original['cfg'],old)
        self.assertEqual(policy,original['stable'])
        cfg,raw,g,mods=fixture(100,volume=8000,mute=True)
        ident.identify(cfg,raw,g,mods,policy)
        raw[0]['properties']['api.bluez5.codec']='sbc'
        with self.assertRaises(s.RollbackError):ident.identify(cfg,raw,g,mods,policy)

    def test_foreign_virtual_marker_inside_window_blocks_write(self):
        adapter,raw,g,calls=self.adapter()
        g.nodes[1030]['split.session']='foreign-trial'
        with self.assertRaises(s.RollbackError):adapter.guard_write(('pactl','set-sink-mute','split_lr','1'))
        self.assertFalse(any(a[:2]==('pactl','set-sink-mute') for a in calls))

    def test_duplicate_mac_inside_window_blocks_write(self):
        adapter,raw,g,calls=self.adapter()
        duplicate=copy.deepcopy(raw[0]);duplicate['name']='bluez_output.AA_BB_CC_DD_EE_01.duplicate';raw.append(duplicate)
        with self.assertRaises(s.RollbackError):adapter.guard_write(('pactl','set-sink-mute',adapter.cfg['LEFT_DEVICE'],'1'))

    def test_production_requires_two_macs(self):
        with self.assertRaises(s.RollbackError):ident.require_bluetooth({'LEFT_MAC':LEFT,'RIGHT_MAC':LEFT})
        with self.assertRaises(s.RollbackError):ident.require_bluetooth({'LEFT_DEVICE':'name','RIGHT_DEVICE':'other'})


class EffectiveWatchdogTests(unittest.TestCase):
    def lease(self):
        script='/tmp/fixture-watchdog.sh'
        state=dict(MainPID='42',InvocationID='current-invocation',ActiveState='active',SubState='running',UnitFileState='enabled',FreezerState='running')
        command=['bash '+script]
        def run(*args):
            if args[0]=='busctl':return json.dumps({'data':[[['/fixture',int(state['MainPID']),command[0]]]]})
            if 'ExecMainPID' in args:
                return '\n'.join(['Id=fixture.service','ExecMainPID='+state['MainPID'],'ExecMainStartTimestampMonotonic=100','ExecStart={ path='+script+' ; }','ControlGroup=/fixture'])
            return '\n'.join(k+'='+v for k,v in state.items())
        lease=s.ServiceWatchdog(run,['systemctl'],'fixture.service',{'MainPID':'old-pid'},Path('/fixture-no-request'))
        lease.enable_verified_process(script)
        return lease,state,command

    def test_new_invocation_bound_fresh_then_pinned_for_window(self):
        from unittest.mock import patch
        lease,state,command=self.lease()
        with patch.dict(s.os.environ,{'DBUS_SESSION_BUS_ADDRESS':'unix:path=/private-fixture'}):
            lease.preflight();self.assertEqual(lease.saved['MainPID'],'42')
            state['MainPID']='43'
            with self.assertRaises(s.RollbackError):lease.preflight()

    def test_effective_process_must_match_verified_watchdog(self):
        from unittest.mock import patch
        lease,state,command=self.lease();command[0]='bash /tmp/unrelated.sh'
        with patch.dict(s.os.environ,{'DBUS_SESSION_BUS_ADDRESS':'unix:path=/private-fixture'}):
            with self.assertRaises(s.RollbackError):lease.preflight()


if __name__=='__main__':unittest.main()
