# Architecture

## Phase 1 boundary

`build.py` is only a CLI adapter. Build logic lives in `builder/BuildEngine`, so later FastAPI endpoints can call the same engine without embedding PyInstaller/uv logic in the web layer.

A build owns one UUID workspace. The build environment and artifacts never share a `.venv` with another build. uv's global cache may be reused for speed, but dependency installation state is isolated per task.

Phase 2 will add project/dependency analysis ahead of `BuildEngine`; Phase 4 will add the Web adapter; AI and notifications remain outside the core builder.
