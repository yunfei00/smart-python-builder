import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from builder.notifications import FakeNotifier
from web.app import create_app


ADMIN_HEADERS = {'Authorization': 'Bearer admin-test-token'}


def register(client, username='user_01'):
    response = client.post(
        '/account/register',
        data={'username': username, 'password': 'password123'},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_admin_user_search_plan_state_filters_and_build_count(tmp_path):
    app = create_app(tmp_path, admin_token='admin-test-token')
    first = app.state.accounts.create_user('alpha_user', 'password123')
    second = app.state.accounts.create_user('beta_user', 'password123')
    app.state.accounts.set_plan_by_id(second['id'], 'TEST')
    app.state.accounts.set_disabled(second['id'], True)
    app.state.jobs['1' * 32] = {
        'id': '1' * 32, 'owner_id': first['id'], 'status': 'SUCCESS',
        'terminal': True, 'created_at': time.time(), 'started_at': time.time(),
    }
    app.state.jobs['2' * 32] = {
        'id': '2' * 32, 'owner_id': first['id'], 'status': 'FAILED',
        'terminal': True, 'created_at': time.time(), 'started_at': time.time(),
    }
    # These jobs are injected directly for this test, so mirror application
    # startup by backfilling the durable analytics ledger explicitly.
    app.state.analytics.backfill(app.state.jobs.values())

    with TestClient(app) as client:
        result = client.get('/api/admin/users?search=alpha', headers=ADMIN_HEADERS)
        assert result.status_code == 200
        data = result.json()
        assert data['summary']['total'] == 2
        assert [row['username'] for row in data['users']] == ['alpha_user']
        assert data['users'][0]['build_count'] == 2

        test_users = client.get('/api/admin/users?plan=TEST', headers=ADMIN_HEADERS).json()['users']
        assert [row['username'] for row in test_users] == ['beta_user']

        disabled = client.get('/api/admin/users?disabled=disabled', headers=ADMIN_HEADERS).json()['users']
        assert [row['username'] for row in disabled] == ['beta_user']


def test_admin_overview_build_queue_ai_disk_and_feedback_stats(tmp_path):
    app = create_app(tmp_path, admin_token='admin-test-token')
    user = app.state.accounts.create_user('stats_user', 'password123')
    now = time.time()
    app.state.jobs.update({
        '1' * 32: {
            'id': '1' * 32, 'owner_id': user['id'], 'status': 'SUCCESS',
            'terminal': True, 'created_at': now, 'started_at': now,
            'attempts': [
                {'number': 1, 'success': False, 'repair': {'retry': True}},
                {'number': 2, 'success': True},
            ],
        },
        '2' * 32: {
            'id': '2' * 32, 'owner_id': user['id'], 'status': 'FAILED',
            'terminal': True, 'created_at': now, 'started_at': now, 'attempts': [],
        },
        '3' * 32: {
            'id': '3' * 32, 'owner_id': user['id'], 'status': 'QUEUED',
            'terminal': False, 'created_at': now, 'started_at': now, 'attempts': [],
        },
        '4' * 32: {
            'id': '4' * 32, 'owner_id': user['id'], 'status': 'READY',
            'terminal': False, 'created_at': now,
        },
    })
    # Directly injected jobs do not pass through /build, therefore populate
    # the same durable ledger that production writes at build start/finish.
    app.state.analytics.backfill(app.state.jobs.values())
    uploads = tmp_path / 'uploads'
    uploads.mkdir(exist_ok=True)
    (uploads / 'sample.bin').write_bytes(b'x' * 2048)
    app.state.feedback_store.create(user, 'SUGGESTION', '希望增加运行状态统计')

    with TestClient(app) as client:
        response = client.get('/api/admin/overview', headers=ADMIN_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data['builds']['total'] == 3
        assert data['builds']['today'] == 3
        assert data['builds']['success'] == 1
        assert data['builds']['failed'] == 1
        assert data['builds']['success_rate'] == 50.0
        assert data['builds']['ai_repairs'] == 1
        assert data['queue']['queued'] == 1
        assert data['queue']['limit'] == 8
        assert data['queue']['workers'] == 1
        assert data['disk']['total_bytes'] >= 2048
        assert data['feedback']['new'] == 1


def test_manual_retention_cleanup_removes_only_expired_non_active_jobs(tmp_path):
    app = create_app(tmp_path, admin_token='admin-test-token')
    app.state.settings.save({'retention_days': 30})
    now = time.time()
    old = now - 40 * 86400

    old_id = 'a' * 32
    active_id = 'b' * 32
    recent_id = 'c' * 32
    build_id = 'd' * 32

    upload = tmp_path / 'uploads' / old_id
    upload.mkdir(parents=True)
    (upload / 'source.py').write_text('print(1)', encoding='utf-8')
    workspace = tmp_path / 'workspace' / build_id
    workspace.mkdir(parents=True)
    (workspace / 'artifact.exe').write_bytes(b'fake-artifact')

    old_job = {
        'id': old_id, 'status': 'SUCCESS', 'terminal': True,
        'created_at': old, 'started_at': old, 'finished_at': old,
        'build_id': build_id, 'attempts': [], 'owner_id': None,
    }
    active_job = {
        'id': active_id, 'status': 'BUILDING', 'terminal': False,
        'created_at': old, 'started_at': old, 'owner_id': None,
    }
    recent_job = {
        'id': recent_id, 'status': 'SUCCESS', 'terminal': True,
        'created_at': now, 'started_at': now, 'finished_at': now, 'owner_id': None,
    }
    with TestClient(app) as client:
        app.state.jobs.update({old_id: old_job, active_id: active_job, recent_id: recent_job})
        (tmp_path / f'{old_id}.json').write_text(json.dumps(old_job), encoding='utf-8')
        preview = client.get('/api/admin/maintenance/cleanup-preview', headers=ADMIN_HEADERS)
        assert preview.status_code == 200
        assert preview.json()['count'] == 1
        assert preview.json()['bytes'] > 0

        cleaned = client.post('/api/admin/maintenance/cleanup', headers=ADMIN_HEADERS)
        assert cleaned.status_code == 200
        assert cleaned.json()['count'] == 1
        assert old_id not in app.state.jobs
        assert active_id in app.state.jobs
        assert recent_id in app.state.jobs
        assert not upload.exists()
        assert not workspace.exists()
        assert not (tmp_path / f'{old_id}.json').exists()


def test_user_feedback_is_persisted_notified_and_visible_to_admin(tmp_path):
    notifier = FakeNotifier()
    app = create_app(
        tmp_path,
        admin_token='admin-test-token',
        notifier_factory=lambda values: notifier,
    )
    app.state.settings.save({
        'feishu_enabled': True,
        'feishu_webhook': 'https://example.invalid/hook',
        'feedback_notifications': True,
    })

    with TestClient(app) as client:
        register(client, 'voice_user')
        session = app.state.accounts.session(client.cookies.get('builder_user'))
        response = client.post(
            '/feedback',
            data={
                'category': 'SUGGESTION',
                'message': '希望增加更清楚的构建统计。',
                'csrf': session['csrf'],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers['location'] == '/feedback?submitted=1'
        assert len(notifier.events) == 1
        assert notifier.events[0]['event'] == 'User Feedback'
        assert notifier.events[0]['username'] == 'voice_user'

        page = client.get('/feedback')
        assert page.status_code == 200
        assert '希望增加更清楚的构建统计。' in page.text
        assert '功能建议' in page.text

        inbox = client.get('/api/admin/feedback?status=NEW', headers=ADMIN_HEADERS)
        assert inbox.status_code == 200
        item = inbox.json()['items'][0]
        assert item['username'] == 'voice_user'
        assert item['notified'] == 1

        resolved = client.post(
            f"/api/admin/feedback/{item['id']}/status",
            headers=ADMIN_HEADERS,
            json={'status': 'RESOLVED'},
        )
        assert resolved.status_code == 200
        assert resolved.json()['status'] == 'RESOLVED'


def test_feedback_notification_can_be_disabled_without_losing_feedback(tmp_path):
    notifier = FakeNotifier()
    app = create_app(
        tmp_path,
        admin_token='admin-test-token',
        notifier_factory=lambda values: notifier,
    )
    app.state.settings.save({
        'feishu_enabled': True,
        'feishu_webhook': 'https://example.invalid/hook',
        'feedback_notifications': False,
    })

    with TestClient(app) as client:
        register(client, 'quiet_user')
        session = app.state.accounts.session(client.cookies.get('builder_user'))
        response = client.post(
            '/feedback',
            data={'category': 'OTHER', 'message': '仅保存在后台。', 'csrf': session['csrf']},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert notifier.events == []
        items = client.get('/api/admin/feedback', headers=ADMIN_HEADERS).json()['items']
        assert len(items) == 1
        assert items[0]['notified'] == 0


def test_user_facing_username_placeholders_have_no_personal_name(tmp_path, monkeypatch):
    monkeypatch.setenv('BUILDER_ADMIN_PASSWORD', 'admin-password')
    app = create_app(tmp_path)
    with TestClient(app) as client:
        register_page = client.get('/account/register').text
        assert 'user_01' in register_page
        assert 'yunfei' not in register_page.lower()
        assert '云飞' not in register_page

        client.post('/admin/login', data={'password': 'admin-password'})
        users_page = client.get('/admin/users').text
        assert 'user_01' in users_page
        assert 'yunfei' not in users_page.lower()
        assert '云飞' not in users_page
