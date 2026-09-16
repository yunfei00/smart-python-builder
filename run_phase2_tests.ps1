$ErrorActionPreference = "Stop"

Write-Host "=== Smart Python Builder / Phase 2 ==="
uv --version
python --version

Write-Host "`n[1] Unit tests"
python -m pytest tests/test_analyzer.py -q

Write-Host "`n[2] Analyze OpenCV project"
python analyze.py tests/phase2_samples/opencv_app

Write-Host "`n[3] Build OpenCV project with automatically detected dependencies"
python build.py tests/phase2_samples/opencv_app --name phase2-opencv

Write-Host "`n[4] Analyze multi-file PySide6 project (helpers must be internal, not PyPI)"
python analyze.py tests/phase2_samples/pyside_project

Write-Host "`n[5] Build multi-file PySide6 project with automatically detected dependencies"
python build.py tests/phase2_samples/pyside_project --windowed --name phase2-pyside

Write-Host "`nPhase 2 automated verification completed."
Write-Host "Manually run the generated OpenCV EXE and PySide6 EXE before closing Phase 2."
