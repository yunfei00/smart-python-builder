"""Real Windows builds and executable checks; invoked explicitly, not by pytest."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyzer import analyze_project
from builder import SmartBuilder


def verify_executable(artifact: Path, *, gui: bool = False, expected: str = "") -> str:
    assert artifact.is_file() and artifact.stat().st_size > 0, artifact
    if not gui:
        result = subprocess.run([str(artifact)], capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout, result.stdout
        return result.stdout.strip()
    process = subprocess.Popen([str(artifact)])
    try:
        time.sleep(10)
        assert process.poll() is None, f"GUI exited early: {process.returncode}"
        return "GUI process remained alive for 10 seconds; test process tree stopped"
    finally:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        process.wait(timeout=15)


def phase2():
    root = Path(__file__).resolve().parents[1]
    records = []
    for name, gui, expected, packages in [
        ("opencv_app", False, "shape (120, 240, 3)", ["numpy", "opencv-python"]),
        ("pyside_project", True, "", ["PySide6"]),
    ]:
        source = root / "tests" / "phase2_samples" / name
        analysis = analyze_project(source)
        assert analysis.packages == packages
        if gui:
            assert "helpers" in analysis.internal_imports
        result = SmartBuilder(root / "workspace").build(source, windowed=gui, app_name=f"phase2-{name}").build
        assert result.success, f"{result.error}: {result.log_file}"
        notes = verify_executable(result.artifact, gui=gui, expected=expected)
        records.append(dict(case=name, status="PASS", build_id=result.build_id, artifact=str(result.artifact), notes=notes))
        print(json.dumps(records[-1]), flush=True)
    # A real metadata-bearing project catches uv-init collisions that AST-only
    # samples cannot detect.
    source = root / ".pytest-tmp-metadata"
    source.mkdir(exist_ok=True)
    (source / "main.py").write_text("print('metadata-ok')\n", encoding="utf-8")
    (source / "pyproject.toml").write_text('[project]\nname="metadata-demo"\nversion="1.0"\ndependencies=[]\n', encoding="utf-8")
    result = SmartBuilder(root / "workspace").build(source, app_name="phase2-metadata").build
    assert result.success, f"{result.error}: {result.log_file}"
    notes = verify_executable(result.artifact, expected="metadata-ok")
    records.append(dict(case="pyproject-project", status="PASS", build_id=result.build_id, artifact=str(result.artifact), notes=notes))
    output = root / "docs" / "phase2-acceptance.json"
    output.write_text(json.dumps(records, indent=2), encoding="utf-8")


if __name__ == "__main__":
    phase2()
