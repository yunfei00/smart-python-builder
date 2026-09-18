# Architecture

Smart Python Builder 1.1 uses one shared build pipeline for the CLI and Web UI.

`analyzer/` inspects Python files/projects, detects entry points and dependencies, and preserves
supported `pyproject.toml` requirements including validated public GitHub VCS dependencies.
`builder/` owns BuildPlan validation, experience matching, isolated uv workspaces, PyInstaller
execution, bounded AI repair, notifications, persistence and settings. `web/` provides upload,
public GitHub repository import, build/download APIs, the user interface and administrator UI.

Each build receives a UUID workspace with its own project copy, `pyproject.toml`, `.venv`,
build directory, dist directory and logs. Dependency isolation is not a security sandbox:
Python projects and dependency build backends can execute code as the Builder service account.

Public GitHub import accepts HTTPS github.com owner/repository URLs, optional validated refs,
does not recurse submodules, removes clone metadata after import and applies repository tree
limits before analysis. VCS package dependencies are limited to validated
`name @ git+https://github.com/owner/repository.git[@ref]` declarations.

`builder/settings.py` owns configuration validation, environment overrides, SQLite persistence,
DPAPI-backed Windows secrets, password hashes and sessions. Explicit environment variables take
precedence over saved settings, which take precedence over defaults. AI and Feishu clients are
created from effective settings for new builds; fake providers exist only through explicit test
injection.

The Web process uses one build worker and a bounded queue. Download availability is validated
server-side. AI returns validated structured RepairPlans and may retry at most twice. Successful
AI repairs become experience candidates; only administrator-approved experiences participate in
future planning. Notification failures never change the build result.

The primary long-term modules are:

- `analyzer/`: source/project analysis.
- `builder/`: build engine, plans, AI, experience, notifications and settings.
- `web/`: FastAPI/Jinja2 application and repository import.
- `tests/`: automated regression tests plus Windows acceptance scripts.
- `docs/`: architecture, operations, Windows setup and release procedure.
