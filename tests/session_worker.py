"""Private process surrogate for systemd: real stop/continue, no host services."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from trial_session import AudioAdapter, Session, c
from trial_support import OwnedGroup, process_identity


class PrivateWatchdog:
    def __init__(self,path):
        self.path=path
        code='import time,pathlib; p=pathlib.Path('+repr(str(path/'heartbeat'))+'); n=0\nwhile True:\n n+=1;p.write_text(str(n));time.sleep(.02)'
        self.proc=subprocess.Popen([sys.executable,'-c',code],start_new_session=True)
        self.group=OwnedGroup(self.proc)
        self.frozen=False
        self.resumes=0
    def preflight(self):
        assert self.proc.poll() is None and not self.frozen
    def freeze(self):
        self.group.send(self.proc.pid,signal.SIGSTOP)
        deadline=time.monotonic()+2
        while not self.paused():
            if time.monotonic()>deadline:raise RuntimeError('Fixture stop not confirmed')
            time.sleep(.01)
        self.frozen=True
    def paused(self):
        state=process_identity(self.proc.pid)
        return bool(state and state['state']=='T')
    def resume(self):
        assert self.paused()
        self.group.send(self.proc.pid,signal.SIGCONT)
        self.frozen=False
        self.resumes+=1
    def verify_resumed(self):
        state=process_identity(self.proc.pid)
        return bool(state and state['state'] not in ('T','Z'))
    def close(self):
        self.group.send(self.proc.pid,signal.SIGCONT)
        self.group.stop()


def main():
    path=Path(sys.argv[1]);cfg=json.loads((path/'fixture.json').read_text())
    # Test runner refuses host audio even if called accidentally.
    runtime=Path(os.environ['XDG_RUNTIME_DIR'])
    assert runtime.name.startswith('split-return-') and runtime.parent==Path('/tmp')
    assert os.environ['PULSE_SERVER']=='unix:'+str(runtime)+'/pulse/native'
    scenario=cfg.pop('scenario')
    watchdog=PrivateWatchdog(path)
    class FaultAdapter(AudioAdapter):
        failed=False
        def remove_original(self):
            super().remove_original()
            if scenario=='swap-failure':raise RuntimeError('Injected failure after original removal')
        def launch(self,path):
            if scenario=='readiness-timeout':
                return subprocess.Popen(['sleep','30'],start_new_session=True)
            self.candidate=super().launch(path)
            return self.candidate
        def observe(self,path):
            super().observe(path)
            if scenario=='command-timeout':self.run('sleep','10')
            if not hasattr(self,'observed_at'):self.observed_at=time.monotonic()
            if scenario=='candidate-failure' and not self.failed and time.monotonic()-self.observed_at>.8:
                self.failed=True
                self.candidate.terminate()
        def run(self,*args):
            if scenario in ('return-failure','return-persistent-failure') and args[0]=='pw-link' and len(args)==3 and (not self.failed or scenario=='return-persistent-failure'):
                state=json.loads((path/'state.json').read_text()) if (path/'state.json').exists() else {}
                if state.get('phase')=='RESTORING':
                    self.failed=True
                    raise RuntimeError('Injected restoration link failure')
            return super().run(*args)
    adapter=FaultAdapter(cfg,watchdog,{})
    adapter.path=path
    session=Session(path,adapter,maximum=60 if os.environ.get('SPLIT_EXTERNAL_IPC') else 12,return_after=45 if os.environ.get('SPLIT_EXTERNAL_IPC') else 6,ready_timeout=3)
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
        signal.signal(sig,lambda *_:setattr(session,'stop_requested',True))
    try:
        result=session.run()
        result.update(private_watchdog_resumes=watchdog.resumes,
                      private_watchdog_running=watchdog.verify_resumed())
        (path/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        if not result['complete']:sys.exit(1)
    finally:watchdog.close()


if __name__=='__main__':main()
