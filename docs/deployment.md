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
| ClickHouse | Any recent version; the migrations are tested against 25.5 and later |
| Redis | Reachable from the API and from every agent; Streams support (5.0+) |
| Frontend build | Node.js 20.19+ (build only, nothing runs on the server) |
| Agent build | Go 1.27 (build only, the agent is a single binary) |
| Web server | Any reverse proxy; nginx and Apache examples below |

The API and the agents share one Redis, so an agent on another host needs network access to it. Keys and
streams use the `maestro:` prefix, which allows sharing a Redis instance with other applications.

## 1. ClickHouse

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

## 2. API

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

MAESTRO_AUTH_DB_PATH=/opt/maestro/api/data/maestro_auth.db
MAESTRO_FRONTEND_URL=https://maestro.example.com

# Name shown in the interface; leave empty to hide it
MAESTRO_CLIENT_NAME=
```

A server's state comes from default limits for CPU, memory and disk plus the alert rules firing now. CPU is
judged on its 5-minute average, so a short spike does not read as an overloaded server. To change the limits,
set `MAESTRO_HEALTH_*_PERCENT` (see `api/.env.example`).

The service user needs write access to the directory of `MAESTRO_AUTH_DB_PATH`. Anomaly detection keeps no
model files: its seasonal baseline is refitted from ClickHouse every day.

### Alerts

Every server seen for the first time with no rule gets five default rules: no heartbeat for
`MAESTRO_OFFLINE_THRESHOLD_SECONDS`, disk at the attention and critical limits, and memory and CPU (5-minute
average) at the critical limit. The limits are the `MAESTRO_HEALTH_*_PERCENT` ones, so a rule fires when the
dashboard changes colour. Rules deleted later are not recreated.

Alerts go to the server's notification channels, set on the Alerts screen: a channel takes every rule of its
server or a single one. Every delivery, including the "send test" button, lands in the delivery history.

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

- **API** (`uvicorn app.main:app`): HTTP only. Keep one instance: the user store is a local SQLite file.
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

Create the first accounts from a JSON file. They must change their password on first login:

```bash
cat > users.json <<'EOF'
[{"username": "alice", "email": "alice@example.com"}]
EOF

.venv/bin/python -m app.seed_users users.json
```

Leave the temporary password empty to get one random password per account. The command skips accounts that
already exist, so it is safe to run again. Delete `users.json` afterwards.

A login is blocked for 15 minutes after 5 failed attempts. The interface has no "forgot password" link: the API
route sends an email and needs the `MAESTRO_SMTP_*` settings. Reset the password on the host until #99 ships.

## 3. Frontend

Build it anywhere and copy the result to the server. The frontend calls the API under `/api/`.

```bash
cd frontend
npm ci
npm run build
# copy frontend/dist/ to /opt/maestro/frontend/
```

## 4. Reverse proxy

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

## 5. Agent

Build the binary for the target platform and copy it to each monitored server:

```bash
cd agent
GOOS=linux GOARCH=amd64 go build -o maestro-agent ./cmd/agent
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

## 6. Process manager

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

## 7. Updating

1. Apply any new file in `migrations/`, as `default`, in numeric order. Coming from a version without
   `metrics_hourly`, run 013 (backfill) right after 012, before the raw rows it copies expire.
2. Replace the API source and run `uv sync --locked --no-dev`. Coming from a version with
   `requirements.txt`, uv takes over the existing `.venv`.
3. Replace the frontend build.
4. Replace the agent binary on each server (and the watchdog binary, if you run one).
5. Restart `maestro-api`, `maestro-worker` and `maestro-agent`. Coming from a version without the worker,
   add its service first (section 6): the API no longer runs the background tasks.

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
