import io

import pytest
from fastapi.testclient import TestClient

from web.accounts import AccountStore
from web.app import create_app


def test_account_store_register_authenticate_and_quota(tmp_path):
    store = AccountStore(tmp_path / "accounts.sqlite3")
    user = store.create_user("User@Example.com", "password123")
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
    user = store.create_user("user@example.com", "password123")
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
            data={"email": "user@example.com", "password": "password123"},
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
    store.create_user("user@example.com", "password123")
    with pytest.raises(ValueError, match="已经注册"):
        store.create_user("USER@example.com", "password456")
