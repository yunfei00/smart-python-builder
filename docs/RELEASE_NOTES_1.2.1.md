# Smart Python Builder v1.2.1

## Highlights

Smart Python Builder v1.2.1 completes the first customer-account and project-management baseline on top of v1.2.0.

- Username-first customer accounts with optional email.
- Automatic migration of legacy email-only accounts while preserving existing IDs, password hashes, plan/quota state, disabled state and session ownership.
- Login by username or bound email; legacy email login remains supported.
- FREE build quotas and internal unlimited TEST accounts.
- Administrator user management: create users, set/reset quotas, switch FREE/TEST, disable/enable accounts and reset passwords.
- Customer password changes with old-session invalidation.
- Guest project analysis followed by login/registration and seamless continuation of the same READY project.
- Project cancellation and deletion, including Windows process-tree termination for active builds and cleanup of associated files.
- Improved READY project metadata, account/admin UI and settings layout.
- Improved package entry handling and optional dependency detection for imported projects.

## Validation

Before release preparation, the complete Windows pytest regression suite reported:

- 246 passed
- 2 dependency deprecation warnings
- 0 failed

The repository release checklist also requires the Windows acceptance script and final Web UI smoke checks before tagging.

## Upgrade notes

Existing `web-data/accounts.sqlite3` databases are migrated automatically on first startup. Back up the database before upgrading a real deployment.

Legacy users keep their original email login. A unique username is generated from the email prefix when possible, with a deterministic fallback/suffix strategy when required.

No manual database deletion or recreation is required.

## Security boundary

v1.2.1 adds authentication and account isolation, but uploaded Python code, dependencies and PyInstaller hooks are still executed by the Windows build worker. This release remains intended for trusted/internal build workloads until stronger worker isolation is added.
