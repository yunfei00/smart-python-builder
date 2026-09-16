import io
import time
import zipfile

from fastapi.testclient import TestClient

from web.app import create_app


def zipped(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name, data in files.items(): z.writestr(name,data)
    return stream.getvalue()


def test_upload_and_entry_selection(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/').status_code == 200
        response=client.post('/api/uploads',files={'file':('demo.zip',zipped({'main.py':'print(1)','app.py':'print(2)'}))})
        assert response.status_code == 200
        job=response.json()
        assert job['entry'] is None and len(job['entries'])==2
        assert client.post(f"/api/jobs/{job['id']}/build",data={'entry':'../main.py'}).status_code==400
        assert client.get(f"/api/jobs/{job['id']}/download").status_code==409


def test_upload_rejects_unsafe_files(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        for name, content in [('evil.txt',b'bad'),('bad.zip',zipped({'../evil.py':'bad'})),('bad.zip',zipped({'C:/evil.py':'bad'}))]:
            assert client.post('/api/uploads',files={'file':(name,content)}).status_code==400
        assert not (tmp_path/'evil.py').exists()


def test_upload_plan(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        job=client.post('/api/uploads',files={'file':('demo.py',b'import tkinter')}).json()
        assert job['plan']['app_type']=='gui'
        assert job['dependencies']==[]
        assert client.get('/api/jobs/unknown').status_code==404


def test_plan_preview_for_multiple_entries(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        job=client.post('/api/uploads',files={'file':('demo.zip',zipped({'main.py':'print(1)','app.py':'print(2)'}))}).json()
        r=client.get(f"/api/jobs/{job['id']}/plan",params={'entry':'app.py','mode':'onedir'})
        assert r.status_code==200
        assert r.json()['entry_point']=='app.py' and r.json()['mode']=='onedir'
        assert client.post('/api/uploads',files={'file':('broken.zip',b'not zip')}).status_code==400
