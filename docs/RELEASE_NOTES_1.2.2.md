# Smart Python Builder v1.2.2

## Family-use baseline

v1.2.2 is the family-use configuration release.

- Default service mode is **Family Free**.
- New FREE users receive **10000 builds** by default.
- The family quota is configurable from **Admin → System Settings → Account & Quota**.
- Administrators can use **Save and top up all FREE users** to set every existing FREE user's remaining quota to the configured value.
- Existing per-user quota editing, password reset, disable/enable, FREE/TEST switching and TEST unlimited accounts remain available.
- A **Commercial mode (reserved)** switch remains available. It restores the basic FREE 3-build default but does not implement payments, orders or recharge flows.

## Upgrade

No account database schema migration is required for this release.

After deployment, open the administrator settings page and use **Save and top up all FREE users** once if existing family accounts should immediately have 10000 remaining builds.

## Security boundary

Family free mode changes account policy only. Python projects are still executed by the trusted Windows builder, so the service should remain restricted to trusted family/internal users.
