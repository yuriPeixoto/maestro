.PHONY: agent-build agent-debug agent-test api-dev api-install migrate migrate-dry

# ── Agent ────────────────────────────────────────────────────────────────────

agent-build:
	$(MAKE) -C agent build

agent-debug:
	$(MAKE) -C agent debug

agent-test:
	$(MAKE) -C agent test

# ── API ───────────────────────────────────────────────────────────────────────

# Install Python dependencies (run once, or after requirements.txt changes)
api-install:
	pip install -r api/requirements.txt

# Run the FastAPI dev server with auto-reload
api-dev:
	uvicorn app.main:app --reload --app-dir api --host 0.0.0.0 --port 8000

# ── ClickHouse Migrations ─────────────────────────────────────────────────────
#
# Required env vars (or edit defaults below):
#   CLICKHOUSE_HOST     default: localhost
#   CLICKHOUSE_PORT     default: 8123
#   CLICKHOUSE_USER     default: default
#   CLICKHOUSE_PASSWORD default: (empty)
#
# Usage:
#   make migrate                                            # apply all migrations
#   make migrate FILE=migrations/001_create_metrics.sql    # apply one file

CLICKHOUSE_HOST     ?= localhost
CLICKHOUSE_PORT     ?= 8123
CLICKHOUSE_USER     ?= default
CLICKHOUSE_PASSWORD ?=

CLICKHOUSE_CMD = clickhouse-client \
	--host $(CLICKHOUSE_HOST) \
	--port $(CLICKHOUSE_PORT) \
	--user $(CLICKHOUSE_USER) \
	$(if $(CLICKHOUSE_PASSWORD),--password $(CLICKHOUSE_PASSWORD),) \
	--multiquery

migrate:
ifdef FILE
	@echo "Applying $(FILE)..."
	$(CLICKHOUSE_CMD) < $(FILE)
	@echo "Done."
else
	@echo "Applying all migrations in order..."
	@for f in $(sort $(wildcard migrations/*.sql)); do \
		echo "  -> $$f"; \
		$(CLICKHOUSE_CMD) < $$f; \
	done
	@echo "All migrations applied."
endif

migrate-dry:
	@echo "Migrations to apply:"
	@for f in $(sort $(wildcard migrations/*.sql)); do echo "  $$f"; done
