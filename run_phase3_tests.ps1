$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
uv run --with pytest python -m pytest tests -q --basetemp (Join-Path $PSScriptRoot ('.pytest-tmp-phase3-' + [guid]::NewGuid().ToString('N')))
if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed' }
python tests/windows_acceptance.py phase3-acceptance.json
if ($LASTEXITCODE -ne 0) { throw 'Executable acceptance failed' }
