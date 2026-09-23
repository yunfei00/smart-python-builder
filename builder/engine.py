from __future__ import annotations

import shutil
import subprocess
import uuid
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from .models import BuildPlan
from .execution import LocalWindowsBackend


@dataclass(slots=True)
class BuildRequest:
    source: Path
    packages: list[str] = field(default_factory=list)
    windowed: bool = False
    app_name: str | None = None
    entry_point: Path | None = None
    plan: BuildPlan | None = None


@dataclass(slots=True)
class BuildResult:
    build_id: str
    success: bool
    workspace: Path
    artifact: Path | None
    log_file: Path
    error: str | None = None
    artifacts: list[Path] = field(default_factory=list)


class BuildEngine:
    """Build a Python entry file or complete project in a fresh uv workspace."""

    def __init__(self, workspace_root: Path | str = "workspace", timeout: int = 900):
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout = timeout
        self.on_created = None
        self.backend = LocalWindowsBackend()
        self.min_free_bytes = 1024**3
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def cancel(self) -> None:
        cancel = getattr(self.backend, 'cancel', None)
        if cancel:
            cancel()

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
        if request.app_name and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', request.app_name):
            raise ValueError('Invalid application name')

        build_id = uuid.uuid4().hex
        workspace = self.workspace_root / build_id
        project_dir = workspace / "project"
        workspace.mkdir(parents=True)
        log_file = workspace / "build.log"
        log_file.touch()
        self._deadline = time.monotonic() + self.timeout
        marker = workspace / 'task.json'
        marker.write_text(json.dumps(dict(status='BUILDING', build_id=build_id)), encoding='utf-8')
        success = False
        try:
            if self.on_created:
                self.on_created(build_id, log_file)
            if shutil.disk_usage(workspace).free < self.min_free_bytes:
                raise RuntimeError('Insufficient disk space: at least 1 GiB required')
            entry = self._copy_source(source, request.entry_point, project_dir)
            if request.plan:
                request.plan.validate(project_dir)
                (workspace / "plan.json").write_text(request.plan.to_json(), encoding="utf-8")
            # Keep uploaded metadata intact; the build environment lives one level
            # above the copied project and never installs the project itself.
            self._run(["uv", "init", "--bare", "--no-workspace"], workspace, log_file)
            if request.packages:
                self._run(["uv", "add", *request.packages], workspace, log_file)
            self._run(["uv", "add", "--dev", "pyinstaller"], workspace, log_file)

            plan = request.plan
            mode = plan.mode if plan else "onefile"
            launch_entry, entry_args = self._prepare_entry(entry, project_dir, workspace)
            command = [str(workspace / ".venv" / "Scripts" / "pyinstaller.exe"), "--noconfirm", "--clean", f"--{mode}"]
            command.extend(entry_args)
            if plan:
                for value in plan.hidden_imports:
                    command.extend(["--hidden-import", value])
                for value in plan.collect_all:
                    command.extend(["--collect-all", value])
                for source_path, destination in plan.data_files:
                    command.extend(["--add-data", f"{source_path};{destination}"])
                command.extend(plan.pyinstaller_args)
            is_windowed = plan.app_type == "gui" if plan else request.windowed
            if is_windowed:
                command.append("--windowed")
            command.extend(["--name", request.app_name or entry.stem])
            command.append(str(launch_entry))
            self._run(command, project_dir, log_file)

            exe_name = request.app_name or entry.stem
            artifact = project_dir / "dist" / (exe_name if mode == "onedir" else f"{exe_name}.exe")
            executable = artifact / f'{exe_name}.exe' if mode == 'onedir' else artifact
            if not executable.is_file() or executable.stat().st_size == 0:
                raise RuntimeError(f"PyInstaller finished but artifact is missing: {artifact}")
            artifact = self._stage_sidecars(artifact, executable, plan, project_dir, exe_name)
            success = True
            return BuildResult(build_id, True, workspace, artifact, log_file)
        except Exception as exc:
            with log_file.open('a', encoding='utf-8') as log:
                log.write('\nBUILD FAILED: ' + str(exc) + '\n')
            return BuildResult(build_id, False, workspace, None, log_file, str(exc))
        finally:
            marker.write_text(json.dumps(dict(status='SUCCESS' if success else 'FAILED', build_id=build_id, finished_at=time.time())), encoding='utf-8')


    def build_many(self, source: Path | str, entries: list[Path], plans: list[BuildPlan]) -> BuildResult:
        """Build several entries using one copied project and one shared environment."""
        source = Path(source).resolve()
        if not source.is_dir() or not entries or len(entries) != len(plans):
            raise ValueError("Multi-app builds require a project folder and matching entries/plans")
        if shutil.which("uv") is None:
            raise RuntimeError("uv was not found in PATH")
        build_id = uuid.uuid4().hex
        workspace = self.workspace_root / build_id
        project_dir = workspace / "project"
        workspace.mkdir(parents=True)
        log_file = workspace / "build.log"
        log_file.touch()
        self._deadline = time.monotonic() + self.timeout
        marker = workspace / "task.json"
        marker.write_text(json.dumps(dict(status="BUILDING", build_id=build_id)), encoding="utf-8")
        success = False
        try:
            if self.on_created:
                self.on_created(build_id, log_file)
            first = self._copy_source(source, entries[0], project_dir)
            copied_entries = [first] + [project_dir / entry.resolve().relative_to(source) for entry in entries[1:]]
            for plan in plans:
                plan.validate(project_dir)
            self._run(["uv", "init", "--bare", "--no-workspace"], workspace, log_file)
            packages = list(dict.fromkeys(dep for plan in plans for dep in plan.dependencies))
            if packages:
                self._run(["uv", "add", *packages], workspace, log_file)
            self._run(["uv", "add", "--dev", "pyinstaller"], workspace, log_file)
            artifacts = []
            for entry, plan in zip(copied_entries, plans):
                launch_entry, entry_args = self._prepare_entry(entry, project_dir, workspace)
                command = [str(workspace / ".venv" / "Scripts" / "pyinstaller.exe"), "--noconfirm", "--clean", f"--{plan.mode}", *entry_args]
                for value in plan.hidden_imports:
                    command.extend(["--hidden-import", value])
                for value in plan.collect_all:
                    command.extend(["--collect-all", value])
                for source_path, destination in plan.data_files:
                    command.extend(["--add-data", f"{source_path};{destination}"])
                command.extend(plan.pyinstaller_args)
                if plan.app_type == "gui":
                    command.append("--windowed")
                exe_name = entry.stem
                command.extend(["--name", exe_name, str(launch_entry)])
                self._run(command, project_dir, log_file)
                artifact = project_dir / "dist" / (exe_name if plan.mode == "onedir" else f"{exe_name}.exe")
                executable = artifact / f"{exe_name}.exe" if plan.mode == "onedir" else artifact
                if not executable.is_file() or executable.stat().st_size == 0:
                    raise RuntimeError(f"PyInstaller finished but artifact is missing: {artifact}")
                artifact = self._stage_sidecars(artifact, executable, plan, project_dir, exe_name)
                artifacts.append(artifact)
            success = True
            return BuildResult(build_id, True, workspace, artifacts[0], log_file, artifacts=artifacts)
        except Exception as exc:
            with log_file.open("a", encoding="utf-8") as log:
                log.write("\nMULTI BUILD FAILED: " + str(exc) + "\n")
            return BuildResult(build_id, False, workspace, None, log_file, str(exc))
        finally:
            marker.write_text(json.dumps(dict(status="SUCCESS" if success else "FAILED", build_id=build_id, finished_at=time.time())), encoding="utf-8")

    @staticmethod
    def _stage_sidecars(
        artifact: Path,
        executable: Path,
        plan: BuildPlan | None,
        project_dir: Path,
        exe_name: str,
    ) -> Path:
        if not plan or not plan.sidecar_files:
            return artifact

        if plan.mode == "onefile":
            package_dir = artifact.parent / f"{exe_name}-package"
            if package_dir.exists():
                shutil.rmtree(package_dir)
            package_dir.mkdir(parents=True)
            shutil.move(str(executable), package_dir / executable.name)
        else:
            package_dir = artifact

        for source_path, destination in plan.sidecar_files:
            source = project_dir / source_path
            target_dir = package_dir / destination
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / source.name
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)

        return package_dir

    @staticmethod
    def _prepare_entry(entry: Path, project_dir: Path, workspace: Path) -> tuple[Path, list[str]]:
        """Preserve python -m semantics for entries inside regular packages."""
        package_dir = entry.parent
        parts = [entry.stem]
        while package_dir.is_relative_to(project_dir) and (package_dir / '__init__.py').is_file():
            parts.insert(0, package_dir.name)
            package_dir = package_dir.parent
        if len(parts) == 1:
            return entry, []
        module = '.'.join(parts)
        # runpy supplies __package__, __spec__, and the __main__ guard. Explicit
        # hidden-import makes the dynamically executed module visible to analysis.
        launcher = workspace / '_builder_entry.py'
        launcher.write_text(
            'import runpy\n'
            "if __name__ == '__main__':\n"
            f"    runpy.run_module({module!r}, run_name='__main__', alter_sys=True)\n",
            encoding='utf-8',
        )
        return launcher, ['--paths', str(package_dir), '--hidden-import', module]

    def _copy_source(self, source: Path, requested_entry: Path | None, project_dir: Path) -> Path:
        if source.is_file():
            project_dir.mkdir(parents=True)
            entry = project_dir / source.name
            shutil.copy2(source, entry)
            return entry

        def ignore(directory, names):
            ignored = set(shutil.ignore_patterns('.git', '.venv', 'venv', 'build', 'dist', '__pycache__', '.pytest_cache', '.pytest-tmp*', 'workspace', 'web-data')(directory, names))
            for name in names:
                path = Path(directory) / name
                if path.resolve() == self.workspace_root:
                    ignored.add(name)
                elif name not in ignored and (path.is_symlink() or not path.resolve().is_relative_to(source)):
                    raise ValueError('Project contains a link outside its source tree')
            return ignored
        shutil.copytree(
            source,
            project_dir,
            ignore=ignore,
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
            remaining = getattr(self, '_deadline', time.monotonic() + self.timeout) - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Build timeout exceeded')
            returncode = self.backend.run(command, cwd, log, remaining)
            log.write(f"\n[exit_code={returncode}]\n")
            if returncode != 0:
                raise RuntimeError(f"Command failed ({returncode}): {' '.join(command)}")
