# Phase 1 — Build Engine

Current implementation provides a command-line build engine for one Python entry file on Windows.

```powershell
python build.py path\to\app.py --package requests --windowed
```

Each invocation creates a UUID workspace, copies only the uploaded source into it, initializes a uv project, installs only explicitly requested application dependencies plus PyInstaller, builds a one-file Windows executable, and records all build commands and exit codes in `build.log`.

See `docs/PHASE1_COMMANDS.md` for the three mandatory verification cases. Do not merge/close Phase 1 until all three generated executables are manually verified on Windows.
