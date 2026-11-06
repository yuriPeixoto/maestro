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
   the transaction with `set_config(..., true)` (`SET LOCAL`); without them, the trigger records the database
   user and `application_name`. Before and after go to JSONB. Secret columns (password hash, channel
   configuration) are replaced by `[redacted]` / `[changed]`; bookkeeping columns (lockout counters, last access)
   do not produce an entry on their own. `alert_state` is not audited: the evaluator writes it every cycle and
   its history is already `alert_events`.
5. **Events that change no row** (login, failed login, logout, a channel test) are inserted by the API.
6. **The log is append-only**: a trigger refuses `UPDATE` and `DELETE` on `audit_log`, for the API's database
   user too, and the foreign key to `users` has no `ON DELETE` action.
7. **Temporary passwords replace the email reset**: an admin generates one (14 characters from an alphabet
   without look-alikes), it is shown once, the account must replace it on the next login, and its lockout is
   cleared. The SMTP reset flow and its token table are removed.

## Consequences

- An edit made in a database client shows up in the audit log, with the client's `application_name`. One made by
  the table owner can still disable the triggers; that needs DDL rights, which the application account lacks.
- Every API transaction inside a request runs one extra `SELECT set_config(...)`. Configuration writes are rare,
  and reads pay it only once per request.
- Fixed roles are coarse: no per-server permissions. Groups of servers (stage 9) may need scoped roles later.
- The log grows without bound. Volume is small (configuration changes and logins); a retention job, run by the
  owner with the append-only trigger disabled, can come when it matters.
- Proxies: the client address comes from `X-Forwarded-For` only when the peer is in `MAESTRO_TRUSTED_PROXIES`.
