"""Lifecycle assertions inside rollback-native's private PipeWire fixture only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from trial_effects import classify


def sample(cfg,c):
    raw=json.loads(c.command('pactl','-f','json','list','sinks'))
    names={s['index']:s['name'] for s in raw}
    inputs=json.loads(c.command('pactl','-f','json','list','sink-inputs'))
    for item in inputs:item['restore_sink']=names.get(item['sink'])
    return classify(cfg,c.snapshot(),inputs)


def wait_state(cfg,c,state):
    deadline=time.monotonic()+15
    error=None
    while time.monotonic()<deadline:
        try:
            value=sample(cfg,c)
            if value['state']==state and (state!='IDLE_UNPROVEN' or value['output_links']==0):return value
        except Exception as exc:error=str(exc)
        time.sleep(.1)
    raise AssertionError((state,error))


def wait_idle(cfg,c):return wait_state(cfg,c,'IDLE_UNPROVEN')
def wait_active(cfg,c):return wait_state(cfg,c,'ACTIVE_VERIFIED')


def start_player(runtime,log):
    assert runtime.name.startswith('split-return-') and runtime.parent==Path('/tmp')
    signal=runtime/'lifecycle.raw'
    signal.write_bytes(b'\x00\x00\x80\x3b\x00\x00\x00\xbc'*48000*40)
    return subprocess.Popen(['pw-cat','--playback','--raw','--format','f32','--channels','2','--target','easyeffects_sink','--properties','{ node.name = lifecycle_player }',str(signal)],stdout=log,stderr=log)


def check(runtime,cfg,c,smoke,processes,log,scenario):
    # This is fixture activity, never the user's player or session.
    assert os.environ['PULSE_SERVER']=='unix:'+str(runtime)+'/pulse/native'
    for proc in processes:
        if proc.args[0]=='pw-cat':c.stop_process(proc)
    wait_idle(cfg,c)
    initial=c.snapshot()
    sink=initial.named('easyeffects_sink')[0]
    meter=initial.named('ee_soe_output_level')[0]
    before=(initial.nodes[sink]['object.serial'],initial.nodes[meter]['object.serial'])
    player=start_player(runtime,log)
    try:
        active=wait_active(cfg,c)
        # No pw-link commands: EE itself rebuilds processing and output routes.
        player.terminate();player.wait(timeout=3)
        idle=wait_idle(cfg,c)
        after=c.snapshot()
        assert before==(after.nodes[sink]['object.serial'],after.nodes[meter]['object.serial'])
        print('PASS: real private EasyEffects idle -> late active -> idle; persistent sink/meter, dynamic links',flush=True)
        evidence=os.environ.get('SPLIT_E2E_EVIDENCE')
        if evidence:
            target=Path(evidence);target.mkdir(parents=True,exist_ok=True)
            (target/(scenario+'-lifecycle.json')).write_text(json.dumps(dict(active=active,idle=idle,persistent_identities=before),indent=2)+'\n')
    finally:
        if player.poll() is None:player.terminate();player.wait(timeout=3)
    # Both scenarios begin ARMED with legitimate idle. idle-return starts its
    # source before final preflight through the driver too.
