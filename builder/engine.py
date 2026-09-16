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


@dataclass(slots=True)
class BuildResult:
    build_id: str
    success: bool
    workspace: Path
    artifact: Path | None
    log_file: Path
    error: str | None = None


class BuildEngine:
    """Build one Python entry file in a fresh uv-managed workspace."""

    def __init__(self, workspace_root: Path | str = "workspace", timeout: int = 900):
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout = timeout
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def build(self, request: BuildRequest) -> BuildResult:
        source = request.source.resolve()
        if not source.is_file() or source.suffix.lower() != ".py":
            raise ValueError("Phase 1 accepts one existing .py file")
        if shutil.which("uv") is None:
            raise RuntimeError("uv was not found in PATH")

        build_id = uuid.uuid4().hex
        workspace = self.workspace_root / build_id
        workspace.mkdir(parents=True)
        entry = workspace / source.name
        shutil.copy2(source, entry)
        log_file = workspace / "build.log"

        try:
            self._run(["uv", "init", "--bare", "--no-workspace"], workspace, log_file)
            if request.packages:
                self._run(["uv", "add", *request.packages], workspace, log_file)
            self._run(["uv", "add", "--dev", "pyinstaller"], workspace, log_file)

            command = ["uv", "run", "pyinstaller", "--noconfirm", "--clean", "--onefile"]
            if request.windowed:
                command.append("--windowed")
            if request.app_name:
                command.extend(["--name", request.app_name])
            command.append(entry.name)
            self._run(command, workspace, log_file)

            exe_name = request.app_name or source.stem
            artifact = workspace / "dist" / f"{exe_name}.exe"
            if not artifact.exists():
                raise RuntimeError(f"PyInstaller finished but artifact is missing: {artifact}")
            return BuildResult(build_id, True, workspace, artifact, log_file)
        except Exception as exc:
            return BuildResult(build_id, False, workspace, None, log_file, str(exc))

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
