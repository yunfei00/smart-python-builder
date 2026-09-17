"""Real Windows EXEs + Web IDs with explicitly injected offline AI/notifiers.
Run: uv run python tests/windows_notification_url_acceptance.py http://LAN-IP:8000
Never claims real Feishu delivery. Does not modify deployment settings.
"""
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from builder import SmartBuilder
from builder.ai import FakeAIProvider
from builder.notifications import FakeNotifier, NotificationService
from builder.settings import SettingsStore
from web.app import create_app

base=sys.argv[1].rstrip('/')
root=Path('.pytest-tmp-notification-'+uuid.uuid4().hex).resolve()
settings=SettingsStore(root/'settings.sqlite3')
settings.save({'allowed_hosts':'localhost,127.0.0.1,'+httpx.URL(base).host,'base_url':base})
notifier=FakeNotifier()
services=[]
def verify(path):
    result=subprocess.run([str(path)],capture_output=True,text=True,timeout=30)
    if result.returncode: raise RuntimeError(result.stderr)
    assert 'notification-normal-ok' in result.stdout or 'repair-ok' in result.stdout

def factory(workspace):
    provider=FakeAIProvider([dict(root_cause='Dynamic colorsys import missing',confidence=.99,changes={'hidden_imports':['colorsys']},retry=True)])
    service=NotificationService(notifier);services.append(service)
    return SmartBuilder(workspace,settings_store=settings,ai_provider=provider,notifications=service,artifact_validator=verify)

app=create_app(root,builder_factory=factory)
server=uvicorn.Server(uvicorn.Config(app,host='0.0.0.0',port=8000,log_level='warning'))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
report={'base_url':base,'credentials':'NOT VERIFIED WITH REAL CREDENTIALS','cases':[]}
try:
    for _ in range(200):
        if server.started:break
        time.sleep(.05)
    assert server.started
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=30,trust_env=False) as client:
        for name,source in [('normal',"print('notification-normal-ok')"),('repair',"import importlib\nm=importlib.import_module('color'+'sys')\nprint('repair-ok',m.rgb_to_hsv(1,0,0))"),('notifier-outage',"print('notification-normal-ok')")]:
            notifier.events.clear();notifier.fail=name=='notifier-outage'
            job=client.post('/api/uploads',files={'file':('main.py',source)}).json()
            response=client.post('/api/jobs/'+job['id']+'/build',data={'entry':'main.py'})
            response.raise_for_status()
            deadline=time.monotonic()+900
            while time.monotonic()<deadline:
                current=client.get('/api/jobs/'+job['id']).json()
                if current['terminal']:break
                time.sleep(1)
            assert current['status']=='SUCCESS' and current['terminal'],current
            events=[e['event'] for e in notifier.events]
            assert events==(['Build Success'] if name=='normal' else ['Build Failed','AI Repair Success'] if name=='repair' else []),events
            details=base+'/?job='+job['id']
            for event in notifier.events:
                assert event['details_url']==details
                if 'approval_url' in event:assert event['approval_url']==base+'/admin'
                assert '127.0.0.1' not in event['details_url']
            with httpx.Client(trust_env=False,timeout=15) as lan:
                assert lan.get(details).status_code==200
                assert lan.get(base+'/api/jobs/'+job['id']).json()['status']=='SUCCESS'
            exe=root/(name+'.exe');exe.write_bytes(client.get('/api/jobs/'+job['id']+'/download').content)
            verify(exe)
            failures=json.loads(Path(current['artifact']).parents[2].joinpath('attempts.json').read_text())['notification_failures']
            if name=='notifier-outage':assert failures==['RuntimeError']
            row=dict(case=name,result='PASS',job_id=job['id'],build_id=current['build_id'],artifact=str(exe),events=events,details_url=details,runtime='exit 0; expected output verified',notification_failures=failures)
            report['cases'].append(row)
            Path('docs/notification-url-windows.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(row),flush=True)
finally:
    server.should_exit=True;thread.join(timeout=15)
