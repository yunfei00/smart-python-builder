# Phase 1 status

Status: `VERIFYING`

Implemented:

- UUID-isolated workspace per build.
- uv project initialization and per-build `.venv`.
- Explicit application dependency installation.
- Per-build PyInstaller installation.
- one-file console/windowed builds.
- configurable application name.
- persistent command/exit-code build log.
- CLI entry point.
- Case A/B/C sample applications.
- Windows verification runner.

Remaining before `CLOSED`:

- Run `run_phase1_tests.ps1` on the target Windows machine.
- Manually launch Case A, B, and C executables.
- Confirm independent `.venv` directories and complete `build.log` for each build.
- Record any failure and fix it before closing Issue #1.
