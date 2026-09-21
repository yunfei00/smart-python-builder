# Smart Python Builder v1.3.0

## Administrator operations and feedback

v1.3.0 extends the family-use baseline with day-to-day administration, durable statistics, retention cleanup and user feedback.

### Administrator operations

- New `/admin/overview` landing page.
- Total build count and today's build count.
- Success rate based on completed SUCCESS vs FAILED/NEEDS_MANUAL_REVIEW builds.
- AI repair retry count.
- Current queue/running/canceling state, configured queue limit and active builders.
- Builder data-directory disk usage with upload/workspace/database/task-metadata breakdown.
- Total/enabled/FREE/TEST user summary and pending feedback count.

### User management

- Search by username or email.
- Filter by FREE / TEST plan.
- Filter by enabled / disabled status.
- Per-user durable build count.
- Existing quota, plan, password-reset and disable/enable actions remain available.

### Data retention

- Default Web build-data retention is 30 days.
- Administrator presets: 1 month, 2 months, 6 months and 1 year; custom days remain supported.
- Expired READY/terminal build records and their managed uploads, workspaces and artifacts are removed automatically at startup and then hourly.
- The operations page provides cleanup preview plus an explicit manual cleanup action.
- User accounts, user feedback and aggregate analytics are not removed by build-data cleanup.
- Aggregate build statistics are stored separately in `analytics.sqlite3` so totals survive artifact/history cleanup.

### User feedback

- Signed-in users can submit “用户心声” from `/feedback`.
- Feedback categories include suggestions, bugs, experience and other.
- Administrators can search/filter feedback and mark it READ or RESOLVED from `/admin/feedback`.
- Feedback is always persisted locally; optional Feishu delivery can be enabled separately.

### Test safety

Automatically configured external Feishu notifications are disabled while pytest is running, even if the local deployment has a real webhook enabled. Notification behavior is still covered with fake/mocked notifiers and explicit configuration inspection.

### Privacy/UI cleanup

Generic examples such as `user_01` are used in username fields; personal-name examples were removed from customer/admin account UI.

## Validation

The feature branch regression suite was reported fully passing after the admin operations/retention fixes. Before creating a production tag, run the complete pytest suite and Windows acceptance script against the merged `main` commit.

## Upgrade notes

No existing account migration is required. v1.3.0 creates the additional SQLite stores it needs automatically:

- `web-data/analytics.sqlite3`
- `web-data/feedback.sqlite3`

On startup, existing retained job metadata is backfilled into the analytics ledger.

Review the retention setting after upgrade. The default for new settings is 30 days.
