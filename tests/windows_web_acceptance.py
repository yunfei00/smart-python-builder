from pathlib import Path
import httpx, time, subprocess, json
import sys
base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8765'
with httpx.Client(base_url=base, timeout=30) as client:
    assert client.get('/').status_code==200
    job=client.post('/api/uploads',files={'file':('hello.py',b"print('web-build-ok')")}).json()
    response=client.post('/api/jobs/'+job['id']+'/build',data={'entry':'hello.py'})
    response.raise_for_status()
    deadline=time.monotonic()+240
    while time.monotonic()<deadline:
        state=client.get('/api/jobs/'+job['id']).json()
        if state.get('terminal'):break
        time.sleep(1)
    assert state['status']=='SUCCESS',state
    download=client.get('/api/jobs/'+job['id']+'/download')
    download.raise_for_status()
    artifact=Path('.pytest-tmp-web-download.exe').resolve()
    artifact.write_bytes(download.content)
    p=subprocess.run([str(artifact)],capture_output=True,text=True,timeout=30)
    assert p.returncode==0 and 'web-build-ok' in p.stdout,p.stderr
    Path('.pytest-tmp-web-acceptance.json').write_text(json.dumps(dict(status='PASS',job_id=job['id'],build_id=state['build_id'],artifact=str(artifact),notes='Live HTTP upload, build, log, download; EXE exit 0: '+p.stdout),indent=2))
    assert '[exit_code=0]' in client.get('/api/jobs/'+job['id']+'/log').json()['text']
    print(state)
