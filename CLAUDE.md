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
├── agent/      # Go 1.27 — lightweight collector binary (single executable, no deps)
├── api/        # Python 3.14 + FastAPI — ingestion, alerts, ML, REST API
├── frontend/   # React + Vite + Tailwind + ECharts + TanStack Query + Zustand
├── migrations/ # ClickHouse SQL migrations
└── docs/       # roadmap.md, deployment.md, adrs/
```

**Data flow:**
```
[Go Agent] → Redis Streams → [API consumers] → ClickHouse
                                    ↓
                        [Alert evaluator] → webhook / email / Slack
                                    ↓
              [ML: Isolation Forest, River, Prophet] → anomaly scores, forecasts
```

Note: consumers, alert evaluator and ML schedulers currently run as asyncio tasks inside the API
process (`api/app/main.py` lifespan), not as separate processes.

## Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Agent | Go 1.27 | Collect metrics/logs/inventory, batch-send to Redis Streams, local ring buffer |
| API | Python 3.14, FastAPI | Consume streams, write ClickHouse, alerts, ML, REST API |
| Storage | ClickHouse | Telemetry (MergeTree) and alert config (ReplacingMergeTree) |
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
- Dependencies: `api/requirements.txt`
- Async FastAPI — all endpoints `async def`
- Pydantic models for all request/response contracts

## Key Design Decisions (see docs/adrs/ for full context)

- **Go for agent**: performance + single binary deployment
- **Python for API**: ML ecosystem (Pandas, Scikit-learn, River, Prophet)
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
cd api && python -m pytest

# Frontend
cd frontend && npm run build && npm run lint

# Commit (conventional commits)
git commit -m "feat(scope): description"
```

CI (`.github/workflows/ci.yml`) runs the same checks on every PR and on `main`.
Frontend lint is non-blocking until #90 is done.

## Current State (updated 2026-10-12)

- Phases 1–4 shipped: data pipeline, dashboard, ML anomaly detection, capacity planning.
- Phase 5 (Production Hardening) open items: #78 (cron job tracking), #37 (API/deploy docs),
  #38 (README polish), #90 (frontend lint), #91 (Ruff for the API).
- Phase 6 (Integrations): #29 (Orquestra deploy annotations), #85 (Aegis log-pattern alerts + ticket dispatcher).
- **No running deployment**: the former staging VPS is gone; `deploy.yml` (self-hosted runner) is disabled.
  Merging to `main` deploys nothing.

## Known Gaps

- #78 (cron tracking): an `exit_code`-only wrapper misses jobs that fail but exit 0 (e.g. PHP `die()`);
  also match fatal-error patterns in stdout (`Fatal error`, `Uncaught`, `PDOException`, `SQLSTATE`).
- Alerting only understands numeric-threshold/ML rules; log-pattern rules and an Aegis ticket
  dispatcher are needed for #85.
- No URL routing in the frontend (view state lives in `useState`), so alerts cannot deep-link to a chart.

## Skills

`/sprint <issue(s)>` and `/pr` come from the author's global Claude Code setup (not this repo).
They read this file, so project-specific rules belong here:

- PR checks must mirror CI: `go vet ./... && go test ./...` (agent), `python -m pytest` (api),
  `npm run build && npm run lint` (frontend).
- Before architectural decisions, read the relevant ADR in `docs/adrs/`.
- PR titles, descriptions and commits in English.

## Key Docs

- `docs/roadmap.md` — phased roadmap with issues per phase
- `docs/deployment.md` — bare-metal deployment (systemd)
- `docs/adrs/` — architecture decision records (001–008)
