import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from builder.settings import SettingsStore, allowed_hosts, MASK
from builder.ai import FakeAIProvider, OpenAICompatibleProvider
from builder.notifications import FakeNotifier, FeishuNotifier
from builder.smart import SmartBuilder
from web.app import create_app


@pytest.fixture
def configured(tmp_path, monkeypatch):
    # Host-related tests must not inherit deployment/LAN overrides from the
    # developer shell (for example BUILDER_ALLOWED_HOSTS='*').
    monkeypatch.delenv('BUILDER_ALLOWED_HOSTS', raising=False)
    monkeypatch.setenv('BUILDER_ADMIN_PASSWORD', 'test-password-only')
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.post('/admin/login', data={'password':'test-password-only'}, follow_redirects=False)
        assert response.status_code == 303
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', client.get('/admin/settings').text)[1]
        yield app, client, {'X-CSRF-Token': csrf}


def test_home_ui(configured):
    app, client, _ = configured
    page = client.get('/').text
    assert 'Smart Python Builder' in page and 'Python → Windows' in page
    assert 'id="download" disabled' in page
    assert 'id="current-project"' in page
    assert client.get('/static/home.js').status_code == 200
    home_js = client.get('/static/home.js').text
    assert 'scrollIntoView' in home_js
    assert 'renderCurrentProject' in home_js


@pytest.mark.parametrize('status,terminal,exists,expected', [
    ('READY',False,True,409),('QUEUED',False,True,409),('BUILDING',False,True,409),
    ('AI_DIAGNOSING',False,True,409),('AI_REPAIRING',False,True,409),('REBUILDING',False,True,409),
    ('FAILED',True,True,409),('NEEDS_MANUAL_REVIEW',True,True,409),('EXPIRED',True,True,409),
    ('SUCCESS',False,True,409),('SUCCESS',True,False,410),('SUCCESS',True,True,200)])
def test_download_state(configured, tmp_path, status, terminal, exists, expected):
    app, client, _ = configured
    artifact = tmp_path / 'demo.exe'
    if exists: artifact.write_bytes(b'EXE-test-fixture')
    app.state.jobs['test'] = dict(id='test', status=status, terminal=terminal, artifact=str(artifact))
    assert client.get('/api/jobs/test').json()['artifact_available'] == (expected == 200)
    for _ in range(2):
        assert client.get('/api/jobs/test/download').status_code == expected


@pytest.mark.parametrize('outside', [True,False])
def test_invalid_artifact(configured, tmp_path, outside):
    app, client, _ = configured
    target = tmp_path.parent / 'outside.exe' if outside else tmp_path / 'empty.exe'
    target.write_bytes(b'x' if outside else b'')
    app.state.jobs['test'] = dict(id='test',status='SUCCESS',terminal=True,artifact=str(target))
    assert client.get('/api/jobs/test/download').status_code == 410
    assert not client.get('/api/jobs/test').json()['artifact_available']


@pytest.mark.parametrize('raw,expected', [('localhost,127.0.0.1',['localhost','127.0.0.1']),(' localhost, , 192.168.1.105 ,',['localhost','192.168.1.105']),(' * ',['*'])])
def test_hosts(raw, expected):
    assert allowed_hosts(raw) == expected


@pytest.mark.parametrize('raw', ['', ' , ', 'http://localhost', 'localhost:8000', 'a..b', 'bad/host'])
def test_hosts_invalid(raw):
    with pytest.raises(ValueError): allowed_hosts(raw)


def test_session_login_logout(configured):
    app, client, headers = configured
    token = client.cookies.get('builder_admin')
    assert app.state.settings.session(token)
    assert client.get('/admin').status_code == 200
    assert client.post('/admin/logout', headers=headers).status_code == 200
    assert not app.state.settings.session(token)
    assert client.get('/admin/settings', follow_redirects=False).status_code == 303
    assert client.get('/api/admin/settings').status_code == 401
    client.cookies.set('builder_admin', token)
    assert client.get('/api/admin/settings').status_code == 401


def test_password_bootstrap_cookie_and_wrong_password(tmp_path, monkeypatch):
    monkeypatch.setenv('BUILDER_ADMIN_PASSWORD', 'temporary-password')
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.post('/admin/login', data={'password':'wrong'}).status_code == 401
        result = client.post('/admin/login', data={'password':'temporary-password'}, follow_redirects=False)
        assert result.status_code == 303
        cookie = result.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=lax' in cookie and 'secure;' not in cookie
        assert 'temporary-password' not in (tmp_path/'settings.sqlite3').read_bytes().decode('latin1')
    monkeypatch.setenv('BUILDER_ADMIN_PASSWORD', 'changed-env')
    assert SettingsStore(tmp_path/'settings.sqlite3').authenticate('temporary-password')
    assert not SettingsStore(tmp_path/'settings.sqlite3').authenticate('changed-env')


def test_uninitialized_and_unauthorized(tmp_path, monkeypatch):
    monkeypatch.delenv('BUILDER_ADMIN_PASSWORD', raising=False)
    with TestClient(create_app(tmp_path)) as client:
        assert '管理员尚未初始化' in client.get('/admin/login').text
        assert client.get('/admin/settings', follow_redirects=False).status_code == 303
        assert client.get('/api/admin/settings').status_code == 503


def test_settings_persist_mask_and_preserve(configured):
    app, client, headers = configured
    secrets = {'ai_api_key':'private-placeholder-key','feishu_webhook':'https://example.invalid/private-placeholder-hook'}
    result = client.post('/api/admin/settings', headers=headers, json=secrets | {'ai_model':'model-a','allowed_hosts':' localhost, 127.0.0.1, testserver ', 'retention_days':12})
    assert result.status_code == 200 and '重启' in result.json()['message']
    for path in ['/api/admin/settings','/admin/settings']:
        for value in secrets.values(): assert value not in client.get(path).text
    assert client.get('/api/admin/settings').json()['ai_api_key'] == MASK
    assert client.post('/api/admin/settings', headers=headers, json={'ai_model':'model-b','ai_api_key':MASK,'feishu_webhook':''}).status_code == 200
    reloaded = SettingsStore(app.state.settings.path).effective()
    assert reloaded['ai_model'] == 'model-b' and reloaded['retention_days'] == 12
    assert reloaded['allowed_hosts'] == 'localhost,127.0.0.1,testserver'
    for key,value in secrets.items(): assert reloaded[key] == value
    if __import__('os').name == 'nt':
        for value in secrets.values(): assert value.encode() not in app.state.settings.path.read_bytes()


def test_settings_drive_actual_builder(configured, tmp_path):
    app, client, headers = configured
    values = dict(ai_enabled=True, ai_model='saved-model', ai_api_key='placeholder', ai_base_url='https://example.invalid/v1',feishu_enabled=True,feishu_webhook='https://example.invalid/hook')
    assert client.post('/api/admin/settings',headers=headers,json=values).status_code == 200
    builder = SmartBuilder(tmp_path/'workspace',settings_store=app.state.settings)
    assert isinstance(builder.ai_provider, OpenAICompatibleProvider)
    assert builder.ai_provider.model == 'saved-model'
    assert isinstance(builder.notifications.notifier, FeishuNotifier)
    assert builder.notifications.notifier.webhook == values['feishu_webhook']
    client.post('/api/admin/settings',headers=headers,json={'ai_enabled':False,'feishu_enabled':False})
    builder = SmartBuilder(tmp_path/'workspace',settings_store=app.state.settings)
    assert builder.ai_provider is None and builder.notifications.notifier is None


def test_environment_override(configured, monkeypatch):
    app, client, headers = configured
    monkeypatch.setenv('BUILDER_AI_MODEL','override-model')
    response = client.post('/api/admin/settings',headers=headers,json={'ai_model':'saved-model'})
    assert response.json()['settings']['ai_model'] == 'override-model'
    assert 'ai_model' in response.json()['settings']['overridden']
    monkeypatch.delenv('BUILDER_AI_MODEL')
    assert app.state.settings.effective()['ai_model'] == 'saved-model'


@pytest.mark.parametrize('kind,fail',[('ai',False),('ai',True),('feishu',False),('feishu',True)])
def test_connection_fake(tmp_path, kind, fail):
    ai = FakeAIProvider([],fail=fail); notifier = FakeNotifier(fail=fail)
    app = create_app(tmp_path, admin_token='test-only',ai_factory=lambda values:ai,notifier_factory=lambda values:notifier)
    with TestClient(app) as client:
        response = client.post('/api/admin/settings/test-'+kind,headers={'Authorization':'Bearer test-only'},json={})
        assert response.status_code == (400 if fail else 200)
        if not fail and kind == 'feishu':
            assert notifier.events[0]['builder'] == 'Smart Python Builder'
            assert notifier.events[0]['message'] == '飞书通知测试成功'
            assert notifier.events[0]['time']


def test_csrf_origin_bearer_and_hosts(configured):
    app, client, headers = configured
    assert client.post('/api/admin/settings',json={'retention_days':4}).status_code == 403
    assert client.post('/api/admin/settings',headers=headers | {'Origin':'http://evil.invalid'},json={}).status_code == 403
    assert client.post('/api/admin/settings',headers=headers | {'Origin':'https://testserver'},json={}).status_code == 403
    assert client.post('/api/admin/settings',headers=headers | {'Origin':'http://testserver'},json={'retention_days':4}).status_code == 200
    assert client.get('/',headers={'Host':'evil.invalid'}).status_code == 400


@pytest.mark.parametrize('value', [' * ', ' localhost, 127.0.0.1, testserver ,'])
def test_host_middleware_environment(tmp_path, monkeypatch, value):
    monkeypatch.setenv('BUILDER_ALLOWED_HOSTS',value)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/').status_code == 200
        assert client.get('/',headers={'Host':'192.168.1.105'}).status_code == (200 if '*' in value else 400)


def test_session_expiry(configured):
    app, client, headers = configured
    with app.state.settings.connect() as db: db.execute('UPDATE sessions SET expires=0')
    assert client.get('/api/admin/settings').status_code == 401


def test_provider_error_redacted(configured, monkeypatch):
    app, client, headers = configured
    def broken(*args, **kwargs): raise RuntimeError('secret-body-and-key')
    monkeypatch.setattr('urllib.request.urlopen', broken)
    response = client.post('/api/admin/settings/test-ai',headers=headers,json={'ai_api_key':'test-secret','ai_model':'test'})
    assert response.status_code == 400
    assert 'secret' not in response.text


def test_login_throttle(configured):
    app, client, _ = configured
    for _ in range(10): assert client.post('/admin/login',data={'password':'wrong'}).status_code == 401
    assert client.post('/admin/login',data={'password':'wrong'}).status_code == 429

def test_session_experience_approve_and_reject(tmp_path, monkeypatch):
    from test_ai import make_builder, response
    monkeypatch.setenv('BUILDER_ADMIN_PASSWORD','experience-test')
    builder, source, calls = make_builder(tmp_path, monkeypatch, FakeAIProvider([response({'hidden_imports':['colorsys']})]), lambda request:'colorsys' in request.plan.hidden_imports)
    first = builder.build(source)
    second = builder.experience_store.candidate(first.analysis, first.attempts, first.plan)
    with TestClient(create_app(tmp_path)) as client:
        client.post('/admin/login',data={'password':'experience-test'})
        csrf = re.search(r'name="csrf-token" content="([^"]+)"',client.get('/admin').text)[1]
        headers = {'X-CSRF-Token':csrf}
        assert client.post('/api/admin/experiences/'+first.candidate_id,headers=headers,json={'decision':'APPROVED','repair_plan':response({'hidden_imports':['colorsys']})}).status_code == 200
        assert client.post('/api/admin/experiences/'+second,headers=headers,json={'decision':'REJECTED'}).status_code == 200
        assert {row['status'] for row in client.get('/api/admin/experiences').json()} == {'APPROVED','REJECTED'}


def test_minimal_ai_request_and_timeout(monkeypatch):
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,size): return b'{"choices":[{"message":{"content":"OK"}}]}'
    def request(req,timeout):
        calls.append((req,timeout)); return Response()
    monkeypatch.setattr('urllib.request.urlopen',request)
    OpenAICompatibleProvider('placeholder','https://example.invalid/v1','configured-model').test_connection()
    req,timeout = calls[0]
    assert timeout == 15 and req.full_url == 'https://example.invalid/v1/chat/completions'
    assert json.loads(req.data) == {'model':'configured-model','messages':[{'role':'user','content':'Reply OK.'}]}


def test_restart_required_hosts(tmp_path, monkeypatch):
    monkeypatch.delenv('BUILDER_ALLOWED_HOSTS', raising=False)
    app = create_app(tmp_path, admin_token='fixture')
    with TestClient(app) as client:
        assert client.post('/api/admin/settings',headers={'Authorization':'Bearer fixture'},json={'allowed_hosts':'localhost,testserver,192.168.1.100'}).status_code == 200
        assert client.get('/',headers={'Host':'192.168.1.100'}).status_code == 400
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/',headers={'Host':'192.168.1.100'}).status_code == 200


@pytest.mark.parametrize('payload', [{'retention_days':0},{'retention_days':True},{'ai_provider':'fake'},{'ai_api_key':123},{'allowed_hosts':''},{'ai_base_url':'https://user:pass@host/v1'},{'ai_enabled':True},{'feishu_enabled':True}])
def test_invalid_settings_atomic(configured,payload):
    app,client,headers = configured
    before = app.state.settings.saved()
    assert client.post('/api/admin/settings',headers=headers,json=payload).status_code == 400
    assert app.state.settings.saved() == before


def test_admin_user_management(configured):
    app, client, headers = configured
    first = app.state.accounts.create_user('free', 'password123', email='free@example.com')
    second = app.state.accounts.create_user('test', 'password123', email='test@example.com')

    users_page = client.get('/admin/users')
    assert users_page.status_code == 200
    assert '用户管理' in users_page.text
    assert '添加用户' in users_page.text
    assert 'new-user-username' in users_page.text
    assert '邮箱（选填）' in users_page.text
    assert 'password-modal' in users_page.text

    created = client.post(
        '/api/admin/users',
        headers=headers,
        json={
            'username': 'managed',
            'email':'managed@example.com',
            'password':'initial-password',
            'plan':'FREE',
            'remaining':12,
        },
    )
    assert created.status_code == 200
    assert created.json()['email'] == 'managed@example.com'
    assert created.json()['quota_remaining'] == 12
    managed_id = created.json()['id']
    assert app.state.accounts.authenticate('managed@example.com', 'initial-password')['id'] == managed_id

    listed = client.get('/api/admin/users').json()['users']
    assert {row['email'] for row in listed} >= {'free@example.com', 'test@example.com', 'managed@example.com'}

    reset_password = client.post(
        f'/api/admin/users/{managed_id}/password',
        headers=headers,
        json={'password':'replacement-password'},
    )
    assert reset_password.status_code == 200
    assert app.state.accounts.authenticate('managed@example.com', 'initial-password') is None
    assert app.state.accounts.authenticate('managed@example.com', 'replacement-password')['id'] == managed_id

    quota = client.post(
        f"/api/admin/users/{first['id']}/quota",
        headers=headers,
        json={'remaining': 25},
    )
    assert quota.status_code == 200
    assert quota.json()['quota_remaining'] == 25
    assert quota.json()['quota_total'] == 25

    changed = client.post(
        f"/api/admin/users/{first['id']}/plan",
        headers=headers,
        json={'plan':'TEST'},
    )
    assert changed.status_code == 200
    assert changed.json()['plan'] == 'TEST'
    assert changed.json()['quota_unlimited'] is True
    invalid_quota = client.post(
        f"/api/admin/users/{first['id']}/quota",
        headers=headers,
        json={'remaining': 10},
    )
    assert invalid_quota.status_code == 400
    assert 'TEST' in invalid_quota.json()['detail']

    disabled = client.post(
        f"/api/admin/users/{second['id']}/disabled",
        headers=headers,
        json={'disabled': True},
    )
    assert disabled.status_code == 200
    assert disabled.json()['disabled'] is True
    assert app.state.accounts.authenticate('test@example.com', 'password123') is None

    enabled = client.post(
        f"/api/admin/users/{second['id']}/disabled",
        headers=headers,
        json={'disabled': False},
    )
    assert enabled.status_code == 200
    assert enabled.json()['disabled'] is False

    app.state.accounts.consume_build(second['id'])
    reset = client.post(f"/api/admin/users/{second['id']}/quota/reset", headers=headers)
    assert reset.status_code == 200
    assert reset.json()['quota_used'] == 0
    assert reset.json()['quota_remaining'] == 3


def test_set_admin_password_replaces_existing_password_and_sessions(tmp_path):
    store = SettingsStore(tmp_path / 'settings.sqlite3')
    store.set_admin_password('first-password')
    token = store.new_session()
    assert store.session(token)
    assert store.authenticate('first-password')

    store.set_admin_password('second-password')
    assert not store.authenticate('first-password')
    assert store.authenticate('second-password')
    assert store.session(token) is None
