# Windows build machine setup

Phase 1 requires Windows, Python 3.11+ and uv available on `PATH`.

Verify:

```powershell
python --version
uv --version
```

Then run:

```powershell
.\run_phase1_tests.ps1
```

No global `requests`, `pandas`, `PySide6`, or PyInstaller installation is required by the build engine. Each Build Task installs its requested packages into its own uv-managed `.venv`.
