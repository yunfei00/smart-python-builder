# Architecture

`build.py` and `web/app.py` adapt the shared SmartBuilder. Project analysis and
ExperienceEngine produce validated BuildPlans, BuildEngine creates UUID workspaces
and isolated uv environments, and the Windows execution backend runs PyInstaller.
AI proposes bounded RepairPlans; notification failures remain outside build success.
ExperienceStore persists candidates and applies only administrator-approved repairs.
The V1 builder/execution architecture is unchanged by v1.0.1.

`builder/settings.py` owns configuration validation, environment overrides, SQLite
persistence, DPAPI secrets, password hashes and session records. `web/admin.py`
provides login/session/CSRF, settings and connection-test routes. Web passes its
SettingsStore to SmartBuilder so new builds use the same effective configuration
as settings and test endpoints. CLI defaults to `web-data/settings.sqlite3`.
Production factories instantiate only real OpenAI-compatible/Feishu clients;
Fake providers are explicitly injected by tests, never selectable settings.

Hosts/retention are startup snapshots; AI/Feishu are per-new-build snapshots.
Static CSS and JavaScript are shipped inside the web package and templates share
admin navigation. Download availability is derived server-side from terminal state,
root confinement and a nonempty file, and checked again when downloading.

One process/one build worker and a bounded queue remain the deployment model.
Independent environments are dependency isolation, not a security sandbox.
