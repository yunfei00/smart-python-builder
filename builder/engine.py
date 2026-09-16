from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class BuildRequest:
    source: Path
    packages: list[str] = field(default_factory=list)
    windowed: bool = False
    app_name: str | None = None
    entry_point: Path | None = None


@dataclass(slots=True)
class BuildResult:
    build_id: str
    success: bool
    workspace: Path
    artifact: Path | None
    log_file: Path
    error: str | None = None


class BuildEngine:
    """Build a Python entry file or complete project in a fresh uv workspace."""

    def __init__(self, workspace_root: Path | str = "workspace", timeout: int = 900):
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout = timeout
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def build(self, request: BuildRequest) -> BuildResult:
        source = request.source.resolve()
        if not source.exists():
            raise FileNotFoundError(source)
        if source.is_file() and source.suffix.lower() != ".py":
            raise ValueError("Source file must be a .py file")
        if not source.is_file() and not source.is_dir():
            raise ValueError("Source must be a Python file or project folder")
        if shutil.which("uv") is None:
            raise RuntimeError("uv was not found in PATH")

        build_id = uuid.uuid4().hex
        workspace = self.workspace_root / build_id
        project_dir = workspace / "project"
        workspace.mkdir(parents=True)
        log_file = workspace / "build.log"

        try:
            entry = self._copy_source(source, request.entry_point, project_dir)
            self._run(["uv", "init", "--bare", "--no-workspace"], project_dir, log_file)
            if request.packages:
                self._run(["uv", "add", *request.packages], project_dir, log_file)
            self._run(["uv", "add", "--dev", "pyinstaller"], project_dir, log_file)

            command = ["uv", "run", "pyinstaller", "--noconfirm", "--clean", "--onefile"]
            if request.windowed:
                command.append("--windowed")
            if request.app_name:
                command.extend(["--name", request.app_name])
            command.append(str(entry.relative_to(project_dir)))
            self._run(command, project_dir, log_file)

            exe_name = request.app_name or entry.stem
            artifact = project_dir / "dist" / f"{exe_name}.exe"
            if not artifact.exists():
                raise RuntimeError(f"PyInstaller finished but artifact is missing: {artifact}")
            return BuildResult(build_id, True, workspace, artifact, log_file)
        except Exception as exc:
            return BuildResult(build_id, False, workspace, None, log_file, str(exc))

    def _copy_source(self, source: Path, requested_entry: Path | None, project_dir: Path) -> Path:
        if source.is_file():
            project_dir.mkdir(parents=True)
            entry = project_dir / source.name
            shutil.copy2(source, entry)
            return entry

        shutil.copytree(
            source,
            project_dir,
            ignore=shutil.ignore_patterns(".git", ".venv", "venv", "build", "dist", "__pycache__", ".pytest_cache"),
        )
        if requested_entry is None:
            raise ValueError("Project-folder builds require an entry_point")
        requested_entry = requested_entry.resolve()
        try:
            relative = requested_entry.relative_to(source)
        except ValueError as exc:
            raise ValueError("entry_point must be inside the source project") from exc
        entry = project_dir / relative
        if not entry.is_file() or entry.suffix.lower() != ".py":
            raise ValueError(f"Invalid project entry point: {requested_entry}")
        return entry

    def _run(self, command: list[str], cwd: Path, log_file: Path) -> None:
        with log_file.open("a", encoding="utf-8") as log:
            log.write("\n$ " + " ".join(command) + "\n")
            log.flush()
            process = subprocess.run(
                command,
                cwd=cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            log.write(f"\n[exit_code={process.returncode}]\n")
            if process.returncode != 0:
                raise RuntimeError(f"Command failed ({process.returncode}): {' '.join(command)}")
