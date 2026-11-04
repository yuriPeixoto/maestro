# Maestro — Claude Context

## What This Project Is

**On-premise observability and telemetry platform. NOT a cloud SaaS.**
Born from real on-premise infrastructure pain (no Datadog, no Sentry, no cloud), and maintained as an
open-source portfolio project. Data never leaves the monitored infrastructure.

Part of a small ecosystem of the author's open-source ops tools: **Orquestra** (deployments) and
**Aegis** (ticketing) — see Phase 6 issues for the planned integrations.

## Architecture

```
maestro/
├── agent/      # Go 1.27 — collector binary (cmd/agent) and the external watchdog (cmd/watchdog)
├── api/        # Python 3.14 + FastAPI — ingestion, alerts, ML, REST API
├── frontend/   # React + Vite + Tailwind + ECharts + TanStack Query + Zustand
├── migrations/ # ClickHouse SQL migrations
└── docs/       # roadmap.md, deployment.md, adrs/
```

**Data flow:**
```
[Go Agent] → Redis Streams → [worker: consumers] → ClickHouse
                                    ↓
                        [worker: alert evaluator] → Telegram / webhook / Slack / email
                                    ↓
              [worker: seasonal baseline, disk trend] → anomaly scores and episodes, forecasts

[API: HTTP only] ← dashboard        [Watchdog, on another host] → polls /health → Telegram
```

Two processes: `app.main` (API, HTTP only) and `app.worker` (`python -m app.worker`: consumers,
alert evaluator and scheduled jobs; run exactly one). Each worker task runs under `task_health.supervise`,
which restarts it; the consumers and the evaluator beat after each good cycle. The worker publishes its task
reports to Redis every 15 s (`worker_health.py`) and the API's `/health` (no login) answers 503 when the
report is older than 45 s or a watched task is down or stale. CPU-heavy ML (baseline refit, forecasts)
goes through `app.ml.pool.run_in_ml_process` to a single nice'd child process; functions sent there must be
module-level (picklable). Consumers ack a stream message only after it was written (`stream_reader.py`) and
re-read their pending list first.

Alerting: `rule_values.py` (`heartbeat_age_seconds` comes from Redis, the rest from ClickHouse),
`default_rules.py` (five rules per new server, from the `health_status` limits), `alert_channels.py`
(channels per server, `rule_id` nil = every rule), `notification_dispatcher.py` (one `notification_log`
row per delivery). Failure reasons never carry a URL or token; httpx logs at WARNING for that reason.

## Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Agent | Go 1.27 | Collect metrics/logs/inventory, batch-send to Redis Streams, local ring buffer |
| API | Python 3.14, FastAPI | Consume streams, write ClickHouse, alerts, ML, REST API |
| Storage | ClickHouse | Telemetry (MergeTree, hourly rollup in `metrics_hourly`) and alert config (ReplacingMergeTree) |
| Users | SQLite | Accounts and password reset (single API instance) |
| Queue | Redis Streams | Decouple agent from storage — resilience buffer |
| Frontend | React + Vite + ECharts + TanStack Query + Zustand | Dashboard |

## Go Conventions

- Module path: `github.com/yuriPeixoto/maestro/agent`
- Go version: see `agent/go.mod`
- Batching: send events in batches (size OR timeout) to reduce connection overhead
- Binary must be self-contained — no runtime dependencies

## Python Conventions

- Virtual environment: `api/.venv/` (gitignored)
- Dependencies: `api/pyproject.toml`, locked in `api/uv.lock` (`uv sync --locked`; `uv lock` after editing
  the dependency list). PyJWT signs the tokens; `MAESTRO_JWT_SECRET` is required (32+ characters).
- Async FastAPI — all endpoints `async def`
- Pydantic models for all request/response contracts

## Key Design Decisions (see docs/adrs/ for full context)

- **Go for agent**: performance + single binary deployment
- **Python for API**: data ecosystem (pandas, NumPy, SciPy); ML choices are measured with `app.ml.evaluation` (ADR-010)
- **ClickHouse over PostgreSQL** for telemetry: columnar OLAP, MergeTree, TTL
- **Redis Streams over Kafka**: lower infra overhead, sufficient throughput for on-premise
- **On-premise first**: no external cloud dependencies

## Language Policy

- Code, docs, issues, PRs: English
- `README.pt-BR.md`: Portuguese (Brazil) translation of the README

## Workflow

```bash
git checkout main && git pull origin main
git checkout -b feature/<slug>

# Go
cd agent && go vet ./... && go test ./...

# Python
cd api && uv run --locked python -m pytest

# Frontend
cd frontend && npm run build && npm run lint

# Commit (conventional commits)
git commit -m "feat(scope): description"
```

CI (`.github/workflows/ci.yml`) runs the same checks on every PR and on `main`.

## Versioning

- One version for the whole project in `VERSION`. A release bumps it together with `api/pyproject.toml`,
  `frontend/package.json` (and `uv lock` / `npm install --package-lock-only`); `tests/test_release.py`
  fails when they differ.
- Every release adds an entry to `CHANGELOG.md` (technical, English) and, when the dashboard's users
  notice something, to `api/app/release_notes.json` (short lines, `pt-BR` and `en`, a `**lead-in**` allowed).
  The newest notes must be for the current version. A release with nothing for users gets no notes entry, and
  the "what's new" modal stays closed.
- The agent gets the version at build time: `-ldflags "-X .../internal/heartbeat.Version=$(cat ../VERSION)"`.
  The About screen marks an agent whose version differs from Maestro's as outdated.
- After the merge: tag `vX.Y.Z` and a GitHub release, only when the maintainer asks.

## Current State (updated 2026-11-04)

- Version 0.1.0. Phases 1–4 shipped: data pipeline, dashboard, anomaly detection, capacity planning.
  The ML approach was measured and replaced in 2026-11 (ADR-010).
- Phase 5 (Production Hardening) open items: #78 (cron job tracking), #37 (API reference),
  #91 (Ruff for the API), #99 (admin password reset).
- Phase 6 (Integrations): #29 (Orquestra as a deploy event source), #85 (Aegis log-pattern alerts + ticket dispatcher).
- No public demo. `deploy.yml` targets a server that no longer exists and is
  disabled on GitHub: merging to `main` deploys nothing. Installations are updated by hand (`docs/deployment.md`).
- Installation-specific context, when there is any, lives in `CLAUDE.local.md` (not versioned).

## Known Gaps

- **No machine authentication.** Every router except `/auth` requires a user JWT, including
  `/agents/register` and `/events`. The agent sends no token, so its registration always gets a 401
  (it is best-effort and collection is unaffected), and the agent registry stays empty. The vulnerability
  scanner discovers servers through heartbeats for that reason. This blocks #78; see ADR-009.
- #78 (cron tracking): an `exit_code`-only wrapper misses jobs that fail but exit 0 (e.g. PHP `die()`);
  also match fatal-error patterns in stdout (`Fatal error`, `Uncaught`, `PDOException`, `SQLSTATE`).
- Alerting only understands numeric-threshold/ML rules; log-pattern rules and an Aegis ticket
  dispatcher are needed for #85.
- A failed notification is recorded in `notification_log` but not retried. No silence, maintenance window,
  global or group rules yet. A rule whose metric goes silent keeps its last state (it neither fires nor
  resolves) until data returns.
- Rules, channels and alert state live in ClickHouse and Redis; the migration to Postgres is planned.
- No URL routing in the frontend (view state lives in `useState`), so alerts cannot deep-link to a chart.
- The OS package scan only supports Debian; other distributions are skipped by the agent. A server with no
  package snapshot still gets a scan date and reads as "no known vulnerabilities".
- SSH screens depend on `auth.log`. A host that logs to journald only shows "no data" until the agent reads it.
- The agent reads inventory versions only at startup, and reports a stopped service and a client-only install
  alike as `inactive`, so the service list shows only `active` and `failed`.
- `/security/{id}/attack-by-hour` groups by UTC hour and the screen shows it as is.
- Dashboard incidents cover only the focus server.

## Skills

`/sprint <issue(s)>` and `/pr` come from the author's global Claude Code setup (not this repo).
They read this file, so project-specific rules belong here:

- PR checks must mirror CI: `go vet ./... && go test ./...` and building `cmd/agent` and `cmd/watchdog` (agent), `uv run --locked python -m pytest` (api),
  `npm run build && npm run lint` (frontend).
- Before architectural decisions, read the relevant ADR in `docs/adrs/`.
- PR titles, descriptions and commits in English.

## Key Docs

- `docs/roadmap.md` — phased roadmap with issues per phase
- `docs/deployment.md` — bare-metal deployment (systemd), alert channels, `/health`
- `docs/watchdog.md` — the external watchdog
- `docs/adrs/` — architecture decision records (001–007, 009 and 010; 008 was an operations note and was removed; 010 supersedes 005)
