"""End-to-end compatibility check for one real public GitHub Python repository.

This intentionally goes through the Web GitHub-import API so entry-path,
selection, build, packaging, download, and final executable smoke behavior are
validated together.

Run on Windows:
    uv run python tests/windows_portfolio_acceptance.py \
        --repository https://github.com/yunfei00/instrument-capture-studio
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from builder.engine import BuildEngine
from builder.settings import SettingsStore
from web.app import create_app


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--timeout", type=int, default=2400)
    return parser.parse_args()


def repository_name(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")


def choose_entries(job: dict) -> list[str]:
    details = job.get("entry_details") or []
    entries = job.get("entries") or []

    recommended = [
        item["path"]
        for item in details
        if item.get("recommended") and item.get("kind") == "application"
    ]
    if recommended:
        # One representative application is enough for portfolio-wide packaging;
        # Instrument Capture Studio gets two to keep multi-entry behavior covered.
        limit = 2 if job.get("project_name") == "instrument-capture-studio" else 1
        return recommended[:limit]

    internal = [
        item["path"]
        for item in details
        if item.get("kind") == "internal"
    ]
    if internal:
        return internal[:1]

    non_auxiliary = [
        item["path"]
        for item in details
        if item.get("kind") != "auxiliary"
    ]
    if non_auxiliary:
        return non_auxiliary[:1]

    return entries[:1] if len(entries) == 1 else []


def wait_for_terminal(client: TestClient, job_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{job_id}").json()
        status = result.get("status")
        if status != last_status:
            print("STATUS", status, flush=True)
            last_status = status
        if result.get("terminal"):
            return result
        time.sleep(2)
    raise TimeoutError(f"build did not finish within {timeout}s")


def inspect_zip(payload: bytes, root: Path) -> list[Path]:
    extracted = root / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        leaked = [name for name in names if name.lower().endswith(".py")]
        if leaked:
            raise AssertionError(f"source files leaked into downloadable ZIP: {leaked[:20]}")
        archive.extractall(extracted)

    # Multi-app bundles contain one ZIP per application. Inspect and extract them.
    nested = list(extracted.glob("*.zip"))
    for nested_zip in nested:
        target = extracted / nested_zip.stem
        target.mkdir(exist_ok=True)
        with zipfile.ZipFile(nested_zip) as archive:
            names = archive.namelist()
            leaked = [name for name in names if name.lower().endswith(".py")]
            if leaked:
                raise AssertionError(
                    f"source files leaked into nested ZIP {nested_zip.name}: {leaked[:20]}"
                )
            archive.extractall(target)
    return list(extracted.rglob("*.exe"))


def write_report(root: Path, **values) -> None:
    (root / "portfolio-result.json").write_text(
        json.dumps(values, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def main():
    args = parse_args()
    name = repository_name(args.repository)
    root = (
        Path(__file__).resolve().parents[1]
        / "workspace"
        / ("portfolio-" + name + "-" + uuid.uuid4().hex)
    )
    root.mkdir(parents=True)

    SettingsStore(root / "settings.sqlite3").save(
        {"ai_enabled": False, "feishu_enabled": False}
    )
    app = create_app(root)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/account/register",
                data={
                    "username": ("portfolio-" + uuid.uuid4().hex)[:32],
                    "password": secrets.token_urlsafe(24),
                },
                follow_redirects=False,
            )
            assert response.status_code == 303, response.text
            session = app.state.accounts.session(client.cookies.get("builder_user"))
            app.state.accounts.set_plan_by_id(session["id"], "TEST")
            csrf = session["csrf"]

            imported = client.post(
                "/api/repositories",
                json={"url": args.repository},
            )
            if imported.status_code != 200:
                write_report(
                    root,
                    repository=args.repository,
                    stage="github_import",
                    status="FAIL",
                    response=imported.text,
                )
                raise AssertionError(
                    f"GitHub import failed ({imported.status_code}): {imported.text}"
                )

            job = imported.json()
            entries = job.get("entries") or []
            details = job.get("entry_details") or []

            assert entries, "import returned no selectable Python entries"
            assert all("\\" not in entry for entry in entries), entries
            detail_paths = [item["path"] for item in details]
            assert all("\\" not in path for path in detail_paths), detail_paths
            missing = [path for path in detail_paths if path not in entries]
            assert not missing, (
                "entry_details and job.entries disagree: "
                f"missing from selectable entries: {missing}"
            )

            selected = choose_entries(job)
            if not selected:
                write_report(
                    root,
                    repository=args.repository,
                    project=name,
                    stage="analysis",
                    status="PASS_NO_BUILDABLE_ENTRY",
                    entries=entries,
                    entry_details=details,
                )
                print(
                    "PORTFOLIO ANALYSIS PASS / NO BUILDABLE ENTRY",
                    args.repository,
                    flush=True,
                )
                return

            for entry in selected:
                preview = client.get(
                    f"/api/jobs/{job['id']}/plan",
                    params={"entry": entry, "mode": "onefile"},
                )
                assert preview.status_code == 200, (
                    f"plan rejected selected entry {entry!r}: {preview.text}"
                )

            started = client.post(
                f"/api/jobs/{job['id']}/build",
                data={"entries": "|".join(selected), "mode": "onefile"},
                headers={"X-CSRF-Token": csrf},
            )
            assert started.status_code == 200, (
                "build request rejected before engine start: "
                f"{started.status_code} {started.text}; selected={selected}; "
                f"allowed={entries}"
            )

            result = wait_for_terminal(client, job["id"], args.timeout)
            if result.get("status") != "SUCCESS":
                log_text = ""
                try:
                    log_text = client.get(f"/api/jobs/{job['id']}/log").json().get("text", "")
                except Exception:
                    pass
                write_report(
                    root,
                    repository=args.repository,
                    project=name,
                    stage="build",
                    status="FAIL",
                    selected_entries=selected,
                    result=result,
                    log_tail=log_text[-50000:],
                )
                raise AssertionError(
                    f"build failed: {result.get('status')}: {result.get('error')}"
                )

            downloaded = client.get(f"/api/jobs/{job['id']}/download")
            assert downloaded.status_code == 200, downloaded.text[:1000]

            artifact = str(result.get("artifact") or "")
            if artifact.lower().endswith(".exe"):
                exe = root / "downloaded.exe"
                exe.write_bytes(downloaded.content)
                executables = [exe]
            else:
                executables = inspect_zip(downloaded.content, root)

            assert executables, "successful build download contained no executable"
            smoke_log = root / "download-smoke.log"
            for exe in executables:
                BuildEngine._smoke_test_executable(
                    exe,
                    "gui",
                    smoke_log,
                    startup_seconds=8,
                )

            write_report(
                root,
                repository=args.repository,
                project=name,
                stage="complete",
                status="PASS",
                selected_entries=selected,
                entry_count=len(entries),
                entry_details=details,
                build_id=result.get("build_id"),
                executables=[str(path) for path in executables],
            )
            print(
                "PORTFOLIO BUILD PASS",
                args.repository,
                "entries=",
                selected,
                flush=True,
            )
    except Exception as exc:
        report = root / "portfolio-result.json"
        if not report.exists():
            write_report(
                root,
                repository=args.repository,
                project=name,
                stage="exception",
                status="FAIL",
                error=f"{type(exc).__name__}: {exc}",
            )
        print("PORTFOLIO BUILD FAIL", args.repository, repr(exc), flush=True)
        print("EVIDENCE", root, flush=True)
        raise


if __name__ == "__main__":
    main()
