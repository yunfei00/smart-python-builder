from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

MAX_REPOSITORY_BYTES = 100 * 1024 * 1024
MAX_REPOSITORY_FILES = 5000
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


def normalize_public_github_url(value: str) -> str:
    """Accept only public github.com HTTPS repository URLs."""
    value = (value or "").strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("目前只支持公开的 https://github.com/owner/repository 仓库")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise ValueError("GitHub 仓库地址格式无效")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    safe = re.compile(r"[A-Za-z0-9_.-]+")
    if not owner or not name or not safe.fullmatch(owner) or not safe.fullmatch(name):
        raise ValueError("GitHub 仓库地址格式无效")
    return f"https://github.com/{owner}/{name}.git"


def _check_repository_tree(root: Path) -> None:
    count = 0
    total = 0
    for path in root.rglob("*"):
        if ".git" in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise ValueError("GitHub 仓库包含符号链接，当前版本不支持")
        if path.is_file():
            count += 1
            total += path.stat().st_size
            if count > MAX_REPOSITORY_FILES:
                raise ValueError("GitHub 仓库文件数量超过限制")
            if total > MAX_REPOSITORY_BYTES:
                raise ValueError("GitHub 仓库内容超过 100 MB 限制")


def clone_public_github_repository(url: str, target: Path, ref: str | None = None, timeout: int = 120) -> Path:
    """Clone a public GitHub repository without credentials or submodules."""
    if shutil.which("git") is None:
        raise RuntimeError("未找到 Git，请先在 Builder 主机安装 Git for Windows")
    normalized = normalize_public_github_url(url)
    ref = (ref or "").strip()
    if ref and (not _REF_RE.fullmatch(ref) or ".." in ref or ref.startswith(("-", "/"))):
        raise ValueError("Branch / Tag / Commit 格式无效")

    target = target.resolve()
    target.mkdir(parents=True, exist_ok=False)
    project = target / "repository"
    env = os.environ.copy()
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GCM_INTERACTIVE="Never",
        GIT_CONFIG_NOSYSTEM="1",
    )

    def run(command: list[str]) -> None:
        try:
            completed = subprocess.run(
                command,
                cwd=target,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("GitHub 仓库下载超时") from exc
        if completed.returncode:
            raise RuntimeError("GitHub 仓库下载失败，请确认仓库公开、地址及 Branch / Tag / Commit 正确")

    run(["git", "-c", "protocol.file.allow=never", "clone", "--depth", "1", "--no-tags", normalized, str(project)])
    if ref:
        run(["git", "-C", str(project), "-c", "protocol.file.allow=never", "fetch", "--depth", "1", "origin", ref])
        run(["git", "-C", str(project), "checkout", "--detach", "FETCH_HEAD"])

    _check_repository_tree(project)
    shutil.rmtree(project / ".git", ignore_errors=True)
    return project
