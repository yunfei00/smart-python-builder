# Phase 1 build commands

Run these commands on the Windows build machine from the repository root.

```powershell
uv --version
python --version
```

## Case A — Tkinter / standard library

```powershell
python build.py tests\samples\tkinter_app.py --windowed --name case-a
```

## Case B — isolated third-party dependencies

```powershell
python build.py tests\samples\third_party_app.py --package requests --package pandas --name case-b
```

## Case C — PySide6 GUI

```powershell
python build.py tests\samples\pyside6_app.py --package PySide6 --windowed --name case-c
```

For every command, record the Build ID printed by the CLI. Verify its workspace contains an independent `.venv`, `pyproject.toml`, `uv.lock`, `build.log`, `build/`, and `dist/`. Run each generated EXE on Windows.

Phase 1 remains `VERIFYING` until all three executables have been manually launched successfully.
