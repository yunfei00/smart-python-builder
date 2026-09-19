"""Customer accounts, sessions, and free-build quota."""
from __future__ import annotations

import argparse
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

    def get_user(self, user_id: str, *, include_disabled: bool = False) -> dict | None:
        with self.connect() as db:
            if include_disabled:
                row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            else:
                row = db.execute("SELECT * FROM users WHERE id=? AND disabled=0", (user_id,)).fetchone()
        return self._public(row) if row else None

    @staticmethod
    def _public(row) -> dict:
        unlimited = row["plan"] == "TEST"
        return {
            "id": row["id"],
            "email": row["email"],
            "plan": row["plan"],
            "quota_total": row["quota_total"],
            "quota_used": row["quota_used"],
            "quota_remaining": None if unlimited else max(0, row["quota_total"] - row["quota_used"]),
            "quota_unlimited": unlimited,
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
                "SELECT plan,quota_total,quota_used FROM users WHERE id=? AND disabled=0", (user_id,)
            ).fetchone()
            if not row:
                raise ValueError("用户不存在")
            if row["plan"] != "TEST":
                if row["quota_used"] >= row["quota_total"]:
                    raise ValueError("免费构建额度已用完")
                db.execute("UPDATE users SET quota_used=quota_used+1 WHERE id=?", (user_id,))
        return self.get_user(user_id)

    def list_users(self, limit: int = 200) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._public(row) | {"disabled": bool(row["disabled"])} for row in rows]

    def set_disabled(self, user_id: str, disabled: bool) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise ValueError("用户不存在")
            db.execute("UPDATE users SET disabled=? WHERE id=?", (1 if disabled else 0, user_id))
            if disabled:
                db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        result = self._public(row)
        result["disabled"] = bool(row["disabled"])
        return result

    def set_remaining_quota(self, user_id: str, remaining: int) -> dict:
        if type(remaining) is not int or not 0 <= remaining <= 1_000_000:
            raise ValueError("剩余额度必须是 0–1000000 的整数")
        with self.connect() as db:
            row = db.execute(
                "SELECT plan,quota_used FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if not row:
                raise ValueError("用户不存在")
            if row["plan"] == "TEST":
                raise ValueError("TEST 账号为无限额度，请先切换为 FREE")
            quota_total = row["quota_used"] + remaining
            db.execute(
                "UPDATE users SET quota_total=? WHERE id=?",
                (quota_total, user_id),
            )
        return self.get_user(user_id, include_disabled=True)

    def reset_quota(self, user_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT plan FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise ValueError("用户不存在")
            if row["plan"] == "TEST":
                db.execute("UPDATE users SET quota_used=0 WHERE id=?", (user_id,))
            else:
                db.execute("UPDATE users SET quota_total=3, quota_used=0 WHERE id=?", (user_id,))
        return self.get_user(user_id, include_disabled=True)

    def refund_build(self, user_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT plan,quota_used FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                return None
            if row["plan"] != "TEST" and row["quota_used"] > 0:
                db.execute("UPDATE users SET quota_used=quota_used-1 WHERE id=?", (user_id,))
        return self.get_user(user_id)

    def set_plan_by_id(self, user_id: str, plan: str) -> dict:
        plan = (plan or "").strip().upper()
        if plan not in {"FREE", "TEST"}:
            raise ValueError("当前仅支持 FREE 或 TEST 套餐")
        with self.connect() as db:
            row = db.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise ValueError("用户不存在")
        return self.set_plan(row["email"], plan)

    def set_plan(self, email: str, plan: str) -> dict:
        email = self.normalize_email(email)
        plan = (plan or "").strip().upper()
        if plan not in {"FREE", "TEST"}:
            raise ValueError("当前仅支持 FREE 或 TEST 套餐")
        with self.connect() as db:
            row = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not row:
                raise ValueError("用户不存在")
            if plan == "TEST":
                db.execute(
                    "UPDATE users SET plan='TEST', quota_total=0, quota_used=0 WHERE email=?",
                    (email,),
                )
            else:
                db.execute(
                    "UPDATE users SET plan='FREE', quota_total=3, quota_used=0 WHERE email=?",
                    (email,),
                )
        return self.get_user(row["id"], include_disabled=True)


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Smart Python Builder account administration")
    parser.add_argument(
        "--database",
        default="web-data/accounts.sqlite3",
        help="Accounts SQLite path (default: web-data/accounts.sqlite3)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    set_plan = subparsers.add_parser("set-plan", help="Set an existing account plan")
    set_plan.add_argument("email")
    set_plan.add_argument("plan", choices=["FREE", "TEST", "free", "test"])
    args = parser.parse_args()

    store = AccountStore(args.database)
    try:
        user = store.set_plan(args.email, args.plan)
    except ValueError as exc:
        parser.error(str(exc))
    remaining = "∞" if user["quota_unlimited"] else str(user["quota_remaining"])
    print(f"{user['email']}: plan={user['plan']} remaining={remaining}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
