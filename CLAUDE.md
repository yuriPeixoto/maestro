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
├── frontend/   # React + Vite + Tailwind + ECharts — dashboard
└── docs/adrs/  # Architecture Decision Records
```

**Data flow:**
```
[Go Agent] → Redis Streams → [Python Worker] → ClickHouse
                                     ↓
                             [Alert Engine] → Slack/Discord/Telegram
                                     ↓
                             [Pandas/ML] → Dynamic Thresholds (Phase 3)
```

## Stack

| Component | Technology | Role |
|-----------|-----------|------|
| Agent | Go 1.26 | Collect metrics (CPU/RAM/disk), compress, batch-send |
| API | Python 3.10+, FastAPI | Ingest, orchestrate, alerts, analytics |
| Storage | ClickHouse | OLAP time-series (NOT PostgreSQL for telemetry) |
| Queue | Redis Streams | Decouple agent from storage — resilience buffer |
| Frontend | React + Vite + ECharts | Real-time dashboard |

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

Phase 1 in progress — mostly scaffolding.
Immediate next: Go agent with real CPU/memory collection via `gopsutil`.

**Pending housekeeping:**
- `go.mod`: update `go 1.25.0` → `go 1.26.0`
- Convert ADRs from `.txt` → `.md`
- Add `frontend/node_modules/` to `.gitignore`

## Skills Disponíveis

| Skill | Uso |
|-------|-----|
| `/sprint <issue(s)>` | Inicia sprint: lê issues, cria branch, apresenta plano |
| `/pr` | Cria PR com template padrão para main |

**UI/UX:** Para qualquer trabalho no dashboard (frontend/), usar a skill **UI/UX Pro Max**
(https://github.com/nextlevelbuilder/ui-ux-pro-max-skill).
Garante: design system coerente, WCAG AA, responsivo, ECharts integrado.

## Key Docs

- `docs/adrs/ADR 01 - Architecture.txt` — system architecture decisions
- `docs/adrs/ADR 02 - Infrastructure.txt` — stack justification
- `docs/adrs/ADR 03 - Multi-language Strategy.txt` — EN/PT-BR policy
