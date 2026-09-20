import io
import json
import secrets
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from builder.ai import FakeAIProvider
from builder.engine import BuildEngine, BuildResult
from builder.notifications import FakeNotifier, NotificationService, format_message
from builder.settings import SettingsStore
from builder.urls import normalize_base_url, local_base_url
from test_ai import make_builder, response
from web.app import create_app


@pytest.mark.parametrize('scenario', ['normal','repair','exhausted','declined','invalid'])
def test_notification_state_machine(tmp_path,monkeypatch,scenario):
    provider=FakeAIProvider([response({'hidden_imports':['colorsys']})]*2)
    if scenario == 'declined': provider=FakeAIProvider([response({},False)])
    if scenario == 'invalid': provider=FakeAIProvider([{'invalid':'response'}])
    builder,source,calls=make_builder(tmp_path,monkeypatch,provider,lambda r: scenario=='normal' or scenario=='repair' and 'colorsys' in r.plan.hidden_imports)
    store=SettingsStore(tmp_path/'settings.sqlite3');store.save({'base_url':'http://192.168.1.105:8000'})
    builder.settings_store=store;builder.web_job_id='web-job-not-build-id'
    fake=FakeNotifier();builder.notifications=NotificationService(fake)
    result=builder.build(source)
    expected=['Build Success'] if scenario=='normal' else ['Build Failed','AI Repair Success' if scenario=='repair' else 'AI Repair Failed']
    assert [e['event'] for e in fake.events] == expected
    for event in fake.events:
        assert event['details_url']=='http://192.168.1.105:8000/?job=web-job-not-build-id'
        assert '127.0.0.1' not in json.dumps(event)
    if scenario=='normal':
        event=fake.events[0]
        assert event['project']=='main.py' and event['entry']=='main.py'
        assert event['attempt_count']==1 and event['status']=='SUCCESS'
        assert event['dependencies']==[] and event['build_id']==result.build.build_id
    else:
        assert fake.events[-1]['approval_url']=='http://192.168.1.105:8000/admin'


def test_success_notification_failure_isolated(tmp_path,monkeypatch):
    builder,source,_=make_builder(tmp_path,monkeypatch,FakeAIProvider([]),lambda r:True)
    builder.notifications=NotificationService(FakeNotifier(fail=True))
    result=builder.build(source)
    assert result.build.success and result.status=='SUCCESS'
    assert builder.notifications.failures==['RuntimeError']


@pytest.mark.parametrize('raw,expected', [
 (' http://192.168.1.105:8000/// ','http://192.168.1.105:8000'),
 ('https://builder.example.com/','https://builder.example.com'),
 ('http://localhost:8000/','http://localhost:8000'),
 ('http://127.0.0.1:8000','http://127.0.0.1:8000'),
 ('https://builder.example.com/internal/','https://builder.example.com/internal')])
def test_base_url_persist_reload(tmp_path,raw,expected):
    store=SettingsStore(tmp_path/'settings.sqlite3');store.save({'base_url':raw})
    assert SettingsStore(store.path).effective()['base_url']==expected


@pytest.mark.parametrize('raw', ['javascript:alert(1)','file:///tmp','ftp://host','data:text/plain,a',
 'http://host/?abc=1','http://host/#test','http://host/?','http://host/#','http://0.0.0.0:8000',
 'http://[::]:8000','http://user:pass@host','http://host:99999','http://host:0','http://bad host','', 'http://host\\other'])
def test_base_url_invalid(raw):
    with pytest.raises(ValueError): normalize_base_url(raw)


@pytest.mark.parametrize('url,expected',[('http://localhost:8000',True),('http://127.0.0.1:8000',True),('http://127.2.3.4',True),('http://[::1]',True),('http://192.168.1.105:8000',False),('https://builder.example.com',False)])
def test_loopback_warning(url,expected):
    assert local_base_url(url)==expected


def test_base_url_api_and_redaction(tmp_path):
    app=create_app(tmp_path,admin_token='fixture-only')
    key=secrets.token_urlsafe(32);hook='https://example.invalid/'+secrets.token_urlsafe(32)
    with TestClient(app) as client:
        headers={'Authorization':'Bearer fixture-only'}
        r=client.post('/api/admin/settings',headers=headers,json={'base_url':' http://192.168.1.105:8000/ ','ai_api_key':key,'feishu_webhook':hook})
        assert r.status_code==200
        assert '后续通知' in r.json()['message']
        data=client.get('/api/admin/settings',headers=headers)
        assert data.json()['base_url']=='http://192.168.1.105:8000'
        assert data.json()['base_url_local'] is False
        assert key not in data.text and hook not in data.text
        assert client.post('/api/admin/settings',headers=headers,json={'base_url':'http://0.0.0.0:8000'}).status_code==400
        client.post('/api/admin/settings',headers=headers,json={'base_url':'http://localhost:8000'})
        assert client.get('/api/admin/settings',headers=headers).json()['base_url_local'] is True


def test_url_refresh_existing_builder(tmp_path):
    from builder import SmartBuilder
    store=SettingsStore(tmp_path/'settings.sqlite3')
    builder=SmartBuilder(tmp_path/'workspace',settings_store=store)
    builder.web_job_id='job-id'
    store.save({'base_url':'https://builder.example.com'})
    assert builder.notification_links()=={'details_url':'https://builder.example.com/?job=job-id','approval_url':'https://builder.example.com/admin'}


def _login_for_build(app, client, email='notify@example.com', *, test_plan=False):
    response = client.post(
        '/account/register',
        data={'username': email.split('@')[0], 'email': email, 'password': 'password123'},
        follow_redirects=False,
    )
    assert response.status_code == 303
    if test_plan:
        app.state.accounts.set_plan(email, 'TEST')
    session = app.state.accounts.session(client.cookies.get('builder_user'))
    return {'X-CSRF-Token': session['csrf']}


@pytest.mark.parametrize('scenario',['normal','repair','failed'])
def test_web_job_url_notification_integration(tmp_path,monkeypatch,scenario):
    fake=FakeNotifier()
    monkeypatch.setattr('builder.smart.NotificationService.configured',lambda settings:NotificationService(fake))
    monkeypatch.setattr('builder.smart.configured_provider',lambda settings:FakeAIProvider([response({'hidden_imports':['colorsys']})]*2))
    def build(engine,request):
        identifier=uuid.uuid4().hex
        workspace=engine.workspace_root/identifier;workspace.mkdir(parents=True)
        log=workspace/'build.log';log.write_text('fixture build')
        artifact=workspace/'main.exe';artifact.write_bytes(b'fixture')
        success=scenario=='normal' or scenario=='repair' and 'colorsys' in request.plan.hidden_imports
        return BuildResult(identifier,success,workspace,artifact if success else None,log,None if success else 'missing module')
    monkeypatch.setattr(BuildEngine,'build',build)
    app=create_app(tmp_path)
    app.state.settings.save({'base_url':'http://192.168.1.105:8000'})
    with TestClient(app) as client:
        headers = _login_for_build(app, client)
        job=client.post('/api/uploads',files={'file':('main.py',b'print(1)')}).json()
        assert client.post('/api/jobs/'+job['id']+'/build',data={'entry':'main.py'},headers=headers).status_code==200
        for _ in range(300):
            current=client.get('/api/jobs/'+job['id']).json()
            if current['terminal']: break
            time.sleep(.01)
        assert current['terminal']
        assert current['build_id']!=job['id']
        for event in fake.events:
            assert event['details_url']=='http://192.168.1.105:8000/?job='+job['id']
        assert [e['event'] for e in fake.events]==(['Build Success'] if scenario=='normal' else ['Build Failed','AI Repair Success' if scenario=='repair' else 'AI Repair Failed'])


def test_disabled_feishu_no_request(tmp_path,monkeypatch):
    from builder.settings import DEFAULTS
    called=[]
    monkeypatch.setattr('urllib.request.urlopen',lambda *args,**kwargs:called.append(True))
    service=NotificationService.configured(DEFAULTS | {'feishu_enabled':False,'feishu_webhook':'https://example.invalid/hook'})
    service.emit({'event':'Build Success'})
    assert called==[]


def test_outbound_notification_redaction_and_readability(monkeypatch):
    from builder.settings import DEFAULTS
    key=secrets.token_urlsafe(32)
    captured=[]
    def send(request,timeout):
        captured.append(json.loads(request.data)['content']['text'])
        return io.BytesIO(b'{"code":0}')
    monkeypatch.setattr('urllib.request.urlopen',send)
    service=NotificationService.configured(DEFAULTS | {'feishu_enabled':True,'feishu_webhook':'https://example.invalid/hook','ai_api_key':key})
    service.emit({'event':'Build Success','project':key,'build_id':'build-id','entry':'main.py','attempt_count':1,'status':'SUCCESS','details_url':'http://192.168.1.105:8000/?job=web-job','diagnoses':key,'api_key':key,'session_secret':key})
    assert key not in captured[0]
    assert '✅ 构建成功' in captured[0] and '尝试次数：1' in captured[0]
    assert '查看任务：' in captured[0] and 'web-job' in captured[0]
    assert 'diagnoses' not in captured[0]

def test_base_url_only_form_save_no_restart(tmp_path):
    app=create_app(tmp_path,admin_token='fixture-only')
    with TestClient(app) as client:
        headers={'Authorization':'Bearer fixture-only'}
        current=client.get('/api/admin/settings',headers=headers).json()
        result=client.post('/api/admin/settings',headers=headers,json={key:current[key] for key in ('allowed_hosts','retention_days')} | {'base_url':'https://builder.example.com'})
        assert result.status_code==200 and '重启' not in result.json()['message']
