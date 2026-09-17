# Smart Python Builder v1.0.0 Release Checklist

Release audit date: 2026-09-17. Audit baseline: `ae5c194` on `main`.

## Release gates

- [x] Initial checkout was main, clean and synchronized with origin/main.
- [x] Local/remote branch inventory contains only main; no unmerged Phase branches.
- [x] Phase 2–8 implementation commits are ancestors of main; main was preserved.
- [x] Phase 1 CLOSED; Phase 2 CLOSED; Phase 3 CLOSED; Phase 4 CLOSED.
- [x] Phase 5 CLOSED; Phase 6 CLOSED; Phase 7 CLOSED; Phase 8 CLOSED.
- [x] Smart Python Builder V1 = COMPLETE. No V1.1 features added.
- [x] Full main automated suite: **80 passed**, no failures; two third-party deprecation warnings.
- [x] Fresh Windows build matrix: **24/24 PASS**, including both Web output modes.
- [x] Final fresh EXE smoke: exit 0, expected versioned output.
- [x] Product version is 1.0.0 in pyproject.toml, builder/version.py, lock metadata and installed distribution.
- [x] Wheel/sdist build succeeded; isolated wheel installation, imports, version and packaged templates passed.
- [x] README covers first-time setup, Windows/Python/uv, Web upload/build/download, AI, Feishu, learning, approval and security.
- [x] Common credential-pattern checks of tracked files and Git patch history found no matches. No real credentials were added.

Audit environment: Windows 11 build 26200; uv 0.11.2; project environment Python 3.13.12.
System `python --version` separately reports 3.13.5; tests/build orchestration use `uv run`.

## Audit defect and resolution

The new rejection-cleanup regression initially failed: rejected ZIPs left partially extracted files
without a task record. The upload error path now removes only that request's validated UUID directory.
Invalid Python and unsafe/oversize ZIP/upload cases were rerun successfully. This is a release fix,
not a new feature. No tag was created while the check was failing.

## Final Windows matrix

Artifacts below are local audit outputs, not committed binaries or public downloads. Several library
cases share one executable with separate functional assertions; this is 24 checks, not 24 independent
executables. Deliberate failure rows PASS when the expected failure is correctly detected.

| Case | Result | Build ID | Artifact | Runtime Verification | Notes |
|---|---|---|---|---|---|
| stdlib CLI | PASS | `bacafde0021f4ad3805395510906ed39` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/bacafde0021f4ad3805395510906ed39/project/dist/main.exe` | EXE exit 0, JSON output verified | Fresh release-audit build |
| requests | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check requests = true | Shared functional EXE |
| pandas | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check pandas = true | Shared functional EXE |
| openpyxl | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check openpyxl = true | Shared functional EXE |
| numpy | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check numpy = true | Shared functional EXE |
| OpenCV | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check OpenCV = true | Shared functional EXE |
| Pillow | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check Pillow = true | Shared functional EXE |
| pyserial | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check pyserial = true | Shared functional EXE |
| PyYAML | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check PyYAML = true | Shared functional EXE |
| multi-file project | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check multi-file project = true | Shared functional EXE |
| JSON config | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check JSON config = true | Shared functional EXE |
| image assets | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | EXE exit 0; functional check image assets = true | Shared functional EXE |
| requirements project | PASS | `2a6464436c434260931faeaebff68345` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/2a6464436c434260931faeaebff68345/project/dist/main.exe` | Declared dependencies used; combined EXE functional checks passed | Shared functional EXE |
| Tkinter | PASS | `257ea3606f1f4fdf9e3a703002a21084` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/257ea3606f1f4fdf9e3a703002a21084/project/dist/main.exe` | GUI process remained alive for 10 seconds; test process tree stopped | Fresh release-audit build |
| PySide6 | PASS | `8f508a8717d64da2a15b8dfa082e276c` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/8f508a8717d64da2a15b8dfa082e276c/project/dist/main.exe` | GUI process remained alive for 10 seconds; test process tree stopped | Fresh release-audit build |
| PyQt6 | PASS | `9d793ffe845b436189c0cebdab0f3868` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/9d793ffe845b436189c0cebdab0f3868/project/dist/main.exe` | GUI process remained alive for 10 seconds; test process tree stopped | Fresh release-audit build |
| pyproject project | PASS | `69cfcdbb66fd4cf084773bce9bf07b04` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/69cfcdbb66fd4cf084773bce9bf07b04/project/dist/main.exe` | pyproject overrides requirements; EXE exit 0 | Fresh release-audit build |
| normal build failure | PASS | `70756219fda142fa8f358ee3abff9318` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/70756219fda142fa8f358ee3abff9318/project/dist/main.exe` | Intentional EXE runtime failure correctly reported and notified | Fresh release-audit build |
| AI repair failure | PASS | `d34606058c3e4fedba1f4423905cce84` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/d34606058c3e4fedba1f4423905cce84/project/dist/main.exe` | 3 real failing EXEs; 2 AI calls; manual review; notification delivered | Fresh release-audit build |
| AI repair success | PASS | `b6ddecbcbcde4bff82937119ef79d137` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/b6ddecbcbcde4bff82937119ef79d137/project/dist/main.exe` | Real EXE missing module repaired; rebuilt EXE exit 0 | Fresh release-audit build |
| approved experience hit | PASS | `fb0a787dec4c4ea38b2a717441580591` | `D:/code_2026/smart-python-builder/workspace/v1-484da1bc167e4659870766a3638a8e8c/builds/fb0a787dec4c4ea38b2a717441580591/project/dist/main.exe` | Second independent project first attempt succeeds; no additional AI call | Fresh release-audit build |
| Web build flow: EXE | PASS | `c2f75bc9c50942f9946926a6b9cf7b75` | `D:/code_2026/smart-python-builder/.pytest-tmp-web-download.exe` | Live HTTP upload, build, log, download; EXE exit 0: web-build-ok  | Live HTTP; local audit server; downloaded executable run |
| Web build flow: ZIP | PASS | `0f27713697d6414bbf9f81033f6a5d53` | `D:/code_2026/smart-python-builder/.pytest-tmp-web-zip-3ee91ee71b884d91b49ffa64aae08f55/main/main.exe` | Live HTTP ZIP upload, explicit multi-entry selection, automatic JSON resource inclusion, onedir ZIP download, EXE exit 0 | Live HTTP; local audit server; downloaded executable run |
| normal packaging failure | PASS | `87e866c3a2894282a7879a3187d0db18` | None (expected failure) | Not applicable: packaging rejected invalid Python, no EXE generated | Actual PyInstaller exit 1 and SyntaxError captured; build failed as expected |

Machine-readable evidence: [release-build-matrix.json](release-build-matrix.json).

## Final smoke

Build ID: `67f820a2fb5340e8aef25ac12ea902fb`  
Artifact: `D:/code_2026/smart-python-builder/workspace/67f820a2fb5340e8aef25ac12ea902fb/project/dist/release-smoke.exe`  
Exit code: `0`  
Output: `Smart Python Builder v1.0.0 smoke OK`

## Production integrations

- AI: production factory selects OpenAICompatibleProvider only with configured API Key + Model;
  otherwise disabled. Base URL is configurable and defaults to https://api.openai.com/v1.
  FakeAIProvider is only explicitly injected by tests. Selection tests cover configured/unconfigured cases.
- Feishu: configured Webhook selects FeishuNotifier; otherwise sending is disabled.
  FakeNotifier is only explicitly injected by tests. Notification failure isolation passed.
- Current audit environment: AI Key / Base URL / Model, Feishu Webhook and admin token are unset.
  No real external AI or Feishu request was made. Boolean configuration presence was checked without
  printing secret values. Literal values in tests are deliberately non-secret placeholders.

## Security audit

| Control | Result | Evidence / limit |
|---|---|---|
| ZIP traversal / Windows aliases / symlinks | PASS | Absolute, parent, drive/ADS, backslash, reserved-name and link rejection tests |
| Upload type / actual size | PASS | .py/.zip only; actual file >20 MiB rejected; HTTP request body bounded |
| ZIP expansion | PASS | 100 MiB expanded total / 2,000 entries; expansion-limit regression |
| Rejected upload cleanup | PASS | Partial extraction and invalid Python leave no upload directory |
| Build timeout | PASS | 900-second command budget per attempt; actual timeout kills parent and child |
| AI retry bound | PASS | At most 2 AI calls / 3 builds; real unrepaired EXE failure reaches manual review |
| Workspace cleanup / artifact retention | PASS | Managed terminal UUID workspaces only; 7-day default; active/unrecognized paths preserved |
| Recovery | PASS | Persisted interrupted jobs move to NEEDS_MANUAL_REVIEW after restart |
| Notification isolation | PASS | Simulated delivery outage does not alter successful repair outcome |
| Concurrency | PASS | One Web worker executor; eight active/queued tasks; ninth rejected with HTTP 429 |
| Disk space | PASS | Pre-build 1 GiB free-space check; simulated shortage logged as failure |
| Admin / request boundary | PASS | Bearer token required for approval; host and cross-origin write checks |

## Known limitations

- Trusted/internal Windows use only. Uploaded projects and package hooks execute code as the worker;
  virtual environments are not a sandbox. No VM isolation or hard CPU/memory quotas.
- Separate low-privilege Windows account deployment, Windows 10/Server and other Python versions were
  not individually validated. One service process is required; no distributed queue/user login system.
- Real AI diagnosis and actual Feishu delivery remain unconfigured/unverified; tests use explicit fakes
  and mocked transport contracts. Feishu signing-secret configuration is not implemented.
- Web/CLI SUCCESS means packaging produced a nonempty artifact. Arbitrary uploaded EXEs are not run
  automatically; runtime validation here uses fixed trusted fixtures / operator validators.
- Dynamic imports and unconventional dependency declarations are not fully inferred; approved learning
  deliberately matches source/dependency fingerprints. Some dependencies share one matrix executable.
- Web retention runs at startup/hourly; CLI cleanup must be scheduled by the operator. Candidate approval
  needs its retained source. Package versions not pinned by input manifests can change on future builds.
- Two FastAPI/Starlette test-client deprecation warnings remain; they did not fail tests.
- Credential scans are heuristic checks, not a claim to detect every possible credential format.

## Reproduction and publication

```powershell
uv sync --locked
uv run pytest tests -q --basetemp .pytest-tmp-release-check
uv run python tests/windows_v1_acceptance.py
uv run python tests/windows_release_failure_acceptance.py
# With a local server already running:
uv run python tests/windows_web_acceptance.py http://127.0.0.1:8000
uv run python tests/windows_web_zip_acceptance.py http://127.0.0.1:8000
```

Only after all gates pass, publish this audited tree using:

```powershell
git commit -m "chore: prepare Smart Python Builder v1.0.0 release"
git push origin main
git tag -a v1.0.0 -m "Smart Python Builder v1.0.0"
git push origin v1.0.0
```

The release commit is the commit referenced by annotated tag `v1.0.0` (resolve with
`git rev-parse v1.0.0^{}`). The tag/commit push is verified after publication;
no commit hash is embedded here to avoid a self-referential commit hash.
