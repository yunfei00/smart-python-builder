from pathlib import Path

import pytest

from builder import BuildEngine, BuildRequest


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
