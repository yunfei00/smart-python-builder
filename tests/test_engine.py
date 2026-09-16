from pathlib import Path

import pytest

from builder import BuildEngine, BuildRequest


def test_rejects_non_python_source(tmp_path: Path) -> None:
    source = tmp_path / "input.txt"
    source.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        BuildEngine(tmp_path / "workspace").build(BuildRequest(source=source))


def test_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BuildEngine(tmp_path / "workspace").build(BuildRequest(source=tmp_path / "missing.py"))
