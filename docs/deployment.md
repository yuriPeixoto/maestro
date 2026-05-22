# Maestro — Deployment Guide

## ClickHouse: least-privilege user setup

The Maestro API must connect to ClickHouse as `maestro_app`, not as `default`.
The `default` user has full admin privileges — using it for application traffic is equivalent to running the app as root.

### 1. Create the user on the server

Connect to ClickHouse as `default` (via `clickhouse-client` or DataGrip) and run:

```sql
-- Create the application user
CREATE USER IF NOT EXISTS maestro_app
    IDENTIFIED WITH sha256_password BY 'CHANGE_ME_USE_A_STRONG_PASSWORD';

-- Grant the minimum required privileges
GRANT SELECT, INSERT ON maestro.* TO maestro_app;

-- Confirm (should list only SELECT and INSERT on maestro.*)
SHOW GRANTS FOR maestro_app;
```

> **The `default` user must remain for DBA and migration tasks.**
> The deploy pipeline (`deploy.yml`) runs ClickHouse migrations using `default` — this is intentional.
> Do not revoke `default` privileges on the server.

### 2. Set the password in the API `.env`

On the server, edit `/opt/maestro/api/.env`:

```env
MAESTRO_CLICKHOUSE_USER=maestro_app
MAESTRO_CLICKHOUSE_PASSWORD=CHANGE_ME_USE_A_STRONG_PASSWORD
```

Restart the API after changing:

```bash
sudo systemctl restart maestro-api
```

### 3. Verify

Confirm the API is connecting as `maestro_app`:

```bash
journalctl -u maestro-api -n 20 | grep clickhouse
# Should NOT show any auth errors
```

From ClickHouse (as `default`), confirm the session:

```sql
SELECT user, query_kind, elapsed, query
FROM system.processes
WHERE user = 'maestro_app';
```

---

## DataGrip — configuring the maestro_app connection

After creating `maestro_app`, update (or add) the ClickHouse data source in **both environments**.

> Keep the existing `default` connection for DBA tasks (migrations, schema inspection, manual fixes).
> Create a separate `maestro_app` data source for application-level queries and day-to-day work.

### Office (desktop)

1. Open DataGrip → **Database** panel → **+** → **Data Source** → **ClickHouse**
2. Fill in:
   - **Name:** `Maestro — maestro_app (office)`
   - **Host:** `153.75.226.75` (or `localhost` if connecting via SSH tunnel)
   - **Port:** `8123`
   - **Database:** `maestro`
   - **User:** `maestro_app`
   - **Password:** _(the password set in step 1)_
3. Click **Test Connection** — should succeed
4. Click **OK**

> If connecting remotely (not via tunnel), ensure port 8123 is accessible.
> For on-premise, prefer an SSH tunnel: `ssh -L 8123:localhost:8123 user@153.75.226.75`

### Home office

Same steps as above. If using an SSH tunnel (recommended):

1. In DataGrip, go to the data source → **SSH/SSL** tab
2. Enable **Use SSH tunnel**
3. Fill in the SSH host, port (22), and your credentials
4. DataGrip will tunnel automatically — use `localhost:8123` as the ClickHouse address

Alternatively, set up the tunnel manually before opening DataGrip:

```bash
ssh -L 8123:localhost:8123 -N user@153.75.226.75
```

Then connect DataGrip to `localhost:8123` as `maestro_app`.

---

## Agent: YAML config file

The agent binary reads `/etc/maestro/agent.yaml` by default.
This file **does not exist** on the server — the agent currently runs via environment variables set in the systemd service.

Create it only when you need to customise values that have no env var equivalent
(sampling intervals, log watcher paths, shutdown timeout):

```bash
sudo mkdir -p /etc/maestro
sudo cp /opt/maestro/agent/configs/agent.yaml.example /etc/maestro/agent.yaml
sudo nano /etc/maestro/agent.yaml
# Adjust: server_id, redis.password (if set), and any intervals
sudo systemctl restart maestro-agent
```

> Environment variables always override YAML values — existing env vars in the
> systemd service file take precedence automatically.

---

## Systemd services

| Service | Binary / entrypoint | Managed by |
|---------|---------------------|------------|
| `maestro-agent` | `/opt/maestro/agent/maestro-agent` | deploy.yml |
| `maestro-api` | `uvicorn app.main:app` in `/opt/maestro/api/` | deploy.yml |

Check status:

```bash
sudo systemctl status maestro-agent maestro-api
journalctl -u maestro-agent -f
journalctl -u maestro-api -f
```

---

## Deploy pipeline notes

The GitHub Actions workflow (`deploy.yml`) runs on every push to `main`:

1. Builds the Go agent binary
2. Builds the React frontend
3. Deploys agent binary to `/opt/maestro/agent/`
4. Syncs API source to `/opt/maestro/api/` and reinstalls Python deps
5. Runs all ClickHouse migrations using the `default` user ← intentional, app user has no DDL privileges
6. Deploys frontend build to `/opt/maestro/frontend/`
7. Restarts `maestro-api` and `maestro-agent`
