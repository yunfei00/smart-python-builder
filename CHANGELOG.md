# Changelog

## 1.2.1 (2026-09-21)

- Added username-first customer accounts with optional email, legacy email-login compatibility and automatic migration of existing email-only accounts.
- Added administrator user management: create users, FREE/TEST plan switching, custom/reset quotas, disable/enable accounts and password resets.
- Added customer password changes, session invalidation after password reset/change, and improved workspace account display.
- Added guest project analysis followed by login/registration and seamless READY-project continuation without re-uploading.
- Added project cancellation/deletion flows, including Windows process-tree termination for active builds and cleanup of associated project/workspace files.
- Improved READY project context, administrator settings/user-management UI, and preserved uploaded project metadata.
- Improved package entry handling and optional dependency detection for imported source projects.
- Full regression suite verified at 246 passed before release preparation.

## 1.2.0 (2026-09-19)

- Added the commercial landing page and customer workspace.
- Added customer registration/login/logout, FREE build quota enforcement and internal unlimited TEST accounts.
- Added ownership isolation for customer jobs and quota-aware import/build flows.
- Improved GitHub import progress/diagnostics and upload/build state presentation.

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
