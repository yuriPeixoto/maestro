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

## Current State

Phase 1 in progress — agent and API are scaffolding only.
Next: implement issues #1–#4 (Go agent metric collection, buffer, heartbeat, naming).
See `docs/roadmap.md` for full phase breakdown and `github.com/yuriPeixoto/maestro/milestone/1` for active issues.

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
