# Changelog

## 1.1.0 (2026-09-18)

- Added direct import and build support for public GitHub repositories.
- Added validated PEP 508 public GitHub VCS dependencies from `pyproject.toml`.
- Added visible diagnostics for failures that occur before BuildEngine starts.
- Improved GitHub import frontend cache behavior and regression-test isolation.
- Verified direct GitHub repository builds and GitHub VCS dependency builds on Windows.

## 1.0.1 (2026-09-18)

- Added password-based administrator sessions, logout/CSRF protection and Bearer API compatibility.
- Added SQLite-backed Builder, AI and Feishu settings with environment override precedence.
- Added AI/Feishu connection tests, LAN/base-URL configuration and notification URL fixes.
- Improved Web layout, build progress behavior and download readiness.

## 1.0.0 (2026-09-17)

- Initial complete release: isolated uv workspaces, PyInstaller builds, project analysis,
  experience library, Web UI, bounded AI repair, Feishu notifications and administrator approval.
- Added upload/ZIP validation, build limits, persistence/recovery and Windows acceptance coverage.
