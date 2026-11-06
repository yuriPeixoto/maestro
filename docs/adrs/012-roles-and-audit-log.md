# ADR-012: Roles and an Audit Log Written by the Database

**Status:** Accepted
**Date:** 2026-11-06

## Context

Until 0.1.0 every account could do everything: create and delete accounts, change alert rules and channels,
remove agents. Nothing recorded who did it. Once alerts page people and more than one team uses the dashboard,
three things are needed:

- Some accounts only look, some run the alerting, few manage accounts.
- When a rule disappears or a password is reset, the answer to "who, when, from where" must exist.
- Configuration also gets edited outside the API (a database client, a script). Those edits must not be invisible.

There is no SMTP on many on-premise installs, so a forgotten password cannot be reset by email (#99).

## Decision

1. **Three fixed roles**, `viewer`, `operator` and `admin`, each a superset of the previous one. The matrix of
   permissions lives in one place (`app/permissions.py`). Routes declare the permission they need through
   `app.auth.require`; `GET /auth/me` returns the caller's permissions so the dashboard follows the same matrix
   instead of repeating it. Reads need only a login.
2. **The role is read from the database on every request**, not carried in the token, so a demotion or a
   deactivation applies to open sessions at once. A temporary password and a deactivation also set
   `sessions_valid_after`; tokens issued before it (`iat`, with sub-second precision) are refused.
3. **Accounts are deactivated, never deleted.** The last active admin cannot be demoted or deactivated; the check
   locks the active admin rows, so two admins demoting each other at the same moment cannot both pass it.
4. **Row changes are audited by a trigger** (`maestro_audit_row`) on `users`, `alert_rules` and `alert_channels`.
   The API hands the caller (id, name, address, user agent) and a readable action name (`users.deactivate`) to
   the transaction with `set_config(..., true)` (`SET LOCAL`). Anyone can set those settings, so the trigger
   believes them only on the API's own connections (`session_user = maestro_audit_api_role()`, a function the
   migration creates with the API's database user; changing it is DDL). On any other connection it records
   the database user, `application_name` and `inet_client_addr()`. A `TRUNCATE` of an audited table is
   recorded too, with the number of rows it removed. Before and after go to JSONB. Secret columns (password
   hash, channel configuration) are replaced by `[redacted]` / `[changed]`; bookkeeping columns (lockout
   counters, last access) do not produce an entry on their own. `alert_state` is not audited: the evaluator writes it every cycle and
   its history is already `alert_events`.
5. **Events that change no row** (login, failed login, logout, a channel test) are inserted by the API.
6. **The log is append-only**: triggers refuse `UPDATE`, `DELETE` and `TRUNCATE` on `audit_log`, for the API's
   database user too, and the foreign key to `users` has no `ON DELETE` action.
7. **Temporary passwords replace the email reset**: an admin generates one (14 characters from an alphabet
   without look-alikes), it is shown once, the account must replace it on the next login, and its lockout is
   cleared. The SMTP reset flow and its token table are removed.

## Consequences

What the log catches, and what it does not:

- **Caught:** every row change on the audited tables, whatever the client (API, DBeaver, HeidiSQL, psql, a
  script), and a `TRUNCATE` of them. A change from outside the API is named `<database user> via
  <application_name>`, with the client's address.
- **It names a database login, not a person.** When several people share one login, the log says which login,
  program and address, not who. One login per person (and the API's credentials used only by the API) is what
  makes it name people. `application_name` is set by the client, so it is a hint, not proof.
- **Someone using the API's own database credentials** can say they are anyone: from the database's point of
  view, they are the API.
- **Not caught: a superuser or the tables' owner** can disable the triggers (`ALTER TABLE ... DISABLE TRIGGER`,
  `session_replication_role = replica`), change rows and then remove entries. Against that, only a log kept
  outside the database helps: `pgaudit`, or `log_statement = 'mod'` on the server.
- Only the audited tables: a new table that needs it gets its triggers in its migration.
- Every API transaction inside a request runs one extra `SELECT set_config(...)`. Configuration writes are rare,
  and reads pay it only once per request.
- Fixed roles are coarse: no per-server permissions. Groups of servers (stage 9) may need scoped roles later.
- The log grows without bound. Volume is small (configuration changes and logins); a retention job, run by the
  owner with the append-only trigger disabled, can come when it matters.
- Proxies: the client address comes from `X-Forwarded-For` only when the peer is in `MAESTRO_TRUSTED_PROXIES`.
