# Changelog

All notable changes to Maestro. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). Before 1.0.0 the installation contract
(transport, stores, deployment steps) may still change between minor versions.

The version lives in `VERSION`; `api/pyproject.toml` and `frontend/package.json` repeat it, and a test keeps
them equal. Notes for the dashboard's users are in `api/app/release_notes.json`; this file is the technical
history.

## [Unreleased]

## [0.3.1] — 2026-11-11

Fixes found while installing 0.3.0. No migration: the code replaces 0.3.0's and the worker and API restart.

### Fixed
- Turning 0.2.0's per-server copies of a default rule into the global rule now moves the whole alert cycle along
  (`changed_at`, `notified_state`, `last_notified_at` and the acknowledgement), not just the state. An alert firing
  at that moment is no longer announced again, keeps its repeat rhythm and stays acknowledged. A test fails when
  a column added to `alert_state` is not moved.
- The audit screen describes each entry's target as that entry's own row had it (after the change, or before a
  delete): a rule created at 1% and edited to 99% reads 1% on its creation line. Whether the target was removed
  since still comes from now; events that copy no row (logins, channel tests, acknowledgements) are unchanged.

### Changed
- The worker signs its changes in the audit log as `maestro-worker` (`app.audit.WORKER_ACTOR`) through the same
  session settings as the API, which the trigger only takes from the API's database user. The audit screen shows
  them as "Maestro (automatic)" instead of "outside Maestro", `GET /audit?by_worker=true` lists them, and
  `outside=true` leaves them out. Another login naming itself `maestro-worker` is still logged as
  `<database user> via maestro-worker`, outside Maestro. Entries written by 0.3.0's worker keep their actor.

## [0.3.0] — 2026-11-11

Rules, channels and silences for every server, a group or one server; maintenance windows; server names; and
the alert cycle: acknowledging, repeating, "no data", grouped messages and retried deliveries. Installing it
needs Alembic `0004` and `0005` (and the `btree_gist` extension) before the new code starts.

### Added
- The alert cycle (ADR-014). An open alert (firing, or without data) can be acknowledged
  (`POST /alerts/{server_id}/rules/{rule_id}/acknowledge`, new permission `alerts.acknowledge` for operators and
  admins): it stays open and stops repeating, the channels hear who acknowledged it, and the audit log records
  it. `GET /alerts/open` lists what is open on every server.
- A firing alert nobody acknowledged repeats every `cooldown_minutes` (the dashboard calls it "repeat after").
- "No data": a rule whose metric stops arriving goes to `NO_DATA` and says so once, instead of keeping its last
  state; when the data returns it is judged again. A metric the server never sent in the last 24 hours is left
  alone, and "no data" of a server without heartbeat is recorded but not sent ("no signal" already says it).
- A change held back by a silence or maintenance is announced when the quiet ends, saying how long ago it
  happened; an alert still firing then repeats at once. `alert_state.notified_state` keeps what the channels last
  heard, written with a compare-and-set before anything is sent.
- One message per server and channel per evaluation cycle: a burst is one message with a line per alert
  (`alert_outbox`). `notification_log` keeps one row per alert; webhooks get every line in `alerts`.
- Failed deliveries are retried after 1, 2, 4, 8, 16 and 32 minutes (`notification_retries`, Postgres), marked as
  late, and dropped when every alert they speak of has changed since. `GET /alerts/{server_id}/retries`.
- `GET /alerts/rules` without a scope lists every rule; `POST /alerts/channels/{id}/move` takes a channel to
  another place keeping its secrets (audited as `alert_channels.move`).
- The Alerts screen: open alerts with acknowledge; rules by place with where each comes from, overriding or
  switching off a rule on one server, back to default; the channels that reach a server; silences and
  maintenance; labels, groups and nicknames. Every screen names a server through `useServerName`. The audit
  screen describes servers, groups, silences, maintenance windows and acknowledgements.
- Alembic `0005`: `alert_state` gains `NO_DATA`, `changed_at`, `notified_state`, `last_notified_at` and the
  acknowledgement; table `notification_retries`.
- Server groups and names (ADR-013): a `servers` table (filled from the heartbeats), groups, a shared label
  set by admins (notifications show it beside the hostname) and a personal nickname per account
  (`PUT/DELETE /servers/{id}/nickname`, any role). `GET /servers` returns label, group and the caller's
  nickname. New permission `servers.manage` (admins).
- Rules and channels for every server (`global`), a group or one server (`/alerts/rules`, `/alerts/channels`,
  `/alerts/{server_id}/resolved-rules`). Per metric and severity the most specific rule wins; a rule with
  `enabled=false` switches the inherited one off there. Rules can be edited (`PATCH /alerts/rules/{id}`).
- Silences with a deadline, reason and author (`/alerts/silences`), and maintenance windows on a server, once or
  weekly in a time zone (`/alerts/maintenance`). Rules are judged and events recorded while quiet; nothing is sent.
  Occurrences are `tstzrange` rows under an exclusion constraint, so the database refuses overlapping windows.
- Alembic `0004` (needs the `btree_gist` extension). Audit triggers on `servers`, `server_groups`,
  `alert_silences` and `maintenance_windows`.

### Changed
- The default rules are global and editable. The worker stores them once and turns 0.2.0's per-server copies
  into them, keeping each copy's state and rule-bound channels; a default a server had deleted stays off there.
  `alert_defaults_applied` is no longer written.
- Alert state is kept per rule and server. Only one active rule per place, metric and severity (was per
  server, metric, operator, threshold and severity): a server with two such rules fails the migration.
- `DELETE /alerts/{server_id}/rules/{id}` answers 409 for a rule set for a group or every server.
- `python -m app.import_sqlite` names its connection `maestro-import`.
- ML rules (`alert_mode` `ml` or `both`) fire on an anomaly episode open for at least 5 minutes that includes the
  metric, not on the score of the last minute; `ml_score_threshold` applies to the metric's deviation in it.
- A grouped e-mail takes its subject from the first line only.

### Fixed
- A rule overridden or switched off on a server kept its last state there, so a FIRING one kept the server's
  health alarmed; only rules still judged on the server count now.
- The correlation analyzer and the forecast scheduler swallowed their cancellation, so every worker shutdown
  logged `returned on its own` as an error.

## [0.2.0] — 2026-11-06

Accounts, rules, channels and alert state move to Postgres; roles, an audit log and the screen to manage
them. Installing it needs Postgres and the Alembic schema before the new code starts (`docs/deployment.md`).

### Changed
- Accounts moved from SQLite to Postgres (ADR-011): SQLAlchemy 2 with asyncpg, schema in Alembic
  (`api/alembic`). `MAESTRO_DATABASE_URL` is required, and the API refuses to start when the schema is behind
  the code. `MAESTRO_AUTH_DB_PATH` is gone.
- Login lockout is stored with the account (5 wrong passwords in 15 minutes lock it for 15 minutes), so it
  survives a restart. Names that match no account keep the in-memory limit.
- Alert rules and channels moved from ClickHouse, and alert state and the default-rules marker from Redis, to
  Postgres (Alembic `0002`). The API contract is unchanged; creating a rule the server already has now answers
  409. Redis keeps streams, heartbeats and worker health (plus caches until it leaves).
- A change of alert state is a compare-and-set in Postgres, applied before the notification goes out. The alert
  is delivered even when the ClickHouse history insert fails (logged); before, a ClickHouse outage held every
  alert back.
- The worker checks the Postgres schema at startup, like the API. Postgres connections carry an
  `application_name` and statement, lock and idle-in-transaction timeouts.
- Roles `viewer`, `operator` and `admin` (Alembic `0003`, `app/permissions.py`). Write routes need a role that
  grants them and answer 403 otherwise; `/users` and `/audit` are for admins. Accounts from before this release
  become admins; new ones start as viewers. `GET /auth/me` returns `role` and `permissions`.
- `DELETE /users/{id}` is gone: accounts are deactivated (`POST /users/{id}/deactivate`, `/reactivate`) and
  keep their history. A deactivated account's sessions are refused at once, and so are a reset account's.
- `POST /users` takes an optional `full_name` and `role`; without `password`, it generates one and returns it once.

### Added
- `python -m app.import_sqlite <file>` copies the 0.1.0 accounts into Postgres; safe to run again.
- Postgres 16 in Docker Compose (with a `migrate` service) and in CI.
- `python -m app.import_alerting` copies the 0.1.0 rules, channels (with the legacy per-server webhook), alert
  state and default-rules marker into Postgres; safe to run again, and it checks every source row at the end.
- The alert evaluator holds a Postgres advisory lock; a second evaluator stands by.
- `POST /users/{id}/temporary-password` (#99): an admin generates a random temporary password for someone who
  forgot theirs; it ends the account's sessions, clears its lockout and must be changed on the next login.
- Users and audit screen (admins): accounts with role, status and last access; create (with a generated password
  shown once), edit, deactivate, reactivate and temporary password; the audit log filtered by person, action and
  period, with each change field by field; the roles matrix. The dashboard reads `permissions` from
  `/auth/me` and hides what the caller's role does not allow (rules, channels, channel tests, correlation runs).
- `GET /users/roles` returns the permission matrix of `app.permissions`. `GET /audit` takes `outside=true` (changes
  no account made: in the database or by a process with no caller) and returns `target_info` (an account's name, a
  rule's metric and threshold, a channel's type and server, soft-deleted ones too).
- `PATCH /users/{id}` edits name, email and role. The last active admin cannot be demoted or deactivated.
- `audit_log`, written by a trigger on accounts, rules and channels (also for changes made outside the API) and
  by the API for logins, logouts and channel tests; append-only. The caller the API names is believed only on the
  API's own database connections; others are recorded by database user, client program and address, and a
  `TRUNCATE` of an audited table is recorded too. `GET /audit` filters by person, action, target
  and period, newest first, with `before_id` pages. Last login and last access per account.

- The sidebar groups admin screens under Administration and keeps About last, set apart.

### Removed
- `aiosqlite`.
- The email reset (`/auth/forgot-password`, `/auth/reset-password`, `password_reset_tokens`,
  `MAESTRO_FRONTEND_URL`, `MAESTRO_PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`). SMTP stays for email alerts.
- The startup migrations of the evaluator (old metric names, legacy webhook): `app.import_alerting` does both.

## [0.1.0] — 2026-11-04

First numbered release. It covers everything built so far: phases 1–4 of the roadmap and the hardening
done in 2026-10/11.

### Added
- Go agent: CPU, memory, disk, network and process metrics, log tailing, inventory, Debian package list,
  opt-in database pool monitoring, heartbeats, local ring buffer.
- Ingestion through Redis Streams into ClickHouse, acking a message only after it is written.
- Hourly rollup of every metric (`metrics_hourly`, migrations 012–013), kept for two years; charts longer
  than a day and capacity read it. Column codecs on the time-series tables (migration 014).
- Separate worker process (`python -m app.worker`) for consumers, the alert evaluator and scheduled jobs;
  the API only serves HTTP. `/health` reports both and the external watchdog alerts on either.
- Alerting: default rules per server, threshold and ML rules, Telegram, webhook, Slack and e-mail channels,
  delivery history, offline detection.
- Anomaly detection against a seasonal baseline, reported as episodes with what deviated and the normal
  range (`anomaly_episodes`, migration 015). See ADR-010.
- Capacity: disk trend since the last level shift; CPU and memory as the daily 5-minute peak against the
  limits (`GET /forecasts/{server}/peaks`).
- Evaluation bench for anomaly detection and forecasts: `python -m app.ml.evaluation`.
- Security signals (SSH, UFW), vulnerability scan of runtimes and Debian packages against OSV.dev.
- Accounts with forced password change, login throttling, and a required JWT secret of 32+ characters.
- About screen and "what's new" modal; `GET /about`; `POST /auth/me/release-seen`.

### Changed
- Python dependencies are locked with uv (`api/uv.lock`); tokens are signed with PyJWT.
- ML work runs in a low-priority child process of the worker.

### Removed
- River, the per-metric Isolation Forest, the feature pipeline (`metric_features` is no longer written),
  the model store (`MAESTRO_ML_MODELS_DIR`) and Prophet.

### Fixed
- A server in attention now says why.
- The network charts used metric names the agent never sent.
