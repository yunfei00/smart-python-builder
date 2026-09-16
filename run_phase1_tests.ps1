$ErrorActionPreference = "Stop"

Write-Host "=== Smart Python Builder / Phase 1 ==="
uv --version
python --version

Write-Host "`n[Case A] Tkinter"
uv run python build.py tests\samples\tkinter_app.py --windowed --name case-a
if ($LASTEXITCODE -ne 0) { throw "Case A build failed" }

Write-Host "`n[Case B] requests + pandas"
uv run python build.py tests\samples\third_party_app.py --name case-b
if ($LASTEXITCODE -ne 0) { throw "Case B build failed" }

Write-Host "`n[Case C] PySide6"
uv run python build.py tests\samples\pyside6_app.py --windowed --name case-c
if ($LASTEXITCODE -ne 0) { throw "Case C build failed" }

Write-Host "`nAll three builds completed. Manually launch each printed EXE before closing Phase 1."
