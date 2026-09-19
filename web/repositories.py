from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_REPOSITORY_BYTES = 100 * 1024 * 1024
MAX_REPOSITORY_FILES = 5000
_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


def safe_git_diagnostic(stderr: str) -> str:
    """Bounded diagnostics for both browser and logs; never echo raw credentials."""
    text = stderr or ""
    text = re.sub(r"(?im)^.*(?:authorization|proxy-authorization|set-cookie|cookie)\s*[:=].*$", "[REDACTED header]", text)
    text = re.sub(r"(?i)((?:https?|socks[45]h?|ssh|git)://)[^\s/'\"<>]*@", r"\1[REDACTED]@", text)
    text = re.sub(r"(?i)((?:https?|socks[45]h?)://[^\s?'\"<>]+)\?[^\s'\"<>]*", r"\1?[REDACTED]", text)
    text = re.sub(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", "[REDACTED authorization]", text)
    text = re.sub(r"(?i)((?:password|passwd|token|secret|api[_-]?key)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1[REDACTED]", text)
    text = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b", "[REDACTED token]", text)
    for key, value in os.environ.items():
        if value and re.search(r"TOKEN|PASSWORD|PASSWD|SECRET|API_KEY|AUTHORIZATION", key, re.I):
            text = text.replace(value, "[REDACTED]")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text.strip()[:1800]


class RepositoryImportError(RuntimeError):
    def __init__(self, code: str, message: str, *, stage="", returncode=None, stderr=""):
        self.code = code
        diagnostic = safe_git_diagnostic(stderr)
        context = f"（Git {stage}" if stage else ""
        if returncode is not None:
            context += f"，退出码 {returncode}"
        if stage:
            context += "）"
        super().__init__(message + context + ("\n" + diagnostic if diagnostic else ""))


def git_failure(stderr: str, stage: str, returncode: int) -> RepositoryImportError:
    error = (stderr or "").lower()
    if any(word in error for word in ("could not resolve proxy", "proxy authentication", "proxy connect", "407", "tunnel connection failed")) or re.search(r"failed to connect to (?:127\.\d+\.\d+\.\d+|localhost|\[?::1\]?) port", error):
        code, message = "proxy_error", "GitHub 代理连接失败，请检查 Builder 主机的 Git/环境代理配置"
    elif any(word in error for word in ("ssl", "tls", "certificate", "schannel", "ca cert")):
        code, message = "tls_error", "GitHub TLS/证书校验失败，请检查 Git 的 CA、SSL backend 和代理证书配置"
    elif any(word in error for word in ("repository not found", "authentication failed", "could not read username", "terminal prompts disabled", "returned error: 403", "returned error: 404")):
        code, message = "repository_unavailable", "GitHub 仓库不存在或无法公开访问（私有仓库和无权限也可能返回此错误）"
    elif any(word in error for word in ("couldn't find remote ref", "not our ref", "unadvertised object", "remote ref does not exist")):
        code, message = "ref_not_found", "Branch / Tag / Commit 不存在或无法从该仓库拉取；Commit 请使用完整的 40 位 SHA"
    elif any(word in error for word in ("could not resolve host", "failed to connect", "connection", "timed out", "network", "couldn't connect", "empty reply", "unable to access", "http/2", "curl ")):
        code, message = "network_error", "GitHub 网络连接失败，请检查网络、DNS 和代理；这不代表 Branch / Tag 填错"
    else:
        code, message = "git_error", "Git 命令执行失败，请根据以下诊断检查 Builder 主机的 Git 配置和文件权限"
    return RepositoryImportError(code, message, stage=stage, returncode=returncode, stderr=stderr)


def _refused_loopback_proxy(stderr: str) -> bool:
    # GitHub cannot resolve to a literal loopback host here unless a local proxy
    # is selected. Retry only an explicitly refused local connection, not remote
    # proxy outages, TLS failures, timeouts or authentication errors.
    return bool(re.search(r"fatal: unable to access 'https://github\.com/[^']+': Failed to connect to (?:127\.\d+\.\d+\.\d+|localhost|\[?::1\]?) port \d+[^\r\n]*Connection refused", stderr, re.I))


def normalize_public_github_url(value: str) -> str:
    """Accept only public github.com HTTPS repository URLs."""
    if not isinstance(value, str):
        raise ValueError("GitHub 仓库地址必须是文本")
    value = value.strip()
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
            raise RepositoryImportError("unsupported_symlink", "GitHub 仓库包含符号链接，当前版本不支持")
        if path.is_file():
            count += 1
            total += path.stat().st_size
            if count > MAX_REPOSITORY_FILES:
                raise RepositoryImportError("repository_too_large", "GitHub 仓库文件数量超过 5000 个限制")
            if total > MAX_REPOSITORY_BYTES:
                raise RepositoryImportError("repository_too_large", "GitHub 仓库内容超过 100 MB 限制")


def clone_public_github_repository(url: str, target: Path, ref: str | None = None, timeout: int = 120) -> Path:
    """Clone a public GitHub repository without credentials or submodules."""
    if shutil.which("git") is None:
        raise RepositoryImportError("git_not_installed", "未找到 Git，请先在 Builder 主机安装 Git for Windows")
    normalized = normalize_public_github_url(url)
    if ref is not None and not isinstance(ref, str):
        raise ValueError("Branch / Tag / Commit 必须是文本")
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
        LC_ALL="C",
    )
    # Keep the operator's system/global proxy and CA/SSL settings. Disable
    # interactive authentication and credential helpers for this public import
    # rather than ignoring the entire system configuration.
    for key in list(env):
        if key.startswith("GIT_TRACE") or key in {"GIT_CURL_VERBOSE", "GIT_ASKPASS", "SSH_ASKPASS"}:
            env.pop(key)
    empty_hooks = target / "empty-hooks"
    empty_hooks.mkdir()
    options = ["-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
               "-c", "protocol.file.allow=never", "-c", "credential.helper=",
               "-c", "credential.interactive=false", "-c", "core.askPass=",
               "-c", "http.extraHeader=", "-c", "http.cookieFile=",
               "-c", "core.hooksPath=" + str(empty_hooks), "-c", "submodule.recurse=false"]
    deadline = time.monotonic() + timeout
    direct = False

    def run(command: list[str], stage: str) -> str:
        nonlocal direct
        first_failure = ""
        while True:
            flags = options + (["-c", "http.proxy=", "-c", "https.proxy="] if direct else [])
            # URL-specific proxy configuration can otherwise override http.proxy.
            if direct:
                flags += ["-c", f"http.{normalized}.proxy=", "-c", f"http.{normalized}/.proxy="]
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                completed = subprocess.run(
                    command[:1] + flags + command[1:], cwd=target, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", timeout=remaining, check=False,
                )
            except subprocess.TimeoutExpired:
                raise RepositoryImportError("git_timeout", "GitHub 导入超时，请检查网络或缩小仓库后重试", stage=stage) from None
            except FileNotFoundError:
                raise RepositoryImportError("git_not_installed", "未找到 Git，请先在 Builder 主机安装 Git for Windows") from None
            except OSError as exc:
                raise RepositoryImportError("git_error", "Git 无法启动，请检查安装和执行权限", stage=stage, stderr=str(exc)) from None
            if not completed.returncode:
                return completed.stdout
            if not direct and stage in {"ls-remote", "fetch", "clone"} and _refused_loopback_proxy(completed.stderr):
                direct = True
                first_failure = completed.stderr
                continue
            failure = git_failure(completed.stderr, stage, completed.returncode)
            if first_failure:
                raise RepositoryImportError(failure.code, "本地代理拒绝连接，单次直连重试仍失败。\n" + str(failure), stderr=first_failure)
            raise failure

    if ref:
        names = [ref] if ref.startswith(("refs/heads/", "refs/tags/")) else ["refs/heads/" + ref, "refs/tags/" + ref]
        advertised = run(["git", "ls-remote", "--heads", "--tags", normalized, *names], "ls-remote")
        available = {line.split('\t', 1)[1] for line in advertised.splitlines() if '\t' in line}
        selected = next((name for name in names if name in available), None)
        if selected is None:
            if re.fullmatch(r"[0-9a-fA-F]{40}", ref):
                selected = ref
            else:
                raise RepositoryImportError("ref_not_found", "Branch / Tag 不存在；Commit 请使用完整的 40 位 SHA（不是缩写）")
        run(["git", "init", str(project)], "init")
        run(["git", "-C", str(project), "remote", "add", "origin", normalized], "remote")
        run(["git", "-C", str(project), "fetch", "--depth", "1", "--no-tags", "origin", selected], "fetch")
        revision = "FETCH_HEAD"
    else:
        run(["git", "clone", "--depth", "1", "--no-tags", "--no-checkout", normalized, str(project)], "clone")
        revision = "HEAD"

    # Windows core.symlinks=false writes links as plain files. Inspect Git modes
    # before checkout so unsupported links cannot bypass the filesystem check.
    tree = run(["git", "-C", str(project), "ls-tree", "-r", "-z", revision], "ls-tree")
    if any(item.startswith("120000 ") for item in tree.split('\0')):
        raise RepositoryImportError("unsupported_symlink", "GitHub 仓库包含符号链接，当前版本不支持")
    run(["git", "-C", str(project), "checkout", "--detach", revision], "checkout")

    _check_repository_tree(project)
    shutil.rmtree(project / ".git", ignore_errors=True)
    return project
