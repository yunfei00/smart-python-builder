# Release checklist

Use this checklist for every Smart Python Builder release.

## Source state
- Work on a release/maintenance branch; keep `main` stable.
- Confirm `builder/version.py` and `pyproject.toml` contain the intended version.
- Confirm README and CHANGELOG describe current behavior.
- Confirm the working tree is clean before tagging.

## Automated regression
```powershell
uv sync --locked
uv run pytest
```
All tests must pass. Review any new warnings.

## Windows acceptance
```powershell
uv run python tests/windows_v1_acceptance.py
```
Also verify through the Web UI: single-file build, ZIP/multi-file build, public GitHub repository import,
a `pyproject.toml` project with a public GitHub VCS dependency, explicit entry selection, useful
failure logs, administrator settings, and external-service tests when real credentials are deployed.

## Security and operations
- Commit no API keys, webhooks, passwords, generated workspaces or build artifacts.
- Keep GitHub import limited to supported public HTTPS repositories.
- Run deployment under a dedicated low-privilege Windows account.
- Restrict LAN firewall/Allowed Hosts/Base URL configuration.
- Keep the service trusted/internal; do not expose anonymous untrusted uploads.

## Release
After acceptance, merge to `main`, pull the exact main commit, then create an annotated tag:
```powershell
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "Smart Python Builder vX.Y.Z"
git push origin vX.Y.Z
```
The tag is the immutable rollback baseline. Cleanup and new development continue on a new branch.
