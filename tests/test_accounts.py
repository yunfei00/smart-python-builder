import io
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from web.accounts import AccountStore
from web.app import create_app


def test_account_store_register_authenticate_and_quota(tmp_path):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    user = store.create_user('User', "password123", email='User@Example.com')
    assert user["email"] == "user@example.com"
    assert user["plan"] == "FREE"
    assert user["quota_remaining"] == 3
    assert store.authenticate("user@example.com", "wrong-password") is None
    assert store.authenticate("USER@example.com", "password123")["id"] == user["id"]

    assert store.consume_build(user["id"])["quota_remaining"] == 2
    assert store.consume_build(user["id"])["quota_remaining"] == 1
    assert store.consume_build(user["id"])["quota_remaining"] == 0
    with pytest.raises(ValueError, match="额度"):
        store.consume_build(user["id"])


def test_account_sessions_logout(tmp_path):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    user = store.create_user('user', "password123", email='user@example.com')
    token, csrf = store.new_session(user["id"])
    session = store.session(token)
    assert session["id"] == user["id"]
    assert session["csrf"] == csrf
    store.logout(token)
    assert store.session(token) is None


def test_customer_register_dashboard_and_owned_upload(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/account/register").status_code == 200
        response = client.post(
            "/account/register",
            data={'username': 'user', "email": "user@example.com", "password": "password123"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/dashboard"
        assert client.cookies.get("builder_user")

        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "3 次免费构建" in dashboard.text

        upload = client.post(
            "/api/uploads",
            files={"file": ("hello.py", io.BytesIO(b"print('hello')"), "text/x-python")},
        )
        assert upload.status_code == 200
        job = upload.json()
        assert job["owner_id"]

        dashboard = client.get("/dashboard")
        assert "hello" in dashboard.text
        assert "READY" in dashboard.text


def test_dashboard_requires_login(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/account/login"


def test_duplicate_email_rejected(tmp_path):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    store.create_user('user', "password123", email='user@example.com')
    with pytest.raises(ValueError, match="已经注册"):
        store.create_user('another-user', "password456", email='USER@example.com')


def test_test_plan_has_unlimited_builds_and_can_return_to_free(tmp_path):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    user = store.create_user('tester', "password123", email='tester@example.com')

    test_user = store.set_plan(user["email"], "TEST")
    assert test_user["plan"] == "TEST"
    assert test_user["quota_unlimited"] is True
    assert test_user["quota_remaining"] is None

    for _ in range(10):
        current = store.consume_build(user["id"])
        assert current["plan"] == "TEST"
        assert current["quota_used"] == 0
        assert current["quota_unlimited"] is True

    free_user = store.set_plan(user["email"], "FREE")
    assert free_user["plan"] == "FREE"
    assert free_user["quota_total"] == 3
    assert free_user["quota_used"] == 0
    assert free_user["quota_remaining"] == 3


def test_test_plan_dashboard_shows_unlimited_quota(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/account/register",
            data={'username': 'tester', "email": "tester@example.com", "password": "password123", "plan": "TEST"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        store = app.state.accounts
        registered = store.authenticate("tester@example.com", "password123")
        assert registered["plan"] == "FREE"

        store.set_plan("tester@example.com", "TEST")
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "TEST" in dashboard.text
        assert "∞" in dashboard.text
        assert "无限构建" in dashboard.text


def test_free_account_cannot_import_after_quota_is_exhausted(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/account/register",
            data={'username': 'quota', "email": "quota@example.com", "password": "password123"},
            follow_redirects=False,
        )
        user = app.state.accounts.authenticate("quota@example.com", "password123")
        for _ in range(3):
            app.state.accounts.consume_build(user["id"])

        response = client.post(
            "/api/uploads",
            files={"file": ("blocked.py", io.BytesIO(b"print('blocked')"), "text/x-python")},
        )
        assert response.status_code == 402
        assert "额度已用完" in response.json()["detail"]

        home = client.get("/")
        assert home.status_code == 200
        assert "当前没有可用构建额度" in home.text
        assert "disabled" in home.text


def test_ready_jobs_reserve_remaining_free_quota(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/account/register",
            data={'username': 'reserved', "email": "reserved@example.com", "password": "password123"},
            follow_redirects=False,
        )
        for index in range(3):
            response = client.post(
                "/api/uploads",
                files={"file": (f"job{index}.py", io.BytesIO(b"print('ready')"), "text/x-python")},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "READY"

        blocked = client.post(
            "/api/uploads",
            files={"file": ("job4.py", io.BytesIO(b"print('blocked')"), "text/x-python")},
        )
        assert blocked.status_code == 402
        assert "READY" in blocked.json()["detail"]


def test_test_account_can_create_more_than_free_ready_limit(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        client.post(
            "/account/register",
            data={'username': 'internal', "email": "internal@example.com", "password": "password123"},
            follow_redirects=False,
        )
        app.state.accounts.set_plan("internal@example.com", "TEST")

        for index in range(5):
            response = client.post(
                "/api/uploads",
                files={"file": (f"job{index}.py", io.BytesIO(b"print('test')"), "text/x-python")},
            )
            assert response.status_code == 200


def _registered_client(app, client, email='jobs@example.com'):
    response = client.post(
        '/account/register',
        data={'username': email.split('@')[0], 'email': email, 'password': 'password123'},
        follow_redirects=False,
    )
    assert response.status_code == 303
    token = client.cookies.get('builder_user')
    session = app.state.accounts.session(token)
    return session, {'X-CSRF-Token': session['csrf']}


def test_user_can_delete_ready_project_and_release_reserved_slot(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        user, headers = _registered_client(app, client)
        response = client.post(
            '/api/uploads',
            files={'file': ('delete-me.py', io.BytesIO(b"print('ok')"), 'text/x-python')},
        )
        assert response.status_code == 200
        job = response.json()
        assert job['status'] == 'READY'
        source = Path(job['source'])
        metadata = tmp_path / f"{job['id']}.json"
        assert source.exists()
        assert metadata.exists()

        deleted = client.delete(f"/api/jobs/{job['id']}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json()['deleted'] is True
        assert job['id'] not in app.state.jobs
        assert not metadata.exists()
        assert not (tmp_path / 'uploads' / job['id']).exists()

        # Deleting READY must release its reserved import slot without consuming quota.
        account = app.state.accounts.get_user(user['id'])
        assert account['quota_remaining'] == 3
        replacement = client.post(
            '/api/uploads',
            files={'file': ('replacement.py', io.BytesIO(b"print('ok')"), 'text/x-python')},
        )
        assert replacement.status_code == 200


def test_delete_rejects_another_users_project(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as owner:
        first, _ = _registered_client(app, owner, 'owner@example.com')
        job = owner.post(
            '/api/uploads',
            files={'file': ('private.py', io.BytesIO(b"print('private')"), 'text/x-python')},
        ).json()

    with TestClient(app) as other:
        _, headers = _registered_client(app, other, 'other@example.com')
        response = other.delete(f"/api/jobs/{job['id']}", headers=headers)
        assert response.status_code == 404
        assert job['id'] in app.state.jobs


def test_user_can_cancel_running_build_then_delete_it(tmp_path):
    class Plan:
        def to_dict(self):
            return {'entry_point': 'demo.py', 'mode': 'onefile', 'app_type': 'cli'}

    class SlowBuilder:
        started = threading.Event()

        def __init__(self, workspace_root):
            self.workspace_root = Path(workspace_root)
            self.engine = SimpleNamespace(on_created=None)
            self.on_state = None
            self.web_job_id = None
            self.cancelled = threading.Event()

        def cancel(self):
            self.cancelled.set()

        def build(self, source, *, entry_point=None, mode='onefile'):
            build_id = 'b' * 32
            workspace = self.workspace_root / build_id
            workspace.mkdir(parents=True, exist_ok=True)
            log_file = workspace / 'build.log'
            log_file.write_text('fake build running\n', encoding='utf-8')
            if self.engine.on_created:
                self.engine.on_created(build_id, log_file)
            SlowBuilder.started.set()
            self.cancelled.wait(timeout=5)
            build = SimpleNamespace(
                build_id=build_id,
                success=False,
                workspace=workspace,
                artifact=None,
                log_file=log_file,
                error='Build cancelled by user',
            )
            return SimpleNamespace(
                build=build,
                plan=Plan(),
                status='CANCELED',
                attempts=[],
            )

    app = create_app(tmp_path, builder_factory=SlowBuilder)
    with TestClient(app) as client:
        user, headers = _registered_client(app, client, 'cancel@example.com')
        source = tmp_path / 'demo.py'
        source.write_text("print('demo')", encoding='utf-8')
        job_id = 'a' * 32
        app.state.jobs[job_id] = {
            'id': job_id,
            'status': 'READY',
            'source': str(source),
            'entries': ['demo.py'],
            'entry': 'demo.py',
            'dependencies': [],
            'dependency_source': None,
            'plan': None,
            'created_at': time.time(),
            'terminal': False,
            'source_type': 'upload',
            'owner_id': user['id'],
            'project_name': 'demo',
        }

        started = client.post(
            f'/api/jobs/{job_id}/build',
            data={'entry': 'demo.py', 'mode': 'onefile'},
            headers=headers,
        )
        assert started.status_code == 200
        assert SlowBuilder.started.wait(timeout=2)

        cannot_delete = client.delete(f'/api/jobs/{job_id}', headers=headers)
        assert cannot_delete.status_code == 409
        assert '先取消' in cannot_delete.json()['detail']

        canceled = client.post(f'/api/jobs/{job_id}/cancel', headers=headers)
        assert canceled.status_code == 200
        assert canceled.json()['status'] in {'CANCELING', 'CANCELED'}

        deadline = time.time() + 3
        while time.time() < deadline and not app.state.jobs[job_id].get('terminal'):
            time.sleep(0.05)
        assert app.state.jobs[job_id]['status'] == 'CANCELED'
        assert app.state.jobs[job_id]['terminal'] is True
        # A running build has already consumed resources, so its FREE quota is not refunded.
        assert app.state.accounts.get_user(user['id'])['quota_remaining'] == 2

        deleted = client.delete(f'/api/jobs/{job_id}', headers=headers)
        assert deleted.status_code == 200
        assert job_id not in app.state.jobs
        assert not (tmp_path / 'workspace' / ('b' * 32)).exists()


def test_free_quota_can_be_refunded_for_pre_execution_cancel(tmp_path):
    store = AccountStore(tmp_path / 'accounts.sqlite3')
    user = store.create_user('refund', 'password123', email='refund@example.com')
    store.consume_build(user['id'])
    assert store.get_user(user['id'])['quota_remaining'] == 2
    refunded = store.refund_build(user['id'])
    assert refunded['quota_remaining'] == 3
    assert refunded['quota_used'] == 0


def test_guest_can_analyze_but_build_requires_login_and_resumes_after_login(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        upload = client.post(
            '/api/uploads',
            files={'file': ('guest.py', io.BytesIO(b"print('guest')"), 'text/x-python')},
        )
        assert upload.status_code == 200
        job = upload.json()
        assert job['status'] == 'READY'
        assert job['owner_id'] is None

        denied = client.post(
            f"/api/jobs/{job['id']}/build",
            data={'entry': 'guest.py', 'mode': 'onefile'},
        )
        assert denied.status_code == 401
        assert '登录' in denied.json()['detail']
        assert app.state.jobs[job['id']]['status'] == 'READY'

        next_url = f"/?job={job['id']}#project"
        login = client.get('/account/login', params={'next': next_url})
        assert login.status_code == 200
        assert f'value="{next_url}"' in login.text

        app.state.accounts.create_user('resume', 'password123', email='resume@example.com')
        signed_in = client.post(
            '/account/login',
            data={'email': 'resume@example.com', 'password': 'password123', 'next': next_url},
            follow_redirects=False,
        )
        assert signed_in.status_code == 303
        assert signed_in.headers['location'] == next_url

        resumed = client.get(f"/api/jobs/{job['id']}")
        assert resumed.status_code == 200
        assert resumed.json()['status'] == 'READY'

        session = app.state.accounts.session(client.cookies.get('builder_user'))
        claimed = client.post(
            f"/api/jobs/{job['id']}/claim",
            headers={'X-CSRF-Token': session['csrf']},
        )
        assert claimed.status_code == 200
        assert claimed.json()['owner_id'] == session['id']
        assert job['id'] in client.get('/dashboard').text


def test_auth_next_rejects_external_redirects(tmp_path):
    app = create_app(tmp_path)
    app.state.accounts.create_user('safe', 'password123', email='safe@example.com')
    with TestClient(app) as client:
        response = client.post(
            '/account/login',
            data={
                'email': 'safe@example.com',
                'password': 'password123',
                'next': 'https://evil.example/phish',
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers['location'] == '/dashboard'


def test_customer_can_change_password_and_keep_fresh_session(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        user, _ = _registered_client(app, client, 'password@example.com')
        current = app.state.accounts.session(client.cookies.get('builder_user'))
        settings = client.get('/account/settings')
        assert settings.status_code == 200
        assert '修改密码' in settings.text

        mismatch = client.post(
            '/account/password',
            data={
                'current_password': 'password123',
                'new_password': 'new-password-123',
                'confirm_password': 'different-password',
                'csrf': current['csrf'],
            },
        )
        assert mismatch.status_code == 400
        assert '不一致' in mismatch.text

        changed = client.post(
            '/account/password',
            data={
                'current_password': 'password123',
                'new_password': 'new-password-123',
                'confirm_password': 'new-password-123',
                'csrf': current['csrf'],
            },
            follow_redirects=False,
        )
        assert changed.status_code == 303
        assert changed.headers['location'] == '/account/settings?changed=1'
        assert app.state.accounts.authenticate('password@example.com', 'password123') is None
        assert app.state.accounts.authenticate('password@example.com', 'new-password-123')['id'] == user['id']
        assert client.get('/account/settings').status_code == 200


def test_claiming_guest_project_respects_reserved_free_quota(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        user, headers = _registered_client(app, client, 'reserved-claim@example.com')
        source = tmp_path / 'guest.py'
        source.write_text("print('guest')", encoding='utf-8')

        for index in range(3):
            app.state.jobs[f'{index + 1:032x}'] = {
                'id': f'{index + 1:032x}',
                'status': 'READY',
                'source': str(source),
                'entries': ['guest.py'],
                'entry': 'guest.py',
                'dependencies': [],
                'dependency_source': None,
                'plan': None,
                'created_at': time.time(),
                'terminal': False,
                'source_type': 'upload',
                'owner_id': user['id'],
                'project_name': f'owned-{index}',
            }

        guest_id = 'f' * 32
        app.state.jobs[guest_id] = {
            'id': guest_id,
            'status': 'READY',
            'source': str(source),
            'entries': ['guest.py'],
            'entry': 'guest.py',
            'dependencies': [],
            'dependency_source': None,
            'plan': None,
            'created_at': time.time(),
            'terminal': False,
            'source_type': 'upload',
            'owner_id': None,
            'project_name': 'guest',
        }

        response = client.post(
            f'/api/jobs/{guest_id}/build',
            data={'entry': 'guest.py', 'mode': 'onefile'},
            headers=headers,
        )
        assert response.status_code == 402
        assert app.state.jobs[guest_id]['owner_id'] is None


def test_managed_user_creation_and_admin_password_reset(tmp_path):
    store = AccountStore(tmp_path / 'accounts.sqlite3')
    free_user = store.create_managed_user(
        'managed',
        'initial-password', email='managed@example.com',
        plan='FREE',
        remaining=15,
    )
    assert free_user['plan'] == 'FREE'
    assert free_user['quota_remaining'] == 15

    test_user = store.create_managed_user(
        'internal-managed',
        'initial-password', email='internal-managed@example.com',
        plan='TEST',
        remaining=999,
    )
    assert test_user['plan'] == 'TEST'
    assert test_user['quota_unlimited'] is True

    token, _ = store.new_session(free_user['id'])
    assert store.session(token)
    store.reset_password(free_user['id'], 'replacement-password')
    assert store.authenticate('managed@example.com', 'initial-password') is None
    assert store.authenticate('managed@example.com', 'replacement-password')['id'] == free_user['id']
    assert store.session(token) is None


def test_upload_job_keeps_project_filename_for_ready_summary(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            '/api/uploads',
            files={'file': ('example-tool.py', io.BytesIO(b"print('ok')"), 'text/x-python')},
        )
        assert response.status_code == 200
        job = response.json()
        assert job['project_name'] == 'example-tool'
        assert job['upload_filename'] == 'example-tool.py'
        assert job['source_type'] == 'upload'
