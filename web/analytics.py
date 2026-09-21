from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def repair_count_from_attempts(attempts) -> int:
    count = 0
    for attempt in attempts or []:
        if not isinstance(attempt, dict):
            continue
        repair = attempt.get('repair')
        if isinstance(repair, dict) and repair.get('retry'):
            count += 1
    return count


class AnalyticsStore:
    """Small durable build ledger kept after heavyweight job data is cleaned."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS build_events (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    final_status TEXT,
                    ai_repairs INTEGER NOT NULL DEFAULT 0
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_build_events_started ON build_events(started_at)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_build_events_user ON build_events(user_id, started_at)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def start(self, job_id: str, user_id: str | None, started_at: float | None = None) -> None:
        started_at = time.time() if started_at is None else float(started_at)
        with self.connect() as db:
            db.execute(
                """INSERT INTO build_events(job_id,user_id,started_at)
                   VALUES (?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET
                     user_id=COALESCE(build_events.user_id, excluded.user_id),
                     started_at=MIN(build_events.started_at, excluded.started_at)""",
                (job_id, user_id, started_at),
            )

    def finish(
        self,
        job_id: str,
        status: str,
        *,
        finished_at: float | None = None,
        ai_repairs: int = 0,
        user_id: str | None = None,
        started_at: float | None = None,
    ) -> None:
        if started_at is None:
            started_at = time.time()
        self.start(job_id, user_id, started_at)
        finished_at = time.time() if finished_at is None else float(finished_at)
        with self.connect() as db:
            db.execute(
                """UPDATE build_events
                   SET finished_at=?, final_status=?, ai_repairs=?
                   WHERE job_id=?""",
                (finished_at, status, max(0, int(ai_repairs)), job_id),
            )

    def backfill(self, jobs) -> None:
        for job in jobs:
            if not isinstance(job, dict):
                continue
            status = job.get('status')
            job_id = job.get('id')
            if not isinstance(job_id, str) or not job_id:
                continue
            if not job.get('started_at') and status in {None, 'READY'}:
                continue
            started = job.get('started_at') or job.get('created_at') or time.time()
            self.start(job_id, job.get('owner_id'), started)
            if job.get('terminal') or status in {'SUCCESS', 'FAILED', 'NEEDS_MANUAL_REVIEW', 'CANCELED', 'EXPIRED'}:
                self.finish(
                    job_id,
                    status or 'UNKNOWN',
                    finished_at=job.get('finished_at') or started,
                    ai_repairs=repair_count_from_attempts(job.get('attempts')),
                    user_id=job.get('owner_id'),
                    started_at=started,
                )

    def counts_by_user(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                """SELECT user_id, COUNT(*) AS total
                   FROM build_events
                   WHERE user_id IS NOT NULL
                   GROUP BY user_id"""
            ).fetchall()
        return {row['user_id']: int(row['total']) for row in rows}

    def summary(self, *, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        local = time.localtime(now)
        day_start = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM build_events").fetchone()[0]
            today = db.execute(
                "SELECT COUNT(*) FROM build_events WHERE started_at>=?",
                (day_start,),
            ).fetchone()[0]
            success = db.execute(
                "SELECT COUNT(*) FROM build_events WHERE final_status='SUCCESS'"
            ).fetchone()[0]
            failed = db.execute(
                """SELECT COUNT(*) FROM build_events
                   WHERE final_status IN ('FAILED','NEEDS_MANUAL_REVIEW')"""
            ).fetchone()[0]
            ai_repairs = db.execute(
                "SELECT COALESCE(SUM(ai_repairs),0) FROM build_events"
            ).fetchone()[0]
        completed = int(success) + int(failed)
        return {
            'total': int(total),
            'today': int(today),
            'success': int(success),
            'failed': int(failed),
            'success_rate': round(int(success) * 100 / completed, 1) if completed else None,
            'ai_repairs': int(ai_repairs),
        }
