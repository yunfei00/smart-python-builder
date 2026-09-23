from pathlib import Path
import json
import os
import subprocess
import sys

import pytest

from analyzer import analyze_project
from builder import BuildEngine, BuildRequest, SmartBuilder


def test_rejects_non_python_source(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        BuildEngine(tmp_path / "workspace").build(BuildRequest(source=source))


def test_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BuildEngine(tmp_path / "workspace").build(BuildRequest(source=tmp_path / "missing.py"))


def test_environment_is_outside_uploaded_metadata(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('ok')", encoding="utf-8")
    metadata = '[project]\nname="original"\ndependencies=[]\n'
    (source / "pyproject.toml").write_text(metadata, encoding="utf-8")
    (source / "asset.json").write_text('{}', encoding="utf-8")
    engine = BuildEngine(tmp_path / "workspace")
    calls = []
    def run(command, cwd, log_file):
        calls.append((command, cwd))
        if command[0].endswith("pyinstaller.exe"):
            (cwd / "dist").mkdir()
            (cwd / "dist" / "main.exe").write_bytes(b"test")
    monkeypatch.setattr(engine, "_run", run)
    monkeypatch.setattr(engine, "_smoke_test_executable", lambda *args, **kwargs: None)
    result = engine.build(BuildRequest(source, entry_point=source / "main.py"))
    assert result.success
    assert calls[0][1] == result.workspace
    assert (result.workspace / "project" / "pyproject.toml").read_text(encoding="utf-8") == metadata
    assert (result.workspace / "project" / "asset.json").is_file()


def test_fake_success_without_artifact_fails(tmp_path,monkeypatch):
    source=tmp_path/'main.py';source.write_text('print(1)')
    engine=BuildEngine(tmp_path/'workspace')
    monkeypatch.setattr(engine,'_run',lambda *args:None)
    result=engine.build(BuildRequest(source))
    assert not result.success and 'artifact is missing' in result.error


@pytest.mark.parametrize('layout', ['', 'src'])
@pytest.mark.parametrize('entry_name', ['__main__', 'app'])
def test_package_launcher_preserves_module_context(tmp_path, layout, entry_name):
    project = tmp_path / 'project'
    package = project / layout / 'demo' / 'nested'
    package.mkdir(parents=True)
    (package.parent / '__init__.py').write_text('')
    (package / '__init__.py').write_text('')
    (package.parent / 'helper.py').write_text('value = "package-ok"')
    entry = package / f'{entry_name}.py'
    entry.write_text(
        'from ..helper import value\nimport sys\n'
        'if __name__ == "__main__":\n'
        '    print(value, __package__, __spec__.name, sys.argv[1])\n'
        '    raise SystemExit(7)\n'
    )
    launcher, args = BuildEngine._prepare_entry(entry, project, tmp_path)
    module = f'demo.nested.{entry_name}'
    assert args == ['--paths', str(project / layout), '--hidden-import', module]
    result = subprocess.run([sys.executable, str(launcher), 'argument'],
                            cwd=tmp_path, env={**os.environ, 'PYTHONPATH': str(project / layout)},
                            capture_output=True, text=True)
    assert result.returncode == 7, result.stderr
    assert result.stdout.strip() == f'package-ok demo.nested {module} argument'


def test_plain_script_does_not_get_package_launcher(tmp_path):
    entry = tmp_path / 'main.py'
    entry.write_text('print("ok")')
    assert BuildEngine._prepare_entry(entry, tmp_path, tmp_path) == (entry, [])


@pytest.mark.parametrize('layout', ['', 'src'])
@pytest.mark.parametrize('entry_name', ['__main__', 'app'])
def test_package_launcher_preserves_module_context(tmp_path, layout, entry_name):
    project = tmp_path / 'project'
    package = project / layout / 'demo' / 'nested'
    package.mkdir(parents=True)
    (package.parent / '__init__.py').write_text('')
    (package / '__init__.py').write_text('')
    (package.parent / 'helper.py').write_text('value = "package-ok"')
    entry = package / f'{entry_name}.py'
    entry.write_text(
        'from ..helper import value\nimport sys\n'
        'if __name__ == "__main__":\n'
        '    print(value, __package__, __spec__.name, sys.argv[1])\n'
        '    raise SystemExit(7)\n'
    )
    launcher, args = BuildEngine._prepare_entry(entry, project, tmp_path)
    module = f'demo.nested.{entry_name}'
    assert args == ['--paths', str(project / layout), '--hidden-import', module]
    result = subprocess.run([sys.executable, str(launcher), 'argument'],
                            cwd=tmp_path, env={**os.environ, 'PYTHONPATH': str(project / layout)},
                            capture_output=True, text=True)
    assert result.returncode == 7, result.stderr
    assert result.stdout.strip() == f'package-ok demo.nested {module} argument'


def test_plain_script_does_not_get_package_launcher(tmp_path):
    entry = tmp_path / 'main.py'
    entry.write_text('print("ok")')
    assert BuildEngine._prepare_entry(entry, tmp_path, tmp_path) == (entry, [])


def test_executable_sidecars_are_precise_and_build_info_is_generated(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "VERSION").write_text("0.2.0-dev\n", encoding="ascii")
    (source / "app_info.py").write_text(
        """import sys
from pathlib import Path

def resource_path(name):
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / name
    return Path(__file__).resolve().parent / name

VERSION_PATH = resource_path("VERSION")
BUILD_INFO_PATH = resource_path("BUILD_INFO.json")
UNRELATED = "main.py"
""",
        encoding="utf-8",
    )
    (source / "main.py").write_text(
        """import json
from app_info import VERSION_PATH, BUILD_INFO_PATH
print(VERSION_PATH.read_text(encoding="ascii").strip())
print(json.loads(BUILD_INFO_PATH.read_text(encoding="utf-8"))["version"])
""",
        encoding="utf-8",
    )

    analysis = analyze_project(source)
    builder = SmartBuilder(tmp_path / "workspace")
    plan = builder.experiences.plan(analysis, analysis.entry_point)

    assert ["VERSION", "."] in plan.sidecar_files
    assert ["BUILD_INFO.json", "."] in plan.generated_sidecars
    assert ["BUILD_INFO.json", "."] not in plan.data_files + plan.sidecar_files
    plan.validate(source)
    assert all(item[0] != "main.py" for item in plan.sidecar_files)

    engine = BuildEngine(tmp_path / "workspace-engine")
    monkeypatch.setattr("builder.engine.shutil.which", lambda name: "uv.exe")

    def fake_run(command, cwd, log_file):
        if str(command[0]).endswith("pyinstaller.exe"):
            (cwd / "dist").mkdir(exist_ok=True)
            (cwd / "dist" / "main.exe").write_bytes(b"test")

    monkeypatch.setattr(engine, "_run", fake_run)
    monkeypatch.setattr(engine, "_smoke_test_executable", lambda *args, **kwargs: None)

    result = engine.build(BuildRequest(source, entry_point=source / "main.py", plan=plan))
    assert result.success, result.error
    assert result.artifact == result.workspace / "project" / "dist" / "main-package"
    assert (result.artifact / "main.exe").is_file()
    assert (result.artifact / "VERSION").read_text(encoding="ascii").strip() == "0.2.0-dev"
    assert not (result.artifact / "main.py").exists()

    build_info = json.loads((result.artifact / "BUILD_INFO.json").read_text(encoding="ascii"))
    assert build_info["version"] == "0.2.0-dev"
    assert len(build_info["commit"]) == 40
    assert build_info["built_at"]
    assert build_info["dirty"] is False


def test_smoke_test_failure_marks_build_failed(tmp_path, monkeypatch):
    source = tmp_path / "main.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    engine = BuildEngine(tmp_path / "workspace")
    monkeypatch.setattr("builder.engine.shutil.which", lambda name: "uv.exe")

    def fake_run(command, cwd, log_file):
        if str(command[0]).endswith("pyinstaller.exe"):
            (cwd / "dist").mkdir(exist_ok=True)
            (cwd / "dist" / "main.exe").write_bytes(b"test")

    monkeypatch.setattr(engine, "_run", fake_run)

    def fail_smoke(*args, **kwargs):
        raise RuntimeError("startup smoke failed")

    monkeypatch.setattr(engine, "_smoke_test_executable", fail_smoke)
    result = engine.build(BuildRequest(source))
    assert not result.success
    assert result.artifact is None
    assert "startup smoke failed" in result.error
