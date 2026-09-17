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
The administrator API accepts password sessions with CSRF protection or the legacy
`BUILDER_ADMIN_TOKEN` Bearer credential. Configure secrets through admin settings or
the service account environment; never in source control. Runtime under an
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

## v1.0.1 settings and administrator operations

Set `BUILDER_ADMIN_PASSWORD` before the first start. `/admin/login` explicitly reports
an uninitialized administrator if absent; there is no default password. Bootstrap
only creates a missing password hash and never overwrites an existing one. Remove
the bootstrap variable after initialization. Password hashing uses stdlib scrypt
(N=16384, r=8, p=1), a random 16-byte salt and constant-time comparison. No new
cryptographic dependency was added. Use a long, unique administrator password.

Sessions use 256-bit random tokens, eight-hour expiry, HttpOnly / SameSite=Lax
cookies, and database token hashes. Logout revokes the session. Mutating session
APIs require a per-session X-CSRF-Token; the Origin scheme and host must match
when present. Legacy Bearer API clients do not require CSRF tokens. Admin responses
are no-store. Ten failed logins per client address in five minutes are throttled
in the single server process; restarting clears this throttle. This is not a
public authentication platform. HTTP cookies are supported for controlled LAN;
for HTTPS set `BUILDER_COOKIE_SECURE=true` and correctly configure the trusted
reverse proxy scheme. Never expose an HTTP admin password on an untrusted network.

`web-data/settings.sqlite3` holds settings, password hashes and sessions. CLI and
Web share this settings path when launched from the same working directory;
custom `create_app(root=...)` deployments explicitly pass their store to Builder.
Default CLI and Web experience databases remain separate as documented in README.
Precedence is explicit environment override > saved SQLite value > default.
The UI identifies overrides. Remove an override and restart to use a saved value.
All setting environment reads are centralized in `builder/settings.py`.

Allowed Hosts and retention are captured at startup; saving either displays
“保存成功，重启 Smart Python Builder 后生效。” AI/Feishu saved configuration is
read when a new build starts; an in-flight build keeps its snapshot. Connection
tests use the current submitted fields plus stored credentials, applying the same
environment precedence, without saving. Enabled=false prevents automatic external
requests; clicking an explicit test still tests the service. Empty/masked secrets
preserve the previous value. Invalid settings are rejected before any write.

Windows API Key and Webhook values use user-scoped Windows DPAPI with UI disabled.
No reversible custom crypto is used. DPAPI records require the same Windows user
profile to decrypt; do not assume a database copied to another machine/account
can be decrypted. Passwords are hashes, not encrypted plaintext; bearer/session
secrets are not returned to the frontend. POSIX storage uses a private directory
and database mode 0600, with no claimed OS secret encryption. On Windows, ensure
`web-data` and backups inherit only the dedicated account's intended ACL; DPAPI
does not prevent database modification by another user with write access.

Back up settings and experiences while the service is stopped. Keep backups
private and excluded from Git. There is no web password-reset feature in this
patch. An operator with filesystem access can, with the service stopped and a
backup taken, remove only the `password_hash` row and all `sessions` rows from the
settings database, then bootstrap a new password. Preserve other settings rows.
Never log configuration dictionaries, request bodies, keys or webhooks. AI test
errors use safe summaries; notification failures record only exception types.
Trusted project code still executes as the worker and can access its credentials:
DPAPI does not change the trusted/internal deployment boundary.

## LAN checklist

1. Obtain the active network adapter IPv4 with `ipconfig`.
2. Add it to Allowed Hosts alongside localhost and 127.0.0.1; comma-separated
   whitespace/empty items are normalized. All-empty values fail closed with a
   configuration error; repair the environment or SQLite setting locally.
3. Start one process: `uv run uvicorn web.app:app --host 0.0.0.0 --port 8000`.
4. Visit `http://<real-IPv4>:8000`; 0.0.0.0 is a bind address, not a client URL.
5. If other PCs cannot connect, an authorized administrator should review Windows
   Firewall inbound TCP 8000 for the intended private profile and trusted subnet.
   Do not disable the firewall. Allowed Hosts validates the Host header, not client
   identity; `*` does not add authentication or protect an untrusted network.
6. Set `BUILDER_BASE_URL` to the reachable internal URL for notification links.

See [v1.0.1 acceptance](V1_0_1_ACCEPTANCE.md). Real AI and Feishu credentials were
not supplied: **NOT VERIFIED WITH REAL CREDENTIALS**. No firewall changes were made.

## Notification and external URL follow-up

Configure **Builder 访问地址** (`base_url`) under Builder settings, for example
`http://192.168.1.105:8000` or `https://builder.example.com`. Explicit
`BUILDER_BASE_URL` still overrides SQLite; remove it and restart if daily management
should use the UI. Base URL itself needs no restart: each generated notification
reads the effective value, including later notifications of an active build.
Only changes to Hosts/retention need restart; saving unchanged values with a new
Base URL does not falsely require restart.

Listening Host selects interfaces (`0.0.0.0` binds all); Allowed Hosts validates
request Host headers; Base URL generates externally clickable links. None guesses
or changes the others. Choose the real LAN adapter IPv4 explicitly, configure
Allowed Hosts and appropriate private-network firewall access separately. A Base
URL is not a connectivity guarantee or a substitute for firewall/proxy setup.
Reject unspecified addresses 0.0.0.0/::, non-HTTP(S), query/fragment and embedded
credentials. Loopback remains valid for development with a yellow UI warning.

`builder/urls.py` generates both task and approval URLs. Web assigns its public
job ID to SmartBuilder, not the per-attempt BuildEngine ID. Tasks use
`{base_url}/?job={web_job_id}`; candidate approvals use `{base_url}/admin`.
CLI has no Web Job ID, so its details link is the configured service home.

First-attempt success emits **Build Success** once, after success and any operator
artifact validation. First failure emits **Build Failed** once. An AI attempt ends
with **AI Repair Success** or **AI Repair Failed**, never an additional Build Success.
No AI configured means no AI event. Notification errors remain isolated and do not
change the build result. Disabled Feishu produces no automatic request.
These are event-emission counts within a run, not a durable exactly-once delivery
protocol: there is no outbox/retry queue or proof of recipient reading.

Feishu renders an allowlisted, human-readable metadata summary instead of arbitrary
error/diagnostic/configuration JSON. NotificationService redacts configured sensitive
values and omits secret-named fields. No actual credentials were added to tests or
Git; generated random test sentinels exercise redaction. Uploaded code and local
logs remain inside the existing trusted-worker boundary; this is not a general
secret scanner for arbitrary project content.
