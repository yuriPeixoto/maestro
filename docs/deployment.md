# Maestro — Deployment Guide

Bare-metal installation of the API, the dashboard and the agent. Docker Compose (see the
[README](../README.md)) is meant for local development only.

There is no automated pipeline and there are no published releases yet: you build the agent and the
frontend, copy them to the server and restart the services. The `deploy.yml` workflow in this repository
is disabled.

The examples install everything under `/opt/maestro`. Any other path works.

## Requirements

| Component | Requirement |
|-----------|-------------|
| API | Python 3.14 and [uv](https://docs.astral.sh/uv/) (a single binary; installs the locked dependencies) |
| Postgres | 16 or later; accounts, roles, the audit log, alert rules, channels and alert state ([ADR-011](adrs/011-postgres-config-state.md)) |
| ClickHouse | Any recent version; the migrations are tested against 25.5 and later |
| Redis | Reachable from the API and from every agent; Streams support (5.0+) |
| Frontend build | Node.js 20.19+ (build only, nothing runs on the server) |
| Agent build | Go 1.27 (build only, the agent is a single binary) |
| Web server | Any reverse proxy; nginx and Apache examples below |

The API and the agents share one Redis, so an agent on another host needs network access to it. Keys and
streams use the `maestro:` prefix, which allows sharing a Redis instance with other applications.

## 1. Postgres

Configuration and state live in Postgres; telemetry and history stay in ClickHouse. The API connects as
`maestro_app`, which reads and writes rows but cannot change the schema. The schema is applied by the
database owner. Connect as a superuser and run one statement at a time (`CREATE DATABASE` cannot run inside
a transaction):

```sql
CREATE ROLE maestro_app LOGIN PASSWORD 'CHANGE_ME_USE_A_STRONG_PASSWORD';

CREATE DATABASE maestro;

REVOKE ALL ON DATABASE maestro FROM PUBLIC;

GRANT CONNECT ON DATABASE maestro TO maestro_app;
```

Then, connected to the `maestro` database, still as the owner:

```sql
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO maestro_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO maestro_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO maestro_app;
```

The default privileges apply to tables the same owner creates later, so every migration's tables reach
`maestro_app` without a new grant. Use letters and digits for the password: it goes inside
`MAESTRO_DATABASE_URL`, where `@ : / % # ?` would have to be percent-encoded.

The schema comes from Alembic (`api/alembic/versions`). To apply it as the owner, either point
`MAESTRO_DATABASE_URL` at an owner account for one run:

```bash
cd /opt/maestro/api
MAESTRO_DATABASE_URL=postgresql://postgres@db-host:5432/maestro .venv/bin/alembic upgrade head
```

or print the SQL and run it yourself in a SQL client (it includes the `alembic_version` bookkeeping):

```bash
.venv/bin/alembic upgrade head --sql > maestro-schema.sql
```

The API and the worker refuse to start while the database is behind the code, naming both revisions.

Each Maestro connection names itself in `pg_stat_activity` (`maestro-api`, `maestro-worker`,
`maestro-import`) and runs with `statement_timeout` 15 s, `lock_timeout` 5 s and
`idle_in_transaction_session_timeout` 60 s, so a stuck query never holds a shared database. The worker's
alert evaluator also keeps one idle connection holding an advisory lock: a second worker's evaluator stands by
instead of judging the same rules.

## 2. ClickHouse

The API must connect as `maestro_app`, not as `default`: `default` has full admin privileges. Connect as
`default` and run:

```sql
CREATE DATABASE IF NOT EXISTS maestro;

CREATE USER IF NOT EXISTS maestro_app
    IDENTIFIED WITH sha256_password BY 'CHANGE_ME_USE_A_STRONG_PASSWORD';

GRANT SELECT, INSERT ON maestro.* TO maestro_app;

SHOW GRANTS FOR maestro_app;
```

Then apply the migrations, also as `default`, because `maestro_app` has no DDL privileges on purpose:

```bash
for f in migrations/*.sql; do
  clickhouse-client --multiquery < "$f"
done
```

The migrations hardcode the `maestro` database name in their table names.

## 3. API

```bash
cd /opt/maestro/api
uv sync --locked --no-dev --python python3.14   # creates .venv from uv.lock
cp .env.example .env
```

`--locked` installs exactly the versions in `uv.lock` and fails if the lock no longer matches
`pyproject.toml`; `--no-dev` leaves out the test tools.

Set at least these values in `.env`, and make the file readable only by the service user:

```env
MAESTRO_REDIS_URL=redis://127.0.0.1:6379

MAESTRO_CLICKHOUSE_HOST=127.0.0.1
MAESTRO_CLICKHOUSE_USER=maestro_app
MAESTRO_CLICKHOUSE_PASSWORD=CHANGE_ME_USE_A_STRONG_PASSWORD

# Required: openssl rand -hex 32. The API refuses to start with an empty, short (< 32 characters)
# or published default secret.
MAESTRO_JWT_SECRET=

# Required: the Postgres account from section 1.
MAESTRO_DATABASE_URL=postgresql://maestro_app:CHANGE_ME@db-host:5432/maestro

# Name shown in the interface; leave empty to hide it
MAESTRO_CLIENT_NAME=
```

A server's state comes from default limits for CPU, memory and disk plus the alert rules firing now. CPU is
judged on its 5-minute average, so a short spike does not read as an overloaded server. To change the limits,
set `MAESTRO_HEALTH_*_PERCENT` (see `api/.env.example`).

Anomaly detection keeps no model files: its seasonal baseline is refitted from ClickHouse every day.

### Alerts

Rules, channels and where each alert stands live in Postgres; what fired and every delivery stay in
ClickHouse (`alert_events`, `notification_log`). A rule is set for every server, a server group or one server;
per metric and severity a server is judged by the most specific one, and a rule switched off on a server or group
silences the inherited one there (ADR-013). Five default rules for every server are stored once, when the
worker first runs: no heartbeat for `MAESTRO_OFFLINE_THRESHOLD_SECONDS`, disk at the attention and critical
limits, and memory and CPU (5-minute average) at the critical limit. The limits are the
`MAESTRO_HEALTH_*_PERCENT` ones, so a rule fires when the dashboard changes colour. They are editable, and a
deleted one is not recreated.

Alerts go to every channel that reaches the server: channels for every server, for its group and its own add up.
A channel takes every rule or a single one. Every delivery, including the "send test" button, lands in the
delivery history.

What a cycle has to say about one server goes out as one message per channel. A firing alert repeats at its
rule's "repeat after" interval until someone (an operator or an admin) acknowledges it; it then stays open
without repeating. A metric that stops arriving puts its rule in "no data", said once, unless the server has no
heartbeat at all. A delivery that fails is tried again after 1, 2, 4, 8, 16 and 32 minutes and then given up,
with a line in the worker's log; the screen shows what is waiting (ADR-014).

A silence (with a deadline and a reason) or a maintenance window (once, or weekly at a local time) keeps alerts
from being sent; the rules are still judged and the events recorded, and what changed meanwhile is announced
when it ends. The database refuses two overlapping
windows on one server, through an exclusion constraint that needs the `btree_gist` extension. It is a trusted
extension, so the owner applying the migrations creates it; where it is already installed nothing changes.

A server is named by the hostname its agent reports, which stays its identity in notifications and the audit
log. An admin may give it a shared label (shown beside the hostname in notifications, too) and a group; each
account may give it a nickname that only its own screens show.

For Telegram, create a bot with @BotFather and add it to the chat that should receive the alerts, then set:

```bash
MAESTRO_TELEGRAM_BOT_TOKEN=          # only here, never in a channel's config
MAESTRO_TELEGRAM_DEFAULT_CHAT_ID=    # used by channels created with an empty chat id
```

E-mail channels need the `MAESTRO_SMTP_*` settings; without them the type is not offered. Notification
texts are in Portuguese by default; set `MAESTRO_NOTIFICATION_LANGUAGE=en` for English.

The API cannot report its own outage. Run the [watchdog](watchdog.md) on another host for that.

### Anomalies and capacity

The worker learns what is normal for each server at each hour (seasonal baseline, refitted daily on 28 days)
and records episodes of 5 minutes or more out of that range, shown on the server view. It starts judging
after one day of data and uses the hour of the week once it has about two weeks. Disk capacity is a trend
since the last level shift; CPU and memory capacity is the daily 5-minute peak against the
`MAESTRO_HEALTH_*_CRITICAL_PERCENT` limits. The reasons and the measurements are in
[ADR-010](adrs/010-ml-measured.md); rerun them on your own data with `python -m app.ml.evaluation`.

Maestro runs as two processes from the same directory and `.env`:

- **API** (`uvicorn app.main:app`): HTTP only. Accounts and login lockouts are in Postgres; only the
  throttle for names that match no account is kept in memory, per process.
- **Worker** (`python -m app.worker`): stream consumers, the alert evaluator and the scheduled jobs
  (features, anomaly detection, forecasts, correlation, vulnerability scan). Run exactly one: a second worker
  would evaluate every alert twice. CPU-heavy ML work runs in a child process with a lower priority (`nice`),
  so the consumers keep their pace while a model trains.

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
.venv/bin/python -m app.worker
```

The worker publishes how its tasks are doing to Redis every 15 seconds, and the API's `/health` includes it:
a worker that stopped, or whose event loop is blocked, turns `/health` into a 503 with `worker: down` within
45 seconds.

### Accounts

Create the first accounts from a JSON file. They are admins unless an entry says `"role": "operator"` or
`"viewer"`, and they must change their password on first login:

```bash
cat > users.json <<'EOF'
[{"username": "alice", "email": "alice@example.com"}]
EOF

.venv/bin/python -m app.seed_users users.json
```

Leave the temporary password empty to get one random password per account. The command skips accounts that
already exist, so it is safe to run again. Delete `users.json` afterwards.

An account is locked for 15 minutes after 5 wrong passwords within 15 minutes; the lock is stored with the
account, so restarting the API does not lift it. A name that matches no account gets the same limit, kept in
memory, so the answer never tells which accounts exist.

There is no email reset. Someone who forgot their password asks an admin, who generates a temporary one on the
Users screen (`POST /users/{id}/temporary-password`). It is shown once, ends the account's open sessions, lifts
the lockout, and must be replaced on the next login.

### Roles and the audit log

| Role | Can |
|------|-----|
| `viewer` | See every screen |
| `operator` | Also create and delete alert rules and channels, send a channel test, add chart events, start a correlation run |
| `admin` | Also manage accounts, read the audit log and remove agents |

The matrix lives in `api/app/permissions.py`; `GET /auth/me` returns the caller's permissions and the screens
follow it: what a role does not allow is not shown. Admins manage accounts and read the audit log on the Users and
audit screen, where the Roles tab shows the matrix from `GET /users/roles`. Accounts are deactivated, never deleted. A deactivated account cannot log in, its open sessions are
refused, and the last active admin cannot be demoted or deactivated. Accounts from before 0.2.0 become admins.

`audit_log` records who did what, when, to what and from where. Changes to accounts, rules and channels are
written by a trigger, so an edit made straight in the database (or a `TRUNCATE`) is recorded too, as
`<database user> via <application_name>` with the client's address. What the worker changes on its own (adopting
the default rules, registering servers) is signed `maestro-worker` and shown as "Maestro (automatic)"; only the
API's database user, which the worker shares, can sign that way. Password hashes and channel configuration
never enter it (only whether they changed). The table is append-only: triggers refuse `UPDATE`, `DELETE` and
`TRUNCATE`, also for the API's own database user.

The trigger believes who the API says the caller is only on connections of the API's database user, which
migration `0003` records in `maestro_audit_api_role()`: by default the user in `MAESTRO_DATABASE_URL`. When you
generate or run the migration with another account, pass it: `alembic -x api_role=maestro_app upgrade head --sql`.

Limits: the log names database logins, not people, so give each person their own login and keep the API's
credentials to the API. A superuser or the tables' owner can disable the triggers; for that, keep a log
outside the database (`pgaudit` or `log_statement = 'mod'`). See ADR-012.

Behind a reverse proxy, the client address comes from `X-Forwarded-For`, believed only from
`MAESTRO_TRUSTED_PROXIES` (default `["127.0.0.1", "::1"]`).

## 4. Frontend

Build it anywhere and copy the result to the server. The frontend calls the API under `/api/`.

```bash
cd frontend
npm ci
npm run build
# copy frontend/dist/ to /opt/maestro/frontend/
```

## 5. Reverse proxy

The proxy has three jobs: serve the static build with a fallback to `index.html`, forward `/api/` with the
prefix removed (the API has no prefix), and not buffer responses, because the live log tail uses
Server-Sent Events.

### nginx

```nginx
server {
    listen 443 ssl;
    server_name maestro.example.com;

    root /opt/maestro/frontend;

    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_buffering off;
    }
}
```

### Apache

Requires `mod_proxy`, `mod_proxy_http` and `mod_ssl`.

```apache
<VirtualHost *:443>
    ServerName maestro.example.com
    DocumentRoot /opt/maestro/frontend

    <Directory /opt/maestro/frontend/>
        Options -Indexes
        AllowOverride None
        Require all granted
        FallbackResource /index.html
    </Directory>

    ProxyPreserveHost On
    ProxyPass        /api/ http://127.0.0.1:8000/ flushpackets=on
    ProxyPassReverse /api/ http://127.0.0.1:8000/
</VirtualHost>
```

## 6. Agent

Build the binary for the target platform and copy it to each monitored server:

```bash
cd agent
GOOS=linux GOARCH=amd64 go build -ldflags "-X github.com/yuriPeixoto/maestro/agent/internal/heartbeat.Version=$(cat ../VERSION)" -o maestro-agent ./cmd/agent
```

Configure it in `/etc/maestro/agent.yaml`, starting from
[`agent.yaml.example`](../agent/configs/agent.yaml.example). Environment variables override the YAML; see the
[agent README](../agent/README.md).

- `server_id` must be unique per server.
- Log files that do not exist are skipped silently. Check the paths: Apache hosts need `/var/log/apache2/*`,
  and hosts without rsyslog have no `auth.log`, which leaves the Security view without SSH data.
- The agent only reads, but it needs permission on the log files, so it usually runs as root.
- The inventory and the package scan call `apache2`, `dpkg-query` and similar tools by name, so keep `sbin`
  directories in the service `PATH`.
- The OS package scan only runs on Debian.
- Database pool monitoring is opt-in, under `db_monitor`, with a read-only monitoring user per database.

## 7. Process manager

Keep the API, the worker and the agent running with whatever the host already uses.

### systemd

```ini
# /etc/systemd/system/maestro-api.service
[Unit]
Description=Maestro API
After=network.target

[Service]
User=maestro
WorkingDirectory=/opt/maestro/api
ExecStart=/opt/maestro/api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/maestro-worker.service
[Unit]
Description=Maestro worker
After=network.target

[Service]
User=maestro
WorkingDirectory=/opt/maestro/api
ExecStart=/opt/maestro/api/.venv/bin/python -m app.worker
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/maestro-agent.service
[Unit]
Description=Maestro Agent
After=network.target

[Service]
ExecStart=/opt/maestro/agent/maestro-agent --config /etc/maestro/agent.yaml
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### supervisor

```ini
[program:maestro-api]
command=/opt/maestro/api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
directory=/opt/maestro/api
user=maestro
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true

[program:maestro-worker]
command=/opt/maestro/api/.venv/bin/python -m app.worker
directory=/opt/maestro/api
user=maestro
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true

[program:maestro-agent]
command=/opt/maestro/agent/maestro-agent --config /etc/maestro/agent.yaml
environment=PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
user=root
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stopwaitsecs=15
```

`stopwaitsecs` gives the agent time to flush its buffer on shutdown.

## 8. Updating

1. Apply any new file in `migrations/`, as `default`, in numeric order. Coming from a version without
   `metrics_hourly`, run 013 (backfill) right after 012, before the raw rows it copies expire.
   Apply the new Alembic revisions to Postgres as its owner (section 1).
   Coming from 0.1.0, where accounts lived in SQLite: set up Postgres (section 1), add `MAESTRO_DATABASE_URL`
   and copy the accounts with `.venv/bin/python -m app.import_sqlite data/maestro_auth.db`. It copies password
   hashes, the pending password changes and the release seen; it skips accounts already in Postgres, so it can run
   again, and it only reads the SQLite file, which stays as the way back.
   Then, with the old worker stopped, copy the alert configuration and state with
   `.venv/bin/python -m app.import_alerting`. It reads the active rules and channels from ClickHouse, and from
   Redis where each alert stands, the legacy per-server webhook and the servers already given default rules. It
   never writes to either, skips rows already in Postgres (so it can run again) and ends by looking every source
   row up in Postgres: it prints a count per table and exits with status 1 if anything is missing. The old
   ClickHouse tables and Redis keys stay as the way back; drop them once the new version has run for a while.
2. Replace the API source and run `uv sync --locked --no-dev`. Coming from a version with
   `requirements.txt`, uv takes over the existing `.venv`.
3. Replace the frontend build.
4. Replace the agent binary on each server (and the watchdog binary, if you run one).
5. Restart `maestro-api`, `maestro-worker` and `maestro-agent`. Coming from a version without the worker,
   add its service first (section 7): the API no longer runs the background tasks.

## Verifying

From the server:

```bash
curl -s http://127.0.0.1:8000/health
```

`/health` needs no login. It answers 200 with `"status": "healthy"` only when Redis and ClickHouse respond,
the worker published its report in the last 45 seconds, and every watched task (the three stream consumers
and the alert evaluator) finished a cycle recently; otherwise 503 with `"unhealthy"`. The `tasks` list starts
with `worker` and then shows each background task as `ok`, `starting`, `stale`
(alive but not completing cycles, such as consumers whose inserts keep failing) or `down`, with its restart
count. A task that crashes is restarted with a growing pause. Stream messages are acked only after they are
written, so a ClickHouse outage delays data instead of losing it.

In ClickHouse, as `default`, confirm that data is arriving and that the API connects as `maestro_app`:

```sql
SELECT server_id, max(timestamp) FROM maestro.metrics GROUP BY server_id;

SELECT user, query_kind, elapsed, query
FROM system.processes
WHERE user = 'maestro_app';
```

Connections to ClickHouse from a workstation should go through an SSH tunnel instead of exposing port 8123:

```bash
ssh -L 8123:localhost:8123 -N user@your-server
```
