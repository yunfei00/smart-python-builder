from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

ACTIVE_STATUSES = {
    'QUEUED', 'BUILDING', 'AI_DIAGNOSING', 'AI_REPAIRING', 'REBUILDING', 'CANCELING'
}
UUID32 = re.compile(r'[a-f0-9]{32}')


def _safe_child(root: Path, path: Path) -> Path | None:
    try:
        root = root.resolve()
        resolved = path.resolve()
        return resolved if resolved == root or resolved.is_relative_to(root) else None
    except OSError:
        return None


def path_size(path: Path) -> int:
    """Return managed path size without following symlinks."""
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
        if not path.is_dir():
            return 0
    except OSError:
        return 0
    total = 0
    for current, dirs, files in os.walk(path, followlinks=False):
        base = Path(current)
        dirs[:] = [name for name in dirs if not (base / name).is_symlink()]
        for name in files:
            item = base / name
            try:
                if not item.is_symlink():
                    total += item.stat().st_size
            except OSError:
                pass
    return total


def job_paths(root: Path | str, job: dict) -> list[Path]:
    root = Path(root).resolve()
    paths: list[Path] = []
    job_id = job.get('id')
    if isinstance(job_id, str) and UUID32.fullmatch(job_id):
        upload = _safe_child(root, root / 'uploads' / job_id)
        metadata = _safe_child(root, root / f'{job_id}.json')
        if upload is not None:
            paths.append(upload)
        if metadata is not None:
            paths.append(metadata)

    build_ids = {job.get('build_id')}
    for attempt in job.get('attempts', []):
        if isinstance(attempt, dict):
            build_ids.add(attempt.get('build_id'))
    workspace_root = (root / 'workspace').resolve()
    for build_id in build_ids:
        if not isinstance(build_id, str) or not UUID32.fullmatch(build_id):
            continue
        target = _safe_child(workspace_root, workspace_root / build_id)
        if target is not None:
            paths.append(target)

    for key in ('artifact', 'log'):
        value = job.get(key)
        if not value:
            continue
        target = _safe_child(root, Path(value))
        if target is not None:
            paths.append(target)

    unique: list[Path] = []
    seen = set()
    for path in sorted(paths, key=lambda item: len(item.parts)):
        marker = str(path)
        if marker in seen:
            continue
        if any(path != parent and path.is_relative_to(parent) for parent in unique):
            continue
        seen.add(marker)
        unique.append(path)
    return unique


def delete_job_files(root: Path | str, job: dict) -> int:
    total = 0
    for path in job_paths(root, job):
        total += path_size(path)
        try:
            if path.is_symlink():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            continue
    return total


def retention_reference(job: dict) -> float:
    for key in ('finished_at', 'started_at', 'created_at'):
        value = job.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return time.time()


def cleanup_jobs(
    root: Path | str,
    jobs: dict[str, dict],
    retention_seconds: int,
    *,
    now: float | None = None,
    dry_run: bool = False,
) -> dict:
    now = time.time() if now is None else now
    cutoff = now - max(0, retention_seconds)
    candidates: list[str] = []
    estimated = 0
    for job_id, job in list(jobs.items()):
        status = job.get('status')
        if status in ACTIVE_STATUSES:
            continue
        if not (job.get('terminal') or status in {'READY', 'EXPIRED', 'CANCELED', 'SUCCESS', 'FAILED', 'NEEDS_MANUAL_REVIEW'}):
            continue
        if retention_reference(job) > cutoff:
            continue
        candidates.append(job_id)
        estimated += sum(path_size(path) for path in job_paths(root, job))

    if not dry_run:
        for job_id in candidates:
            job = jobs.get(job_id)
            if job is None:
                continue
            delete_job_files(root, job)
            jobs.pop(job_id, None)
    return {'count': len(candidates), 'bytes': estimated, 'job_ids': candidates}


def disk_usage(root: Path | str) -> dict:
    root = Path(root).resolve()
    uploads = path_size(root / 'uploads')
    workspace = path_size(root / 'workspace')
    databases = 0
    metadata = 0
    try:
        for path in root.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            size = path.stat().st_size
            if path.suffix in {'.sqlite3', '.db'}:
                databases += size
            elif path.suffix == '.json':
                metadata += size
    except OSError:
        pass
    return {
        'total_bytes': path_size(root),
        'uploads_bytes': uploads,
        'workspace_bytes': workspace,
        'database_bytes': databases,
        'metadata_bytes': metadata,
    }
