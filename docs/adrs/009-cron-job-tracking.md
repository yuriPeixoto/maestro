# ADR-009: Cron Job Tracking

**Status:** Proposed
**Date:** 2026-10-30

Records the design of issue #78. Not implemented yet.

## Context

Scheduled jobs (backups, ETL scripts, bots, maintenance routines) are invisible to OS-level metrics. A job
that never runs produces no CPU or memory signal, and neither does one that exits 0 after failing. The failure
modes to cover:

- a job does not run at all (cron misconfiguration, permission error);
- a job stalls, visible only by the absence of a completion event;
- a job takes ten times longer than usual;
- a job fails and still exits 0, for example a script that prints a fatal error to stdout and calls `die()`.

## Decision

### 1. Two collection strategies

- **`maestro-cron` wrapper, for critical jobs.** A thin Go binary shipped with the agent wraps the command in
  the crontab and emits start and finish events. It always runs the job, even when the API is unreachable.
- **Passive crontab discovery, for inventory.** The agent reads `/etc/crontab`, `/etc/cron.d/*`,
  `/var/spool/cron/crontabs/*` and `systemctl list-timers`, and emits the schedules it finds. This is the source
  of truth for missed-run detection and needs no crontab changes.

Discovery alone cannot tell whether a job succeeded, and the wrapper alone cannot see jobs nobody wrapped, so
both are needed.

### 2. Three-tier failure detection

A wrapped command failed if any of these holds, in this order. The reason is recorded in `failure_reason`:

1. `exit_code`: the exit code is not 0;
2. `stderr_non_empty`: anything was written to stderr;
3. `stdout_pattern`: stdout matches a fatal-error pattern (default, case-insensitive: `Fatal error`, `Uncaught`,
   `PDOException`, `SQLSTATE`; overridable per job with `--fatal-pattern`).

Exit-code-only detection was rejected because it misses the fourth failure mode above, which happened in
production.

### 3. Reuse `server_events`

Executions and discovered schedules are stored as events in the `server_events` table (migration 009), with the
details in its `metadata` JSON field. Event types: `cron_start`, `cron_finish`, `cron_fail`,
`cron_schedule_discovered`.

### 4. Alerts through the existing pipeline

| Alert | Condition | Severity |
|-------|-----------|----------|
| `cron_missed` | Expected run plus 10 minutes of grace, with no `cron_start` | warning |
| `cron_failed` | `cron_fail` received | warning |
| `cron_duration_anomaly` | Duration above 3× the rolling 7-day p95 | info |

All three go through the alert evaluator (ADR-007) and, when configured, through the Aegis dispatcher of #85.

## Open question: machine authentication

The design assumes `POST /events/{server_id}` as the ingestion path and a 404 for an unregistered `server_id`.
Neither works today:

- `/events` and `/agents/register` require a user JWT, and neither the agent nor a cron job has one;
- the agent's registration therefore always gets a 401, so the registry is empty and validating `server_id`
  against it would reject every event.

This must be solved before #78. Two candidates:

- **Agent API key.** A per-server credential sent to `/agents/*` and `/events`. Keeps the HTTP path of #78 and
  fixes the registry, but adds key management.
- **Publish cron events to Redis.** `maestro-cron` uses the connection the agent already has, like metrics and
  logs. No new credentials, and `server_events` is fed by a consumer, but event delivery no longer goes through
  the validation in the API.

## Consequences

- No new table and no new alert pipeline.
- Crontabs change only for jobs that need the wrapper; the rest are covered by discovery.
- Stderr as a failure signal will flag jobs that write warnings there. Those jobs need their output cleaned up
  or a way to opt out.
- The 7-day baseline means duration alerts only start a week after a job is first seen.
