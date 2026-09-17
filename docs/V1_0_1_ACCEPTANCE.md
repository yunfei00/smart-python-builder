# Smart Python Builder v1.0.1 Acceptance

Date: 2026-09-17. Development branch: `codex/v1.0.1-admin-settings-ui`.
Baseline: main `c97ab9e` (synced before branching), clean, **80 passed**.
SSH 22/443 failed; direct HTTPS succeeded after bypassing a dead local Git proxy
for that command only. Repository remote configuration was preserved.

## Automated verification

- **131 passed, 0 failed**: original 80 retained + 51 new parameterized cases.
- Two existing third-party TestClient deprecation warnings; no new failures/skips.
- Home/header/initial disabled button; READY/QUEUED/BUILDING/AI/rebuild/failure/
  review/expiry/success download gates; terminal=false, missing/empty/outside artifact
  rejection; repeated successful download requests.
- Host normalization, whitespace, wildcard, invalid/empty values; TrustedHost and
  same-origin scheme/host checks; restart required before changed Hosts take effect.
- Password bootstrap/hash, correct/incorrect login, HttpOnly/SameSite cookies,
  session expiry/logout replay rejection, login throttling, unauthenticated redirects.
- Settings save/reload, atomic rejection, masked GET/HTML, unchanged secret
  preservation, Windows DPAPI ciphertext, explicit environment overrides.
- Saved settings instantiate the actual Builder's real AI/Feishu clients; disabled
  flags disable them. Minimal AI request uses the configured model/URL and 15s timeout.
- Injected FakeAIProvider/FakeNotifier test success/failure, safe provider errors,
  existing notifier failure isolation, session approve/edit/reject and Bearer API.
- `uv build --offline`: wheel and sdist PASS. Installed version 1.0.1; wheel includes
  static CSS/JS, admin/settings/login templates and new settings/auth modules.
- `git diff --check`: PASS. No production credentials, databases, EXEs or temporary
  acceptance credentials are tracked.

Reproduce automated checks:

```powershell
uv sync --locked
uv run pytest tests -q --basetemp .pytest-tmp-v101-check
uv build --offline
```

## Windows and browser acceptance

Windows 11, Python 3.13.12 via uv. Tests used an isolated ignored working directory
`.pytest-tmp-v101-live`, so deployment settings/credentials were not overwritten.
The standard `web.app:app` ran bound to `0.0.0.0:8000`, one worker, with an explicitly
initialized disposable test password. No real AI Key/Model/Webhook was configured.

| Case | Result | Evidence |
|---|---|---|
| Local homepage | PASS | Browser at 127.0.0.1:8000; compact header, initial disabled download |
| LAN address | PASS (same host) | GET http://192.168.3.10:8000 returned HTTP 200; no Invalid Host Header |
| Tkinter upload | PASS | Browser file chooser uploaded demo.py; detected GUI/no third-party deps |
| Build submission | PASS | Button disabled; progress scrolled into view after accepted start |
| Live logs / user scrolling | PASS | Log grew from 739 to 7903 chars; after scrolling to top, scrollY stayed 0 through completion |
| Success / download | PASS | “✓ Windows 应用生成成功”; enabled download triggered browser download event |
| EXE runtime | PASS | Same download endpoint fetched EXE; process alive 10s; process tree terminated after test |
| Administrator | PASS | /admin/login → /admin → /admin/settings via browser navigation |
| Builder setting save | PASS | Retention changed 7 → 8, restart message shown, value survived reload |
| Unsaved other card | PASS | Saving Builder settings retained unsaved AI model draft without saving it |
| AI test button | PASS with injected Fake | Isolated loopback 8001 test app returned “AI 连接成功” |
| Feishu test button | PASS with injected Fake | Isolated loopback 8001 test app returned “飞书通知测试成功” |
| Logout | PASS | Browser returned to login; automated test proves revoked session cannot replay |

Real job: `6c2134204cd3438b87d37fad0c52d24c`.
Build ID: `344b8a7a01014a4b94af04d663a48ea7`.
Artifact: `.pytest-tmp-v101-live/web-data/workspace/344b8a7a01014a4b94af04d663a48ea7/project/dist/demo.exe`.
Runtime copy: `.pytest-tmp-v101-live/downloaded-demo.exe`.
Browser download event and separate HTTP download/runtime checks used the same job.

The isolated 8001 harness explicitly passed `ai_factory` and `notifier_factory` to
`create_app`; no Fake option was added to production settings or environment.
Both temporary servers were stopped after acceptance. No firewall rules changed.

## Responsive measurements

Measured rendered bounding rectangles of the enabled download and log sections:

| Viewport width | Download → log gap | Horizontal overflow | Header height |
|---|---|---|---|
| 390 | 24 px | None | 57.9 px |
| 1024 | 24 px | None | 60.4 px |
| 1280 | 24 px | None | 60.4 px |
| 1920 | 24 px | None | 60.4 px |

A rendered 1280 screenshot confirmed normal-flow download/log spacing and subtle
green/blue background. Temporary viewport override was reset after checking.

## Configuration / security decisions

- Setup and field guidance: [README](../README.md). Operational detail and password
  recovery: [OPERATIONS](OPERATIONS.md).
- Stdlib scrypt avoids a new dependency. No default password. Password environment
  is bootstrap-only; persistent hash takes precedence after initialization.
- Explicit environment > SQLite > defaults. AI/Feishu changes affect new builds;
  Hosts/retention changes require restart and the UI explicitly says so.
- Windows DPAPI encrypts API Key/Webhook for the service user; GET/HTML never
  return those secrets. Masked/blank replacement values keep the old secret.
- HttpOnly/Lax cookies, unpredictable session tokens stored as hashes, expiry,
  revocation, CSRF and same-origin checks. HTTPS Secure cookie is configurable.
- ExperienceStore candidate/approval/rejection semantics are unchanged.
- Uploaded projects remain trusted code running as the service user. DPAPI is
  not a sandbox. Restrict directory ACLs, backups, network and service identity.

## Not verified / known limitations

- AI: **NOT VERIFIED WITH REAL CREDENTIALS**.
- Feishu: **NOT VERIFIED WITH REAL CREDENTIALS**.
- LAN HTTP was tested from this same Windows host to its WLAN IPv4; another physical
  LAN computer and organizational firewall policy were not independently verified.
- Dedicated low-privilege Windows account and HTTPS reverse-proxy deployment were
  not provisioned during acceptance. HTTP credentials require a trusted network.
- No password-change UI, multi-user roles, public SaaS isolation, or new build engine.
- This patch re-ran the requested Tkinter GUI/Web acceptance; the historical V1
  24-case library matrix remains documented in RELEASE_CHECKLIST_V1.md and is not
  represented as a new v1.0.1 full matrix run.

Development delivery only: **尚未 merge/tag**. No v1.0.1 Git tag or release created.


## Notification & URL follow-up (2026-09-17)

Baseline for this follow-up: `b90c440`, same development branch, clean on entry.
Original 131 pytest cases remain unchanged; **41 new cases**, **172 passed, 0 failed**.
No main merge, branch deletion, v1.0.1 tag or release.

Root causes: SmartBuilder's first-success branch transitioned and returned without
emitting a notification; `base_url` already existed but was excluded from editable
settings, so deployments kept the loopback default unless an environment override
was supplied. Web task IDs were already available and are now passed explicitly
to a shared URL builder, rather than appended to mutable URL strings.

Normal success emits Build Success once. Repair success emits exactly Build Failed
then AI Repair Success. Exhausted/declined/invalid AI emits Build Failed then
AI Repair Failed. Notification failure leaves a successful build successful.
Base URL is saved in SQLite, normalized and validated, and reread for each new
notification link. Environment override precedence is unchanged.

New tests include URL persistence/reload, HTTP/HTTPS, slash/whitespace normalization,
invalid scheme/query/fragment/credential/listening-address rejection, loopback
warnings, live link refresh, correct Web Job ID versus Build ID, all notification
sequences, secret redaction, disabled Feishu, HTTP/Web integration and unchanged
Hosts/retention not triggering a restart warning for a Base URL-only change.

Browser checks (isolated data, disposable password): default loopback produced the
visible yellow warning; 0.0.0.0 was rejected by the server; LAN URL with extra slashes
was normalized and survived reload; HTTPS domain accepted. Saving only the address
showed immediate-effect text, not a restart requirement. No actual secrets were
entered into the test page. Production settings were not overwritten.

### Fresh Windows execution evidence

The server used existing create_app/SmartBuilder/BuildEngine, bound to 0.0.0.0:8000.
The explicit operator-selected LAN URL was http://192.168.3.10:8000; the application
did not detect/guess an IP. HTTP uploads generated actual EXEs, which were downloaded
and executed with expected stdout and exit code 0. An explicitly injected FakeAIProvider
repaired a real dynamic-import colorsys failure; FakeNotifier captured event counts.
The third case raised notifier exceptions deliberately. This is real packaging/runtime
verification with offline external-service substitutes, not real Feishu delivery.

| Case | Result | Web Job ID | Build ID | Captured notifications |
|---|---|---|---|---|
| normal | PASS | `e8c79b4b110148ee90b6aad4c3950075` | `cac75bc258954cb282185bf64c120865` | Build Success |
| repair | PASS | `aae8f010eb404248a64f1f437b04bc91` | `259aec884e254ee5aa9f481e4fca9aed` | Build Failed, AI Repair Success |
| notifier-outage | PASS | `8babf5005141422f8364ded54bfec931` | `11438c7f9e5e49f88b9ceee5c46014bd` | send failed; SUCCESS retained |

All task links used LAN Base URL plus the correct Web Job ID. Both page and job API
were fetched successfully via that LAN address **from the same host**. AI candidate
approval URL was checked against the LAN `/admin` address. Artifacts and full details
are recorded in [notification-url-windows.json](notification-url-windows.json).

Reproduce: `uv run python tests/windows_notification_url_acceptance.py http://<LAN-IP>:8000`.
Use a free port 8000 and explicitly provide the intended LAN IP; this offline harness
writes only its UUID `.pytest-tmp-notification-*` data. It starts and stops its own
single-process Web test server and does not modify the firewall.

### Outstanding real environment verification

The current repository SettingsStore had no real AI Key/Model or Feishu Webhook.
The user's separate successful deployment credentials were not located or copied;
no credential value was requested in chat. Therefore:

- Ordinary-success **real Feishu receipt: NOT VERIFIED WITH REAL CREDENTIALS**.
- Real AI repair plus Feishu receipt: **NOT VERIFIED WITH REAL CREDENTIALS**.
- Phone/another physical LAN PC link click: **NOT VERIFIED**. Same-host LAN HTTP
  success is not evidence of another device's network/firewall reachability.
- Actual recipient delivery, HTTPS domain deployment and durable exactly-once
  delivery across crashes are not claimed. The implementation makes one emit per
  specified state transition and keeps notification exceptions isolated.

README and OPERATIONS explain Listening Host (interfaces), Allowed Hosts (request
Host headers), and Base URL (outgoing links). Only local development defaults and
examples retain loopback literals; generated notification links read SettingsStore.
Feishu output uses a metadata allowlist and configured-secret redaction; raw diagnosis
JSON is omitted. No actual secret was added to source, tests or acceptance records.
