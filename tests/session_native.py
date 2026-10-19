"""E2E driver imported by rollback-native inside its private audio fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def wait(path, phase, timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if path.exists():
            state=json.loads(path.read_text())
            if state['phase']==phase:return state
            if state['phase']=='FAILED':raise AssertionError(state)
        time.sleep(.05)
    raise AssertionError('Phase not reached: '+phase)


def run(runtime,cfg,scenario,c,independent,ee_output):
    session=runtime/('session-'+scenario);session.mkdir(mode=0o700)
    cfg=dict(cfg,EFFECTS_OUTPUT_NAME=ee_output,scenario=scenario)
    (session/'fixture.json').write_text(json.dumps(cfg))
    log=(session/'worker.log').open('w')
    proc=subprocess.Popen([sys.executable,str(ROOT/'tests/session_worker.py'),str(session)],stdout=log,stderr=log,start_new_session=True)
    try:
        armed=wait(session/'state.json','ARMED')
        if scenario=='cancelled':
            (session/'return.request').touch()
        else:
            external=os.environ.get('SPLIT_EXTERNAL_IPC')
            if external:
                Path(external).write_text(json.dumps(dict(session=str(session),owner_context=armed['owner_context'])))
            # A separate short-lived requester exits; it never owns candidate PID.
            if not external:
                subprocess.run([sys.executable,str(ROOT/'tools/trial-supervisor.py'),'--request-start','--session',str(session)],check=True,stdout=log)
            if scenario not in ('swap-failure','readiness-timeout'):
                wait(session/'state.json','ROUTED',timeout=35 if external else 15)
                # Actual PCM playback into the same private EE path. This is an
                # application child of the tester, not controlled by supervisor.
                signal=runtime/'session-audio.raw'
                signal.write_bytes(b'\x00\x00\x80\x3b\x00\x00\x00\xbc'*48000*8)
                player=subprocess.Popen(['pw-cat','--playback','--raw','--format','f32','--channels','2','--target','easyeffects_sink','--properties','{ node.name = aba_fixture_player }',str(signal)],stdout=log,stderr=log)
                try:
                    time.sleep(.3)
                    assert player.poll() is None
                    inputs=json.loads(c.command('pactl','-f','json','list','sink-inputs'))
                    streams=[i for i in inputs if i['properties'].get('node.name')=='aba_fixture_player']
                    assert len(streams)==1 and not streams[0]['corked'],streams
                    (session/'playback.json').write_text(json.dumps(streams,indent=2)+'\n')
                    if not external and scenario in ('requested','return-failure','return-persistent-failure','requester-exit'):
                        subprocess.run([sys.executable,str(ROOT/'tools/request-return.py'),'--session',str(session)],check=True,stdout=log)
                    if scenario=='signal':proc.send_signal(15)
                    proc.wait(timeout=15)
                finally:
                    player.terminate();player.wait(timeout=3)
        proc.wait(timeout=15)
        if proc.returncode and scenario!='return-persistent-failure':
            raise AssertionError((session/'worker.log').read_text())
        result=json.loads((session/'result.json').read_text())
        assert result['complete'] == (scenario!='return-persistent-failure'),result
        if scenario=='return-persistent-failure':
            assert result['phase']=='FAILED' and result['private_watchdog_resumes']==0 and result['attempts']==3,result
        elif scenario=='cancelled':
            assert result['phase']=='CANCELLED_UNCHANGED' and result['private_watchdog_resumes']==0,result
        else:
            assert result['resources_ok'] and result['within_limit'] and result['elapsed']<(60 if os.environ.get('SPLIT_EXTERNAL_IPC') else 12),result
            assert result['private_watchdog_resumes']==1 and result['private_watchdog_running'],result
            assert result['owner_context']==armed['owner_context'],result
        if scenario=='return-failure':assert result['attempts']==2,result
        if scenario=='deadline':assert result['reason']=='deadline' and result['elapsed']>=6,result
        if scenario in ('swap-failure','readiness-timeout','candidate-failure','command-timeout'):assert result['reason']=='failure',result
        assert independent<={i for i,_,_,_ in c.snapshot().links}
        assert not any(p.get('split.session')==cfg['TRIAL_TOKEN'] for p in c.snapshot().nodes.values())
        print('PASS: persistent E2E',scenario,result['phase'],round(result.get('elapsed',0),3),'seconds',flush=True)
        # Persist all assertions' input and lifecycle trace outside temp fixture.
        output=os.environ.get('SPLIT_E2E_EVIDENCE')
        if output:
            import shutil
            target=Path(output)/scenario;target.mkdir(parents=True,exist_ok=True)
            for f in session.iterdir():
                if f.is_file():shutil.copyfile(f,target/f.name)
    finally:
        if sys.exc_info()[0]:
            print((session/'worker.log').read_text())
            for name in ('state.json','events.jsonl','candidate.log'):
                if (session/name).exists():print(name,(session/name).read_text())
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        log.close()
