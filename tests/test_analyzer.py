from pathlib import Path

import pytest

from analyzer import analyze_project, resolve_package
from builder import EntryPointRequired, SmartBuilder, BuildResult


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
    write(tmp_path / "requirements.txt", "Pillow\n")
    result = analyze_project(tmp_path)
    assert result.dependency_source == "pyproject.toml"
    assert result.packages == ["requests>=2", "pandas"]



def test_pyproject_preserves_pep508_git_dependency(tmp_path):
    write(tmp_path / "main.py", "import android_dut_agent\n")
    write(
        tmp_path / "pyproject.toml",
        '[project]\nname="demo"\nversion="0.1.0"\ndependencies=["android-dut-agent @ git+https://github.com/example/android-dut-agent.git@v1.2.0"]\n',
    )
    result = analyze_project(tmp_path)
    assert result.dependency_source == "pyproject.toml"
    assert result.packages == [
        "android-dut-agent @ git+https://github.com/example/android-dut-agent.git@v1.2.0"
    ]


def test_ambiguous_entries_are_not_guessed(tmp_path):
    write(tmp_path / "main.py", "print('main')\n")
    write(tmp_path / "app.py", "print('app')\n")
    result = analyze_project(tmp_path)
    assert result.entry_point is None
    assert result.entry_is_ambiguous
    assert [p.name for p in result.entry_candidates] == ["main.py", "app.py"]


def test_smart_builder_requires_entry_for_ambiguous_project(tmp_path):
    write(tmp_path / "main.py", "print('main')\n")
    write(tmp_path / "app.py", "print('app')\n")
    builder = SmartBuilder(tmp_path / "workspace")
    with pytest.raises(EntryPointRequired):
        builder.build(tmp_path)


def test_smart_builder_accepts_explicit_entry_without_building(tmp_path, monkeypatch):
    write(tmp_path / "main.py", "import requests\n")
    write(tmp_path / "app.py", "print('app')\n")
    builder = SmartBuilder(tmp_path / "workspace")
    captured = {}

    def fake_build(request):
        captured["request"] = request
        return BuildResult('test', True, tmp_path, tmp_path / 'main.exe', tmp_path / 'build.log')

    monkeypatch.setattr(builder.engine, "build", fake_build)
    result = builder.build(tmp_path, entry_point="main.py")
    assert result.analysis.packages == ["requests"]
    assert captured["request"].entry_point == (tmp_path / "main.py").resolve()


def test_empty_pyproject_dependencies_are_authoritative(tmp_path):
    write(tmp_path / "main.py", "import requests\n")
    write(tmp_path / "pyproject.toml", "[project]\ndependencies=[]\n")
    write(tmp_path / "requirements.txt", "Pillow\n")
    result = analyze_project(tmp_path)
    assert result.packages == []
    assert result.dependency_source == "pyproject.toml"


def test_imported_optional_dependencies_preserve_constraints_and_skip_tests(tmp_path):
    write(tmp_path / 'src' / 'demo' / '__main__.py', 'import PySide6\nimport pyvisa\nimport requests\n')
    write(tmp_path / 'tests' / 'test_gui.py', 'import pytest\n')
    write(tmp_path / 'pyproject.toml', '''[project]
dependencies = ["requests==2.32.5"]
[project.optional-dependencies]
gui = ["PySide6>=6.5", "requests>=2"]
visa = ["pyvisa>=1.14"]
dev = ["pytest>=7.4", "ruff"]
''')
    result = analyze_project(tmp_path)
    assert result.packages == ['requests==2.32.5', 'PySide6>=6.5', 'pyvisa>=1.14']
    assert result.dependency_source == 'pyproject.toml'


@pytest.mark.parametrize("metadata", ["broken [", "[project]\nname='demo'\n"])
def test_unusable_pyproject_falls_back_to_requirements(tmp_path, metadata):
    write(tmp_path / "main.py", "import requests\n")
    write(tmp_path / "pyproject.toml", metadata)
    write(tmp_path / "requirements.txt", "Pillow\n")
    result = analyze_project(tmp_path)
    assert result.packages == ["Pillow"]
    assert result.dependency_source == "requirements.txt"


def test_entry_cannot_escape_project(tmp_path):
    write(tmp_path / "main.py", "print('ok')")
    with pytest.raises(ValueError, match="inside"):
        SmartBuilder(tmp_path / "workspace").build(tmp_path, entry_point="../outside.py")


def test_python_source_encoding_cookie(tmp_path):
    source=tmp_path/'main.py'
    source.write_bytes("# coding: cp1252\n# café\nimport json\n".encode('cp1252'))
    assert analyze_project(source).packages==[]


def test_git_dependency_build_plan_validation(tmp_path):
    from builder.models import BuildPlan
    write(tmp_path / "main.py", "print(1)\n")
    dependency = "android-dut-agent @ git+https://github.com/example/android-dut-agent.git@v1.2.0"
    plan = BuildPlan("main.py", [dependency], "pyproject.toml")
    plan.validate(tmp_path)


def test_discovers_nonconventional_runnable_entries(tmp_path):
    write(tmp_path / "scripts" / "run_gui.py", """
from PySide6.QtWidgets import QApplication

def main():
    app = QApplication([])
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
""")
    write(tmp_path / "tools" / "capture_cli.py", """
def main():
    print("capture")

if __name__ == "__main__":
    main()
""")
    result = analyze_project(tmp_path)
    entries = [path.relative_to(tmp_path).as_posix() for path in result.entry_candidates]
    assert entries == ["scripts/run_gui.py", "tools/capture_cli.py"]
    assert result.entry_point is None
    assert result.entry_is_ambiguous


def test_entry_discovery_excludes_test_launchers(tmp_path):
    write(tmp_path / "main.py", "print('main')\n")
    write(tmp_path / "tests" / "run.py", "if __name__ == '__main__':\n    print('test')\n")
    write(tmp_path / "test_tool.py", "if __name__ == '__main__':\n    print('test')\n")
    result = analyze_project(tmp_path)
    assert result.entry_point == (tmp_path / "main.py").resolve()
    assert result.entry_candidates == [(tmp_path / "main.py").resolve()]


def test_classifies_recommended_internal_and_auxiliary_entries(tmp_path):
    write(tmp_path / "src" / "demo" / "ui" / "app.py", """
from PySide6.QtWidgets import QApplication
def main():
    app = QApplication([])
    return app.exec()
""")
    write(tmp_path / "scripts" / "run_gui.py", """
def main():
    pass
if __name__ == "__main__":
    main()
""")
    write(tmp_path / "scripts" / "run_combined_capture.py", """
def main():
    pass
if __name__ == "__main__":
    main()
""")
    write(tmp_path / "scripts" / "gui_smoke.py", """
if __name__ == "__main__":
    print("smoke")
""")
    write(tmp_path / "scripts" / "probe_fsw.py", """
if __name__ == "__main__":
    print("probe")
""")
    result = analyze_project(tmp_path)
    details = {item["path"]: item for item in result.entry_details}
    assert details["scripts/run_gui.py"]["recommended"] is True
    assert details["scripts/run_combined_capture.py"]["recommended"] is True
    assert details["src/demo/ui/app.py"]["kind"] == "internal"
    assert details["src/demo/ui/app.py"]["recommended"] is False
    assert details["scripts/gui_smoke.py"]["kind"] == "auxiliary"
    assert details["scripts/probe_fsw.py"]["kind"] == "auxiliary"



def test_classifies_diagnostic_checkers_as_auxiliary(tmp_path):
    write(tmp_path / "packaging" / "check_windows_dependencies.py", """
def main():
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
""")
    write(tmp_path / "tools" / "verify_installation.py", """
def main():
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
""")
    write(tmp_path / "scripts" / "run_gui.py", """
def main():
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
""")
    result = analyze_project(tmp_path)
    details = {item["path"]: item for item in result.entry_details}
    assert details["packaging/check_windows_dependencies.py"]["kind"] == "auxiliary"
    assert details["packaging/check_windows_dependencies.py"]["recommended"] is False
    assert details["tools/verify_installation.py"]["kind"] == "auxiliary"
    assert details["tools/verify_installation.py"]["recommended"] is False
    assert details["scripts/run_gui.py"]["kind"] == "application"
    assert details["scripts/run_gui.py"]["recommended"] is True
