from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path


def cleanup_workspaces(root: Path, retention_seconds=7*86400, now=None):
    """Only delete terminal, owned UUID directories older than retention."""
    root=Path(root).resolve()
    now=time.time() if now is None else now
    removed=[]
    if not root.exists():return removed
    for path in root.iterdir():
        if not re.fullmatch('[a-f0-9]{32}',path.name) or not path.is_dir() or path.is_symlink():continue
        if not path.resolve().is_relative_to(root):continue
        marker=path/'task.json'
        try:
            state=json.loads(marker.read_text(encoding='utf-8'))
            if state['status'] not in {'SUCCESS','FAILED'} or now-state['finished_at']<retention_seconds:continue
        except (OSError,ValueError,KeyError):continue
        # Re-check the absolute deletion target immediately before mutation.
        resolved=path.resolve()
        if resolved.parent!=root:raise ValueError('Cleanup target escaped managed workspace')
        shutil.rmtree(resolved)
        removed.append(path.name)
    return removed
