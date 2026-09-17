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
