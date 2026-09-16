$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Invoke-Checked {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE" }
}
Invoke-Checked { uv --version }
Invoke-Checked { python --version }
$pytestTemp = Join-Path $PSScriptRoot (".pytest-tmp-phase2-" + [guid]::NewGuid().ToString('N'))
Invoke-Checked { uv run --with pytest python -m pytest tests -q --basetemp $pytestTemp }
Invoke-Checked { uv run python tests/windows_acceptance.py }
Write-Host "Phase 2: all tests and real EXE checks passed. See docs/phase2-acceptance.json."
