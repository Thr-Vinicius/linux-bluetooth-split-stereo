#!/usr/bin/env python3
"""Prepare read-only, or execute an explicitly authorized, reviewed A-B-A plan.

Preparation does NOT grant authorization. Never run --execute-reviewed-plan
without the user's separate consent for that specific real-device window.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import time

from trial_session import AudioAdapter, ServiceWatchdog, Session, c, ROOT
from trial_support import private_directory, save_state


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_hashes():
    paths=[ROOT/'bluetooth-split-controller.py',ROOT/'tools/trial-supervisor.py',
           ROOT/'tools/trial_session.py',ROOT/'tools/trial_support.py']
    return {str(p):sha(p) for p in paths}


def prepare(args):
    path=args.session.resolve()
    path.mkdir(mode=0o700,parents=True,exist_ok=False)
    cfg=c.config(args.config.resolve())
    cfg.update(AUTO_DEFAULT='false',NATIVE_DEBUG='true',TRIAL_TOKEN=secrets.token_hex(16))
    prefix=['systemctl','--user','--machine='+os.environ.get('USER',str(os.getuid()))+'@.host']
    # Prefix selects the host manager from this desktop execution context. It is
    # explicit and persisted; no fallback to a different service manager.
    values={}
    for item in json.loads(args.manifest.read_text())['files']:
        if 'sha256' not in item:continue
        source=Path(item['source'])
        backup=(args.manifest.resolve().parents[2]/item['backup']).resolve()
        if sha(source)!=item['sha256'] or sha(backup)!=item['sha256']:
            raise RuntimeError('Original or backup hash differs; capture a fresh reviewed backup')
        values[str(source)]=item['sha256']
        values[str(backup)]=item['sha256']
    flag=Path(os.environ['XDG_RUNTIME_DIR'])/f'fones-watchdog-resync-request-{os.getuid()}.flag'
    lease=ServiceWatchdog(c.command,prefix,'fones-watchdog.service',{},flag)
    state=lease.state()
    if state.get('ActiveState')!='active' or state.get('SubState')!='running' or int(state.get('MainPID','0'))<=0 or not state.get('InvocationID'):
        raise RuntimeError('Original watchdog is not an identifiable active service')
    lease.saved={k:state[k] for k in ('MainPID','ActiveState','SubState','UnitFileState','InvocationID')}
    adapter=AudioAdapter(cfg,lease,values)
    adapter.preflight()
    # Legacy watchdog must already recognize these connections before freezing.
    indexes=':'.join(str(adapter.before['sinks'][cfg[s+'_DEVICE']]['index']) for s in ('LEFT','RIGHT'))
    sync=flag.parent/f'fones-watchdog-sync-{os.getuid()}.state'
    if sync.read_text().strip()!=indexes:raise RuntimeError('Legacy device state is not settled')
    for side in ('LEFT','RIGHT'):
        sink=adapter.before['sinks'][cfg[side+'_DEVICE']]
        if sink['properties'].get('api.bluez5.codec')!='aac' or sink['properties'].get('api.bluez5.profile')!='a2dp-sink':
            raise RuntimeError('Expected A2DP/AAC endpoints')
        if 'Connected: yes' not in c.command('bluetoothctl','info',cfg[side+'_MAC']):
            raise RuntimeError('Bluetooth endpoint not connected')
    plan=dict(cfg=cfg,hashes=values,code_hashes=code_hashes(),service_prefix=prefix,
              service_saved=lease.saved,request_flag=str(flag),sync_file=str(sync),
              sync_indexes=indexes,maximum=600,return_after=360,ready_timeout=30,
              original_module=adapter.old_module,physical_signature=adapter.backend.signature(adapter.before['sinks']))
    (path/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    (path/'prepared-before.json').write_text(json.dumps(adapter.before,indent=2)+'\n')
    save_state(path,dict(phase='PREPARED_NOT_AUTHORIZED',complete=False,audio_changed=False))
    print('Read-only preparation complete. No authorization granted. '+str(path))


def execute(path):
    path=private_directory(path.resolve())
    plan=json.loads((path/'plan.json').read_text())
    if (path/'events.jsonl').exists():raise RuntimeError('Session already used; prepare a new one')
    if code_hashes()!=plan['code_hashes']:raise RuntimeError('Candidate code changed after preparation')
    for p,h in plan['hashes'].items():
        if sha(p)!=h:raise RuntimeError('Original/backup changed after preparation')
    lease=ServiceWatchdog(c.command,plan['service_prefix'],'fones-watchdog.service',plan['service_saved'],plan['request_flag'])
    class ReviewedAdapter(AudioAdapter):
        def preflight(self):
            super().preflight()
            if list(self.old_module)!=plan['original_module'] or json.loads(json.dumps(self.backend.signature(self.before['sinks'])))!=plan['physical_signature']:
                raise RuntimeError('Prepared resources changed; no intervention')
            if Path(plan['sync_file']).read_text().strip()!=plan['sync_indexes']:
                raise RuntimeError('Legacy connection state changed')
    adapter=ReviewedAdapter(plan['cfg'],lease,plan['hashes'])
    # Use bounded service commands too; not c.command's default five seconds.
    lease.run=adapter.run
    adapter.path=path
    session=Session(path,adapter,plan['maximum'],plan['return_after'],plan['ready_timeout'])
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
        signal.signal(sig,lambda *_:setattr(session,'stop_requested',True))
    try:
        result=session.run()
        print(json.dumps(result,indent=2))
        return 0 if result['complete'] else 1
    except Exception as exc:
        save_state(path,dict(phase='PREFLIGHT_FAILED_UNCHANGED' if session.started is None else 'FAILED_UNKNOWN',complete=False,error=str(exc)))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare',action='store_true')
    action.add_argument('--execute-reviewed-plan',action='store_true')
    action.add_argument('--request-start',action='store_true')
    parser.add_argument('--session',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--manifest',type=Path)
    args=parser.parse_args()
    if args.prepare:
        if not args.config or not args.manifest:parser.error('Preparation requires config and backup manifest')
        prepare(args)
    elif args.request_start:
        path=private_directory(args.session.resolve())
        if json.loads((path/'state.json').read_text())['phase']!='ARMED':raise RuntimeError('Owner is not armed')
        pulse=json.loads((path/'heartbeat.json').read_text())
        if time.monotonic()-pulse['monotonic']>2:raise RuntimeError('Persistent owner heartbeat is stale; no start requested')
        fd=os.open(path/'start.request',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        os.close(fd)
        print('Start requested; wait for verified ROUTED. This is not proof of readiness.')
    else:sys.exit(execute(args.session))


if __name__=='__main__':main()
