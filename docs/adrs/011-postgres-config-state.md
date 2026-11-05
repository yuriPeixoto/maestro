# ADR-011: Postgres for Configuration and State

**Status:** Accepted
**Date:** 2026-11-05

## Context

Maestro keeps three kinds of data, today spread over three stores:

- **Telemetry and history** (metrics, logs, notification deliveries, anomaly episodes) in ClickHouse.
- **Configuration** (alert rules and channels) in ClickHouse `ReplacingMergeTree` tables, and **alert state**
  (what is firing, cooldowns, servers already given default rules) in Redis.
- **Accounts** in a SQLite file next to the API.

That split no longer fits what comes next:

- Configuration is edited row by row and read whole. `ReplacingMergeTree` only deduplicates on merge, so every
  read needs `FINAL` or an `argMax`, there are no unique constraints, and an update is an insert of a new version.
- Alert state needs transactions: one evaluation reads a rule, compares it with what is firing and records the
  change. In Redis that is several keys with no transaction across them, and Redis is leaving Maestro anyway
  (ingestion moves to NATS JetStream).
- SQLite ties the accounts to one host and one process. Roles, an audit log and a temporary password per account
  are next, and a second API process or an alerting service on another host must see the same accounts.

## Decision

1. **Postgres holds configuration and state**: accounts, and next rules, channels, alert state, server groups,
   silences and the cron job catalog. One database (`maestro`), one application account (`maestro_app`) with
   `SELECT, INSERT, UPDATE, DELETE` only.
2. **ClickHouse keeps everything that is history**: metrics, logs, notification deliveries, anomaly episodes and,
   later, cron runs. The rule of thumb: rows that are appended and read by time range go to ClickHouse; rows
   that are edited and read by key go to Postgres.
3. **Alembic owns the Postgres schema** (`api/alembic/versions`). The API never creates or alters tables and
   refuses to start when the database is behind the code. Migrations are applied by the database owner, either
   with `alembic upgrade head` under an owner account or by running the SQL from `alembic upgrade head --sql`
   in a SQL client, so the application account needs no DDL privileges.
4. **SQLAlchemy 2 (async) with asyncpg** as the access layer, configured by `MAESTRO_DATABASE_URL`. Query
   functions return plain dicts, so the routers do not depend on the ORM.
5. **Postgres 16** is the supported baseline; Compose and CI run 16.

## Consequences

- One more service to run. In exchange, Redis drops to streams, heartbeats and worker health until NATS replaces
  it, and SQLite goes away.
- Login lockouts live with the account, so they survive a restart and an administrator can lift them. Identifiers
  that match no account keep an in-memory counter with the same limits, so a 429 does not reveal which accounts
  exist.
- Upgrading from 0.1.0 needs a one-time copy of the accounts: `python -m app.import_sqlite <file>`. It can run
  again without duplicating, never overwrites an account already in Postgres, and only reads the SQLite file.
- Tests that touch Postgres need a database: they read `MAESTRO_TEST_DATABASE_URL` and are skipped without it,
  except in CI, where `MAESTRO_REQUIRE_TEST_DATABASE=1` turns the skip into a failure.
- Rules, channels and alert state moved in 0.2.0 (`python -m app.import_alerting` copies them once). A
  change of alert state is a compare-and-set on a `version` column, applied before anything is sent, and the
  evaluator runs behind an advisory lock: a second evaluator stands by. Together with the event id that keys
  each delivery, that is what a redundant evaluator on another host would need.
- The database enforces what the API used to check alone: valid operators and severities, one active copy of
  a rule per server, a channel only for a rule of its own server, channel config as a JSON object.
- Postgres becomes something the alerting path depends on. A service that must keep alerting while Postgres is
  down caches the rules it needs locally.

## Alternatives considered

- **Keep configuration in ClickHouse.** No new service, but no transactions or unique constraints, and every read
  pays for deduplication. Rejected.
- **SQLite for everything relational.** Simple, but single-host and single-writer. Rejected for the same reasons
  the accounts are leaving it.
- **Schema created by the API at startup** (`create_all`). Convenient, but needs DDL privileges for the
  application account and has no upgrade path. Rejected in favour of Alembic.
