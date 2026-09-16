from pathlib import Path

from analyzer import analyze_project, resolve_package


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_package_mapping():
    assert resolve_package("cv2") == "opencv-python"
    assert resolve_package("PIL") == "Pillow"
    assert resolve_package("yaml") == "PyYAML"
    assert resolve_package("serial") == "pyserial"
    assert resolve_package("sklearn") == "scikit-learn"
    assert resolve_package("bs4") == "beautifulsoup4"
    assert resolve_package("requests") == "requests"


def test_single_file_filters_stdlib(tmp_path):
    source = tmp_path / "tool.py"
    write(source, "import os\nimport json\nimport requests\n")
    result = analyze_project(source)
    assert result.entry_point == source.resolve()
    assert {"os", "json"} <= result.stdlib_imports
    assert result.third_party_imports == {"requests"}
    assert result.packages == ["requests"]


def test_multifile_internal_module_is_not_package(tmp_path):
    write(tmp_path / "main.py", "import os\nimport cv2\nfrom utils.helper import value\n")
    write(tmp_path / "utils" / "__init__.py", "")
    write(tmp_path / "utils" / "helper.py", "value = 1\n")
    result = analyze_project(tmp_path)
    assert result.entry_point == (tmp_path / "main.py").resolve()
    assert "utils" in result.internal_imports
    assert "utils" not in result.third_party_imports
    assert result.packages == ["opencv-python"]


def test_requirements_has_priority(tmp_path):
    write(tmp_path / "main.py", "import requests\n")
    write(tmp_path / "requirements.txt", "requests==2.32.5\nPillow>=10\n")
    result = analyze_project(tmp_path)
    assert result.dependency_source == "requirements.txt"
    assert result.packages == ["requests==2.32.5", "Pillow>=10"]


def test_pyproject_has_priority(tmp_path):
    write(tmp_path / "main.py", "import requests\n")
    write(tmp_path / "pyproject.toml", '[project]\nname="demo"\nversion="0.1.0"\ndependencies=["requests>=2", "pandas"]\n')
    result = analyze_project(tmp_path)
    assert result.dependency_source == "pyproject.toml"
    assert result.packages == ["requests>=2", "pandas"]


def test_ambiguous_entries_are_not_guessed(tmp_path):
    write(tmp_path / "main.py", "print('main')\n")
    write(tmp_path / "app.py", "print('app')\n")
    result = analyze_project(tmp_path)
    assert result.entry_point is None
    assert result.entry_is_ambiguous
    assert [p.name for p in result.entry_candidates] == ["main.py", "app.py"]
