# V1 deployment and security boundary

Smart Python Builder V1 is a **trusted/internal Windows Builder**.
Python projects, package installation/build backends and PyInstaller hooks can execute
code as the worker user. Independent virtual environments isolate dependencies;
they are not a security sandbox. Do not expose this service to anonymous or
untrusted users. Upload/ZIP validation does not change this boundary.

## Run with least privilege

Use a dedicated standard Windows account (not Administrator) with user-installed
Python and uv. Grant it write access only to the builder data/workspace directory
and its package cache. Start from a directory it owns:

```powershell
uv sync --locked
uv run uvicorn web.app:app --host 127.0.0.1 --port 8000
```

Keep the default loopback binding. For internal network deployment, place an
organization-authenticated reverse proxy in front, restrict Windows Firewall,
set `BUILDER_ALLOWED_HOSTS`, and configure `BUILDER_BASE_URL` for notification links.
The administrator API additionally requires `BUILDER_ADMIN_TOKEN`. Store secrets
in the service account environment; never in source control. Runtime under an
independently provisioned low-privilege Windows account is a deployment check;
the current acceptance suite runs under the supplied local account.

## Controls and defaults

- Uploads: .py / .zip only, 20 MiB file limit and bounded HTTP request body.
- ZIP: 100 MiB expanded total, at most 2,000 entries; rejects traversal, absolute
  paths, drive/ADS paths, links, duplicate/case-colliding paths, reserved Windows
  names and trailing-dot/space aliases.
- Build: independent workspace and environment; total command budget 900 seconds
  per attempt; timeout terminates the process tree. AI retries at most twice.
- Worker: one active build, at most eight active/queued tasks in the Web process.
  Numeric-library thread counts and uv concurrent builds/installations are capped.
  Run a single uvicorn worker; this is not a distributed queue.
- Disk: each attempt checks at least 1 GiB free before installation/build.
- Retention: terminal workspaces and their artifacts expire after seven days;
  `BUILDER_RETENTION_DAYS` can increase retention. Startup/hourly maintenance only
  removes validated managed workspace paths; active/unrecognized directories are
  preserved. Expired upload sources are removed, job summaries remain EXPIRED.
- Recovery: persisted queued/running/repairing jobs become NEEDS_MANUAL_REVIEW on
  service restart; they are not blindly re-executed. Ready jobs and completed
  download records survive restart. Missing/expired artifacts return HTTP 410.
- Logs: every subprocess command and exit code, build exception, plan, attempt
  history, and notification delivery failure type are recorded. Logs can contain
  project output and must remain internal. AI receives bounded diagnostic context
  only when explicitly configured. Notification failures never alter build status.
- Approved experiences are SQLite-backed and conservatively match Python source
  fingerprints and dependency declarations. Approvals require authentication;
  rejected or unreviewed candidates never affect plans.

## Extension boundary

`builder.execution.ExecutionBackend` is the injection boundary for future sandbox
or ephemeral-VM execution. The current LocalWindowsBackend runs locally with the
worker identity. Before accepting untrusted projects, move copying, installation,
packaging and optional artifact verification inside an ephemeral isolated worker,
with restricted network and resource quotas. V1 does not claim VM isolation or
hard per-process CPU/memory quotas.

## Acceptance

```powershell
uv run pytest tests -q --basetemp .pytest-tmp-check
uv run python tests/windows_v1_acceptance.py
```

`docs/v1-acceptance.json` records per-case PASS, Build ID, artifact and behavior.
Several library cases share a combined executable; each library has an independent
functional assertion. Console EXEs must exit 0 and satisfy output/behavior checks.
GUI EXEs must stay alive for ten seconds before their test process tree is closed.
Deliberate failure cases PASS when the expected failure/repair state is observed.
FakeAIProvider and FakeNotifier are used: real AI billing/credentials and actual
Feishu delivery are not part of offline acceptance.
