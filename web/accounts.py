"""Customer accounts, sessions, and free-build quota."""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

USER_COOKIE = "builder_user"
SESSION_SECONDS = 7 * 24 * 60 * 60
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _password_hash(password: str) -> str:
    if not 8 <= len(password) <= 128:
        raise ValueError("密码长度需要 8–128 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1).hex()
    return salt.hex() + ":" + digest


def _verify(password: str, stored: str) -> bool:
    if len(password) > 128:
        return False
    try:
        salt, expected = stored.split(":", 1)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


class AccountStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'FREE',
                    quota_total INTEGER NOT NULL DEFAULT 3,
                    quota_used INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    disabled INTEGER NOT NULL DEFAULT 0
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS user_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    csrf TEXT NOT NULL,
                    expires REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )"""
            )

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def normalize_email(email: str) -> str:
        email = (email or "").strip().lower()
        if len(email) > 254 or not _EMAIL.fullmatch(email):
            raise ValueError("请输入有效邮箱地址")
        return email

    def create_user(self, email: str, password: str) -> dict:
        email = self.normalize_email(email)
        identifier = uuid.uuid4().hex
        password_hash = _password_hash(password)
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO users(id,email,password_hash,created_at) VALUES (?,?,?,?)",
                    (identifier, email, password_hash, time.time()),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该邮箱已经注册") from exc
        return self.get_user(identifier)

    def authenticate(self, email: str, password: str) -> dict | None:
        try:
            email = self.normalize_email(email)
        except ValueError:
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM users WHERE email=? AND disabled=0", (email,)
            ).fetchone()
        if not row or not _verify(password, row["password_hash"]):
            return None
        return self._public(row)

    def get_user(self, user_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=? AND disabled=0", (user_id,)).fetchone()
        return self._public(row) if row else None

    @staticmethod
    def _public(row) -> dict:
        return {
            "id": row["id"],
            "email": row["email"],
            "plan": row["plan"],
            "quota_total": row["quota_total"],
            "quota_used": row["quota_used"],
            "quota_remaining": max(0, row["quota_total"] - row["quota_used"]),
            "created_at": row["created_at"],
        }

    def new_session(self, user_id: str) -> tuple[str, str]:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("DELETE FROM user_sessions WHERE expires<=?", (time.time(),))
            db.execute(
                "INSERT INTO user_sessions(token_hash,user_id,csrf,expires) VALUES (?,?,?,?)",
                (token_hash, user_id, csrf, time.time() + SESSION_SECONDS),
            )
        return token, csrf

    def session(self, token: str) -> dict | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute(
                """SELECT u.*, s.csrf FROM user_sessions s
                   JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=? AND s.expires>? AND u.disabled=0""",
                (token_hash, time.time()),
            ).fetchone()
        if not row:
            return None
        result = self._public(row)
        result["csrf"] = row["csrf"]
        return result

    def logout(self, token: str) -> None:
        if not token:
            return
        with self.connect() as db:
            db.execute(
                "DELETE FROM user_sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )

    def consume_build(self, user_id: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT quota_total,quota_used FROM users WHERE id=? AND disabled=0", (user_id,)
            ).fetchone()
            if not row:
                raise ValueError("用户不存在")
            if row["quota_used"] >= row["quota_total"]:
                raise ValueError("免费构建额度已用完")
            db.execute("UPDATE users SET quota_used=quota_used+1 WHERE id=?", (user_id,))
        return self.get_user(user_id)
