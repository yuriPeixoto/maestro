# Maestro — Claude Context

## What This Project Is

**On-premise observability and telemetry platform. NOT a cloud SaaS.**
Real origin: company runs on a local Windows server — no Datadog, no Sentry, no AWS.
Built to solve real infrastructure pain with no external dependencies.

## Architecture

```
maestro/
├── agent/      # Go 1.26 — lightweight collector binary (single executable, no deps)
├── api/        # Python 3.10+ FastAPI — ingestion, alerts, intelligence
├── frontend/   # React + Vite + Tailwind + Recharts — dashboard
└── docs/       # roadmap.md + adrs/
```

**Data flow:**
```
[Go Agent] → Redis Streams → [Python Worker] → ClickHouse
                                     ↓
                          [Alert Evaluator Worker]
                                     ↓
                           [Alert Manager] → webhook / email / Slack
                                     ↓
                        [ML Pipeline] → Dynamic Thresholds (Phase 3)
```

## Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Agent | Go 1.26 | Collect metrics (CPU/RAM/disk), compress, batch-send |
| API | Python 3.10+, FastAPI | Ingest, orchestrate, alerts, analytics |
| Storage | ClickHouse | OLAP time-series (NOT PostgreSQL for telemetry) |
| Queue | Redis Streams | Decouple agent from storage — resilience buffer |
| Frontend | React + Vite + Recharts + TanStack Query + Zustand | Real-time dashboard |

## Go Conventions

- Module path: `github.com/yuriPeixoto/maestro/agent`
- Go version: `go 1.26.0` in `go.mod`
- Patterns: Worker Pool + Buffered Channels + Goroutines for concurrent collection
- Batching: send events in batches (50 items OR 5s timeout) to reduce connection overhead
- Binary must be self-contained — no runtime dependencies

## Python Conventions

- Virtual environment: `.venv/` (gitignored)
- Dependency management: `requirements.txt` (pin versions in production)
- Async FastAPI — all endpoints `async def`
- Pydantic models for all request/response contracts
- Workers run as independent processes (not threads)

## Key Design Decisions (see docs/adrs/ for full context)

- **Go for agent**: performance + single binary deployment
- **Python for API**: ML ecosystem (Pandas, Scikit-learn) for future anomaly detection
- **ClickHouse over PostgreSQL**: columnar OLAP, MergeTree engine, ZSTD compression
- **Redis Streams over Kafka**: lower infra overhead, sufficient throughput for on-premise
- **On-premise first**: no external cloud dependencies, data never leaves the server

## Multilingual Policy

- Code: English exclusively
- `README.md`: English (primary)
- `README.pt-BR.md`: Portuguese Brazilian (secondary)
- ADRs: may be in PT-BR, migrate to EN as project scales

## Workflow

```bash
git checkout main && git pull origin main
git checkout -b feature/<slug>

# Go
cd agent && go vet ./... && go test ./...

# Python
cd api && python -m pytest

# Commit
git commit -m "feat(scope): description"
```

## Current State (updated 2026-09-23)

Phases 1–4 shipped: data pipeline, dashboard, ML anomaly detection, capacity planning.
Phase 5 (Production Hardening) is 9/12 — remaining: #78 (cron job tracking), #37 (API/deploy docs), #38 (README polish).
Phase 6 (Integrations) has #29 (Orquestra deploy annotations) open; no Aegis integration issue exists yet (see Known Gaps below).

Deployed in production on the project's own VPS (`153.75.226.75`) — agent, API, ClickHouse, Redis, and
frontend all running there via CI/CD (`deploy.yml` on push to `main`). Today it only monitors itself
(single self-hosted server) — it has never been pointed at the company's actual production infrastructure
(the `.10` robot server, the `.40` shared web server, etc.), which is where `cronwatch` and
`log-watch-aegis` currently do that job as narrower, purpose-built stopgap tools.

Company-wide rollout is now the active initiative: deploy the agent to `.40` (shared web server), `.10`
(SmarTEC robots), `.5` (Carvalima fleet mgmt), and the DB servers `.3`/`.16`/`.14` (via the existing
`db_monitor` collector), with the goal of retiring `cronwatch` and `log-watch-aegis` once Maestro reaches
parity with what they cover today. See `docs/roadmap.md` for phase breakdown and
`github.com/yuriPeixoto/maestro/milestone/5` and `/milestone/6` for active issues.

## Known Gaps (found during 2026-09-23 review, before company rollout)

- **#78 (cron tracking) is under-scoped vs. `cronwatch`.** The proposed `maestro-cron` wrapper only
  captures `exit_code` + `stderr_tail`. `cronwatch` (the tool it's meant to replace) had to add a third
  failure heuristic — matching `Fatal error`/`Uncaught`/`PDOException`/`SQLSTATE` in stdout — after a real
  production case where a robot called `die()` and exited 0 despite failing. Add that heuristic to #78's
  scope before treating it as a `cronwatch` replacement.
- **No Aegis notification integration exists.** `api/app/*_dispatcher.py` only supports webhook/email/Slack
  with a metric-shaped payload (`server_id`, `metric_name`, `value`, `threshold`). There is no dispatcher
  that can open/update an Aegis ticket, and the alert evaluator only understands numeric-threshold/ML rules
  — not "alert when a log line matches a pattern." This is a hard blocker for replacing `log-watch-aegis`
  and `cronwatch`, since both work by opening Aegis tickets on log/exec failures. Spec'd informally in Aegis
  ticket #1146 (log-pattern rule) — needs to become a real GitHub issue with acceptance criteria before
  work starts.
- **No deployment plan exists for `.10`.** Aegis ticket #1147 only covers deploying the agent to `.40`;
  there's no ticket yet for the robot server.

## Skills Disponíveis

| Skill | Uso |
|-------|-----|
| `/sprint <issue(s)>` | Inicia sprint: lê issues, cria branch, apresenta plano |
| `/pr` | Cria PR com template padrão para main |

**UI/UX:** Para qualquer trabalho no dashboard (frontend/), usar a skill **UI/UX Pro Max**
(https://github.com/nextlevelbuilder/ui-ux-pro-max-skill).
Garante: design system coerente, WCAG AA, responsivo, Recharts integrado.

## Key Docs

- `docs/roadmap.md` — 5-phase roadmap with all issues per phase
- `docs/adrs/001-architecture.md` — system architecture, Go agent design, data pipeline
- `docs/adrs/002-infrastructure.md` — stack justification (Go vs Python roles, ClickHouse vs Postgres)
- `docs/adrs/003-multilanguage-strategy.md` — EN/PT-BR documentation policy
- `docs/adrs/004-clickhouse-schema.md` — MergeTree schema, sort key, partitioning, 90-day TTL
- `docs/adrs/005-ml-phased-approach.md` — Isolation Forest → River → Prophet (capacity only)
- `docs/adrs/006-frontend-stack.md` — Vite + React + Tailwind + TanStack Query + Zustand + Recharts
- `docs/adrs/007-alerting-pipeline.md` — evaluator worker, alert manager state machine, channels
