# Phase 1 Windows verification

Status: `IN_PROGRESS`

## Prerequisites

Install `uv` on the Windows build machine and make sure `uv --version` works in PowerShell.

## Case A — standard library / Tkinter GUI

```powershell
python build.py tests\samples\tkinter_app.py --windowed --name case-a
```

Expected:

1. A unique `workspace/<build-id>/` is created.
2. It contains `pyproject.toml`, `uv.lock`, `.venv`, `build.log`, `build/` and `dist/`.
3. `workspace/<build-id>/dist/case-a.exe` exists.
4. Double-clicking `case-a.exe` opens a window containing `Case A build succeeded`.
5. `build.log` contains each uv/PyInstaller command and its exit code.

Do not close Phase 1 after Case A. Case B and Case C must also pass.

## Case B — third-party packages

To be added after Case A is verified on Windows.

## Case C — PySide6 GUI

To be added after Case B is verified.
