from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

CATEGORIES = {'SUGGESTION', 'BUG', 'EXPERIENCE', 'OTHER'}
STATUSES = {'NEW', 'READ', 'RESOLVED'}


class FeedbackStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'NEW',
                    notified INTEGER NOT NULL DEFAULT 0,
                    notification_error TEXT
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id, created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status, created_at DESC)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _validate(category: str, message: str) -> tuple[str, str]:
        category = (category or 'OTHER').strip().upper()
        if category not in CATEGORIES:
            raise ValueError('反馈类型无效')
        if not isinstance(message, str):
            raise ValueError('反馈内容格式无效')
        message = message.strip()
        if not 2 <= len(message) <= 2000:
            raise ValueError('反馈内容需要 2–2000 个字符')
        return category, message

    def create(self, user: dict, category: str, message: str) -> dict:
        category, message = self._validate(category, message)
        identifier = uuid.uuid4().hex
        created_at = time.time()
        with self.connect() as db:
            db.execute(
                """INSERT INTO feedback(
                    id,user_id,username,category,message,created_at,status,notified
                ) VALUES (?,?,?,?,?,?,'NEW',0)""",
                (identifier, user['id'], user['username'], category, message, created_at),
            )
        return self.get(identifier)

    def get(self, identifier: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM feedback WHERE id=?", (identifier,)).fetchone()
        return dict(row) if row else None

    def set_notification_result(self, identifier: str, *, notified: bool, error: str | None = None) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE feedback SET notified=?, notification_error=? WHERE id=?",
                (1 if notified else 0, (error or '')[:160] or None, identifier),
            )

    def list_for_user(self, user_id: str, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM feedback WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_admin(
        self,
        *,
        search: str = '',
        status: str = '',
        category: str = '',
        limit: int = 200,
    ) -> list[dict]:
        clauses = []
        params: list[object] = []
        if search:
            search = search.strip()[:100]
            clauses.append("(username LIKE ? OR message LIKE ?)")
            value = f"%{search}%"
            params.extend([value, value])
        if status:
            status = status.strip().upper()
            if status not in STATUSES:
                raise ValueError('反馈状态无效')
            clauses.append("status=?")
            params.append(status)
        if category:
            category = category.strip().upper()
            if category not in CATEGORIES:
                raise ValueError('反馈类型无效')
            clauses.append("category=?")
            params.append(category)
        limit = max(1, min(int(limit), 1000))
        sql = "SELECT * FROM feedback"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, identifier: str, status: str) -> dict:
        status = (status or '').strip().upper()
        if status not in STATUSES:
            raise ValueError('反馈状态无效')
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM feedback WHERE id=?", (identifier,)).fetchone():
                raise ValueError('反馈不存在')
            db.execute("UPDATE feedback SET status=? WHERE id=?", (status, identifier))
        return self.get(identifier)

    def summary(self) -> dict:
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            new = db.execute("SELECT COUNT(*) FROM feedback WHERE status='NEW'").fetchone()[0]
            resolved = db.execute("SELECT COUNT(*) FROM feedback WHERE status='RESOLVED'").fetchone()[0]
        return {'total': int(total), 'new': int(new), 'resolved': int(resolved)}
