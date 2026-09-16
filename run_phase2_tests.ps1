$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

Write-Host "=== Smart Python Builder / Phase 2 ==="
Invoke-Checked { uv --version }
Invoke-Checked { python --version }

# Some Windows machines have stale/ACL-restricted %TEMP%\pytest-of-<user>
# directories. Keep Phase 2 test scratch data inside this repository instead.
$pytestTemp = Join-Path $PSScriptRoot ".pytest-tmp-phase2"
if (Test-Path $pytestTemp) {
    Remove-Item -Recurse -Force $pytestTemp
}
New-Item -ItemType Directory -Force -Path $pytestTemp | Out-Null

Write-Host "`n[1] Unit tests"
Invoke-Checked { uv run --with pytest python -m pytest tests/test_analyzer.py -q --basetemp $pytestTemp }

Write-Host "`n[2] Analyze OpenCV project"
Invoke-Checked { python analyze.py tests/phase2_samples/opencv_app }

Write-Host "`n[3] Build OpenCV project with automatically detected dependencies"
Invoke-Checked { python build.py tests/phase2_samples/opencv_app --name phase2-opencv }

Write-Host "`n[4] Analyze multi-file PySide6 project (helpers must be internal, not PyPI)"
Invoke-Checked { python analyze.py tests/phase2_samples/pyside_project }

Write-Host "`n[5] Build multi-file PySide6 project with automatically detected dependencies"
Invoke-Checked { python build.py tests/phase2_samples/pyside_project --windowed --name phase2-pyside }

Write-Host "`nPhase 2 automated verification completed."
Write-Host "Manually run the generated OpenCV EXE and PySide6 EXE before closing Phase 2."
