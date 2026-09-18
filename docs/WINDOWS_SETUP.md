# Windows build machine setup

Smart Python Builder requires Windows, 64-bit Python 3.11+ and uv available on `PATH`.
Git must also be available when importing GitHub repositories or installing GitHub VCS dependencies.

Verify:

```powershell
python --version
uv --version
git --version
```

Install the project environment and run the automated suite:

```powershell
uv sync --locked
uv run pytest
```

Run the Web service locally:

```powershell
$env:BUILDER_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Admin password' -AsSecureString)).Password
uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
```

For a release candidate, also run the maintained Windows acceptance entry point:

```powershell
uv run python tests/windows_acceptance.py
```

The build engine installs each target project's dependencies and PyInstaller into its own
uv-managed workspace; global requests, pandas, Qt or PyInstaller installations are not required.
