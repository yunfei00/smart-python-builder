import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from builder import BuildEngine, BuildRequest
from builder.execution import LocalWindowsBackend
from builder.maintenance import cleanup_workspaces
from web.app import create_app
from test_web import zipped


def test_command_timeout(tmp_path):
    with (tmp_path/'log').open('w') as log:
        started=time.monotonic()
        with pytest.raises(TimeoutError):
            LocalWindowsBackend().run([sys.executable,'-c','import time; time.sleep(30)'],tmp_path,log,0.2)
        assert time.monotonic()-started<10


def test_disk_failure_is_logged(tmp_path,monkeypatch):
    source=tmp_path/'main.py';source.write_text('print(1)')
    engine=BuildEngine(tmp_path/'workspace');engine.min_free_bytes=10**30
    result=engine.build(BuildRequest(source))
    assert not result.success
    assert 'Insufficient disk space' in result.log_file.read_text()
    assert json.loads((result.workspace/'task.json').read_text())['status']=='FAILED'


def test_retention_preserves_active_and_unknown_directories(tmp_path):
    expired=tmp_path/('a'*32);active=tmp_path/('b'*32);other=tmp_path/'user-files'
    for path in (expired,active,other):path.mkdir()
    (expired/'task.json').write_text(json.dumps(dict(status='SUCCESS',finished_at=1)))
    (active/'task.json').write_text(json.dumps(dict(status='BUILDING',finished_at=1)))
    assert cleanup_workspaces(tmp_path,retention_seconds=10,now=100)==['a'*32]
    assert active.exists() and other.exists()


def test_restart_recovers_tasks(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        job=client.post('/api/uploads',files={'file':('main.py',b'print(1)')}).json()
    path=tmp_path/(job['id']+'.json');saved=json.loads(path.read_text());saved['status']='REBUILDING';path.write_text(json.dumps(saved))
    with TestClient(create_app(tmp_path)) as client:
        recovered=client.get('/api/jobs/'+job['id']).json()
        assert recovered['status']=='NEEDS_MANUAL_REVIEW' and recovered['terminal']


@pytest.mark.parametrize('name',['CON.py','x/../evil.py','x\\evil.py','x/a:evil.py','NUL/data.py','file.py.','/absolute.py'])
def test_windows_zip_paths_rejected(tmp_path,name):
    with TestClient(create_app(tmp_path)) as client:
        archive = zipped({name:'print(1)'})
        if '\\' in name:
            archive = archive.replace(name.replace('\\','/').encode(), name.encode())
        assert client.post('/api/uploads',files={'file':('project.zip',archive)}).status_code==400


def test_request_size_and_origin_limit(tmp_path, monkeypatch):
    # Security assertions must use the application's default host policy, not
    # a deployment override such as BUILDER_ALLOWED_HOSTS='*'.
    monkeypatch.delenv('BUILDER_ALLOWED_HOSTS', raising=False)
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/api/uploads',content=b'x',headers={'Content-Length':str(22*1024*1024)}).status_code==413
        assert client.post('/api/uploads',headers={'Origin':'https://evil.invalid'}).status_code==403
        assert client.get('/',headers={'Host':'evil.invalid'}).status_code==400


def test_resources_are_in_build_plan(tmp_path):
    from analyzer import analyze_project
    from builder.experience import ExperienceEngine
    (tmp_path/'main.py').write_text('print(1)')
    (tmp_path/'config.json').write_text('{}')
    assets=tmp_path/'assets';assets.mkdir();(assets/'icon.png').write_bytes(b'image')
    plan=ExperienceEngine().plan(analyze_project(tmp_path),tmp_path/'main.py')
    assert ['config.json','.'] in plan.data_files
    assert [str(Path('assets')/'icon.png'),'assets'] in plan.data_files


def test_expired_upload_cleanup(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        job=client.post('/api/uploads',files={'file':('main.py',b'print(1)')}).json()
    path=tmp_path/(job['id']+'.json')
    saved=json.loads(path.read_text())
    saved['created_at']=0
    path.write_text(json.dumps(saved))
    with TestClient(create_app(tmp_path)) as client:
        # Retention now removes expired build records and their managed files
        # instead of keeping an EXPIRED tombstone indefinitely.
        response=client.get('/api/jobs/'+job['id'])
        assert response.status_code==404
    assert not (tmp_path/'uploads'/job['id']).exists()
    assert not path.exists()
