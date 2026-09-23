from pathlib import Path
import os
import subprocess
import sys
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


def test_sys_executable_resource_is_packaged_beside_onefile_exe(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "print((Path(sys.executable).resolve().parent / 'VERSION').read_text())\n",
        encoding="utf-8",
    )
    (source / "VERSION").write_text("1.2.3\n", encoding="ascii")

    analysis = analyze_project(source)
    builder = SmartBuilder(tmp_path / "workspace")
    plan = builder.experiences.plan(analysis, analysis.entry_point)
    assert ["VERSION", "."] in plan.sidecar_files
    assert ["VERSION", "."] in plan.data_files

    engine = BuildEngine(tmp_path / "workspace-engine")
    monkeypatch.setattr("builder.engine.shutil.which", lambda name: "uv.exe")
    def fake_run(command, cwd, log_file):
        if str(command[0]).endswith("pyinstaller.exe"):
            (cwd / "dist").mkdir(exist_ok=True)
            (cwd / "dist" / "main.exe").write_bytes(b"test")
    monkeypatch.setattr(engine, "_run", fake_run)

    result = engine.build(BuildRequest(source, entry_point=source / "main.py", plan=plan))
    assert result.success, result.error
    assert result.artifact == result.workspace / "project" / "dist" / "main-package"
    assert (result.artifact / "main.exe").is_file()
    assert (result.artifact / "VERSION").read_text(encoding="ascii").strip() == "1.2.3"
