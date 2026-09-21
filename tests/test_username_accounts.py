import hashlib
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from web.accounts import AccountStore, _password_hash
from web.app import create_app


@pytest.mark.parametrize('email', [None, '', '   '])
def test_username_only_account_uses_null_email(tmp_path, email):
    store = AccountStore(tmp_path / 'accounts.sqlite3')
    user = store.create_user('YunFei', 'password123', email=email)
    assert user['username'] == 'yunfei'
    assert user['email'] is None
    assert user['quota_remaining'] == 3
    assert 'password_hash' not in user
    with store.connect() as db:
        row = db.execute('SELECT * FROM users').fetchone()
        assert row['email'] is None
        assert row['password_hash'] != 'password123'
        assert ':' in row['password_hash']
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE users SET username=NULL')
    assert store.authenticate('YUNFEI', 'password123')['id'] == user['id']
    with pytest.raises(ValueError, match='该用户名已被使用'):
        store.create_user('yunfei', 'password123')
    other = store.create_user('another', 'password123')
    assert other['email'] is None
    with store.connect() as db, pytest.raises(sqlite3.IntegrityError):
        db.execute('UPDATE users SET username=? WHERE id=?', ('YUNFEI', other['id']))


@pytest.mark.parametrize('name', ['ab', '张三', 'yunfei', 'yunfei_01', 'python-builder', '云飞', '云飞01', 'a' * 32])
def test_valid_usernames(tmp_path, name):
    store = AccountStore(tmp_path / 'accounts.sqlite3')
    user = store.create_user(name, 'password123')
    assert store.authenticate(name, 'password123')['id'] == user['id']


@pytest.mark.parametrize('name', ['', 'a', '云', 'yun fei', 'abc@test', 'user!', '/admin',
                                 ' yunfei', 'yunfei ', 'user\n', 'a' * 33, 'ééé', '😀用户', None, 123])
def test_invalid_usernames(tmp_path, name):
    store = AccountStore(tmp_path / 'accounts.sqlite3')
    with pytest.raises(ValueError, match='用户名'):
        store.create_user(name, 'password123')


def test_email_login_uniqueness_and_input_limits(tmp_path):
    store = AccountStore(tmp_path / 'accounts.sqlite3')
    user = store.create_user('yunfei', 'password123', email='You@Example.com')
    assert store.authenticate('YOU@example.com', 'password123')['id'] == user['id']
    with pytest.raises(ValueError, match='该邮箱已经注册'):
        store.create_user('other', 'password123', email='you@example.com')
    for email in ['invalid', 'a' * 255 + '@example.com', 123, []]:
        with pytest.raises(ValueError, match='邮箱'):
            store.create_user('other', 'password123', email=email)
    for login in ['a' * 255, "' OR 1=1 --", 'missing', 'missing@example.com', None]:
        assert store.authenticate(login, 'password123') is None


def legacy_database(path):
    password_hash = _password_hash('legacy-password')
    emails = ['222@1.com', 'yunfei@one.com', 'YUNFEI@two.com', 'yunfei@three.com',
              'ab@one.com', 'bad.name@one.com', 'a' * 32 + '@one.com', 'a' * 32 + '@two.com']
    rows = []
    with sqlite3.connect(path) as db:
        db.execute('''CREATE TABLE users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'FREE', quota_total INTEGER NOT NULL DEFAULT 3,
            quota_used INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
            disabled INTEGER NOT NULL DEFAULT 0)''')
        db.execute('''CREATE TABLE user_sessions (
            token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL,
            expires REAL NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))''')
        for i, email in enumerate(emails):
            row = (f'{i + 1:08x}' + '0' * 24, email, password_hash,
                   'TEST' if i == 1 else 'FREE', 17 + i, i, 1000.0 + i, int(i == 3))
            rows.append(row)
            db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)', row)
            db.execute('INSERT INTO user_sessions VALUES (?,?,?,?)',
                       (hashlib.sha256(f'token-{i}'.encode()).hexdigest(), row[0], f'csrf-{i}', time.time() + 3600))
    return rows


def test_real_legacy_schema_migration_preserves_users_and_sessions(tmp_path):
    path = tmp_path / 'accounts.sqlite3'
    original = legacy_database(path)
    store = AccountStore(path)
    expected_names = ['222', 'yunfei', 'yunfei_2', 'yunfei_3', 'ab',
                      'user_00000006', 'a' * 32, 'a' * 30 + '_2']
    with store.connect() as db:
        columns = {row['name']: row for row in db.execute('PRAGMA table_info(users)')}
        assert columns['username']['notnull'] == 1
        assert columns['email']['notnull'] == 0
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert db.execute('SELECT COUNT(*) FROM user_sessions').fetchone()[0] == len(original)
        before = [tuple(row) for row in db.execute('SELECT * FROM users ORDER BY created_at')]
        for i, old in enumerate(original):
            row = db.execute('SELECT * FROM users WHERE id=?', (old[0],)).fetchone()
            assert tuple(row[key] for key in ('id', 'email', 'password_hash', 'plan', 'quota_total',
                                              'quota_used', 'created_at', 'disabled')) == old
            assert row['username'] == expected_names[i]
            if old[-1]:
                assert store.authenticate(old[1], 'legacy-password') is None
                assert store.authenticate(row['username'], 'legacy-password') is None
                assert store.session(f'token-{i}') is None
            else:
                assert store.authenticate(old[1], 'legacy-password')['id'] == old[0]
                assert store.authenticate(row['username'], 'legacy-password')['id'] == old[0]
                assert store.session(f'token-{i}')['id'] == old[0]
                assert store.session(f'token-{i}')['csrf'] == f'csrf-{i}'
    for _ in range(2):
        store = AccountStore(path)
    with store.connect() as db:
        assert [tuple(row) for row in db.execute('SELECT * FROM users ORDER BY created_at')] == before
    assert store.create_user('new-user', 'password123')['email'] is None


def test_migration_failure_rolls_back_schema_and_data(tmp_path, monkeypatch):
    path = tmp_path / 'accounts.sqlite3'
    original = legacy_database(path)
    def fail(username):
        raise RuntimeError('migration interrupted')
    with monkeypatch.context() as patch:
        patch.setattr(AccountStore, 'normalize_username', staticmethod(fail))
        with pytest.raises(RuntimeError):
            AccountStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM users ORDER BY created_at').fetchall() == original
        assert 'username' not in [row[1] for row in db.execute('PRAGMA table_info(users)')]
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='users_upgrade'").fetchall()
    assert AccountStore(path).authenticate('222', 'legacy-password')


@pytest.mark.parametrize('email', [None, 'you@example.com'])
def test_registration_login_and_account_pages(tmp_path, email):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        data = {'username': '云飞01', 'password': 'password123'}
        if email:
            data['email'] = email
        response = client.post('/account/register', data=data, follow_redirects=False)
        assert response.status_code == 303
        assert 'HttpOnly' in response.headers['set-cookie']
        assert 'SameSite=lax' in response.headers['set-cookie']
        token = client.cookies.get('builder_user')
        user = app.state.accounts.session(token)
        assert user['quota_remaining'] == 10000
        for url in ['/dashboard', '/account/settings']:
            page = client.get(url)
            assert '云飞01' in page.text
            assert (email or '未绑定邮箱') in page.text
        assert client.post('/account/logout', data={'csrf': user['csrf']}, follow_redirects=False).status_code == 303
        for login in ['云飞01'] + ([email] if email else []):
            response = client.post('/account/login', data={'login': login, 'password': 'password123'}, follow_redirects=False)
            assert response.status_code == 303
            client.cookies.clear()
        if email:
            assert client.post('/account/login', data={'email': email, 'password': 'password123'}, follow_redirects=False).status_code == 303


def test_registration_errors_and_uniform_login_errors(tmp_path):
    app = create_app(tmp_path)
    app.state.accounts.create_user('yunfei', 'password123', email='you@example.com')
    with TestClient(app) as client:
        for data, message in [
            ({'username': 'YUNFEI'}, '该用户名已被使用'),
            ({'username': 'another', 'email': 'YOU@example.com'}, '该邮箱已经注册'),
            ({'email': 'new@example.com'}, '用户名'),
        ]:
            response = client.post('/account/register', data={**data, 'password': 'password123'})
            assert message in response.text
            assert not client.cookies.get('builder_user')
        for login, password in [('yunfei', 'wrong-password'), ('absent', 'password123'),
                                ('absent@example.com', 'password123')]:
            response = client.post('/account/login', data={'login': login, 'password': password})
            assert '用户名、邮箱或密码不正确' in response.text
        page = client.get('/account/login').text
        assert '用户名 / 邮箱' in page and 'name="login"' in page
        assert 'type="email"' not in page


@pytest.mark.parametrize('email', [None, 'managed@example.com'])
def test_username_account_admin_operations_and_security(tmp_path, email):
    app = create_app(tmp_path, admin_token='test-admin-token')
    headers = {'Authorization': 'Bearer test-admin-token'}
    with TestClient(app) as client:
        payload = {'username': 'managed', 'password': 'password123', 'email': email, 'remaining': 12}
        assert client.post('/api/admin/users', json=payload).status_code in (401, 403)
        created = client.post('/api/admin/users', json=payload, headers=headers)
        assert created.status_code == 200
        user = created.json()
        assert user['username'] == 'managed' and user['email'] == email
        assert user['quota_remaining'] == 12 and 'password_hash' not in user
        listed = client.get('/api/admin/users', headers=headers).json()['users']
        assert listed[0]['username'] == 'managed' and listed[0]['email'] == email
        token, csrf = app.state.accounts.new_session(user['id'])
        client.cookies.set('builder_user', token)
        assert client.post('/api/admin/users', json=payload, headers={'X-CSRF-Token': csrf}).status_code in (401, 403)
        url = '/api/admin/users/' + user['id']
        assert client.post(url + '/password', json={'password': 'replacement-password'}, headers=headers).status_code == 200
        assert app.state.accounts.session(token) is None
        assert app.state.accounts.authenticate('managed', 'password123') is None
        assert app.state.accounts.authenticate('managed', 'replacement-password')['id'] == user['id']
        assert client.post(url + '/plan', json={'plan': 'TEST'}, headers=headers).json()['quota_unlimited']
        assert client.post(url + '/plan', json={'plan': 'FREE'}, headers=headers).json()['quota_remaining'] == 10000
        assert client.post(url + '/quota', json={'remaining': 25}, headers=headers).json()['quota_remaining'] == 25
        token, _ = app.state.accounts.new_session(user['id'])
        client.post(url + '/disabled', json={'disabled': True}, headers=headers)
        assert app.state.accounts.session(token) is None
        assert app.state.accounts.authenticate('managed', 'replacement-password') is None
