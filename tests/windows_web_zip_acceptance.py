import io,zipfile,httpx,time,json,subprocess,uuid
from pathlib import Path
payload=io.BytesIO()
with zipfile.ZipFile(payload,'w') as z:
    z.writestr('main.py',"from pathlib import Path\nimport json\nprint(json.loads(Path(__file__).with_name('config.json').read_text())['value'])")
    z.writestr('app.py',"print('not-selected')")
    z.writestr('config.json','{"value":"web-zip-ok"}')
import sys
base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765'
with httpx.Client(base_url=base,timeout=30) as c:
    response=c.post('/api/uploads',files={'file':('project.zip',payload.getvalue())});response.raise_for_status();j=response.json()
    assert j['entry'] is None
    plan=c.get('/api/jobs/'+j['id']+'/plan',params={'entry':'main.py','mode':'onedir'}).json()
    assert ['config.json','.'] in plan['data_files']
    c.post('/api/jobs/'+j['id']+'/build',data={'entry':'main.py','mode':'onedir'}).raise_for_status()
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        state=c.get('/api/jobs/'+j['id']).json()
        if state.get('terminal'):break
        time.sleep(1)
    assert state['status']=='SUCCESS',state
    r=c.get('/api/jobs/'+j['id']+'/download');r.raise_for_status()
    destination=Path('.pytest-tmp-web-zip-'+uuid.uuid4().hex);destination.mkdir()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:z.extractall(destination)
    exe=next(destination.rglob('main.exe')).resolve()
    p=subprocess.run([str(exe)],capture_output=True,text=True,timeout=30)
    assert p.returncode==0 and 'web-zip-ok' in p.stdout,p.stderr
    destination.joinpath('acceptance-result.json').write_text(json.dumps(dict(status='PASS',job_id=j['id'],build_id=state['build_id'],artifact=str(exe),notes='Live HTTP ZIP upload, explicit multi-entry selection, automatic JSON resource inclusion, onedir ZIP download, EXE exit 0'),indent=2))
    print('WEB ZIP PASS',state['build_id'])
