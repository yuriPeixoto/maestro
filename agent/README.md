# Maestro Agent

Lightweight Go binary that collects system metrics and ships them to Maestro over Redis Streams, NATS
JetStream (ADR-015) or both, chosen with `transport` in `agent.yaml`.

## Features

- CPU, memory, disk I/O, disk space, network, and process count collection
- Configurable sampling rates per metric type
- NATS: every message waits on disk until JetStream acknowledges it (capped in MB, survives restarts);
  Redis: a ring of 1000 batches in memory
- Real-time log tailing (syslog, auth.log, nginx, etc.)
- Runtime inventory detection (PHP, Node, Python, nginx, Apache, OpenSSH, etc.)
- Installed OS package list on Debian, reported every 6 hours for the vulnerability scan
- Opt-in connection pool monitoring for MySQL/MariaDB, PostgreSQL and ClickHouse
- Heartbeat emission for server health monitoring
- Graceful shutdown that flushes the buffers

## Building

```bash
cd agent
go build -ldflags "-X github.com/yuriPeixoto/maestro/agent/internal/heartbeat.Version=$(cat ../VERSION)" -o maestro-agent ./cmd/agent
```

## Configuration

The agent supports three configuration layers, applied in this order (later overrides earlier):

1. Built-in defaults
2. YAML config file
3. Environment variables

### YAML config file

Default path: `/etc/maestro/agent.yaml`

Override with the `--config` flag:

```bash
maestro-agent --config /path/to/agent.yaml
```

Copy `configs/agent.yaml.example` as a starting point:

```bash
cp configs/agent.yaml.example /etc/maestro/agent.yaml
```

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MAESTRO_SERVER_ID` | Unique server identifier | system hostname |
| `MAESTRO_DEBUG` | Print every message to stdout instead of sending it | `false` |
| `MAESTRO_TRANSPORT` | `redis`, `nats` or `both` | `redis` |
| `MAESTRO_NATS_URL` | NATS server (`tls://host:4222`) | _(empty)_ |
| `MAESTRO_NATS_NKEY_FILE` | This server's NKey seed | `/etc/maestro/nats.nk` |
| `MAESTRO_NATS_CA_FILE` | CA that signed the NATS certificate; empty means no TLS | _(empty)_ |
| `MAESTRO_NATS_BUFFER_DIR` | Disk buffer for NATS | `/var/lib/maestro/agent/buffer` |
| `MAESTRO_REDIS_ADDR` | Redis address | `localhost:6379` |
| `MAESTRO_REDIS_PASSWORD` | Redis password | _(empty)_ |
| `MAESTRO_REDIS_STREAM` | Redis stream key for metrics | `maestro:metrics` |
| `MAESTRO_HEARTBEAT_STREAM` | Redis stream key for heartbeats | `maestro:heartbeat` |
| `MAESTRO_HEARTBEAT_INTERVAL` | Heartbeat emission interval | `30s` |
| `MAESTRO_LOG_STREAM` | Redis stream key for log lines | `maestro:logs` |
| `MAESTRO_SHUTDOWN_TIMEOUT` | Max time to flush buffer on shutdown | `10s` |

### Config validation

The agent validates its configuration on startup and exits with a clear error message on invalid values. Example:

```
fatal: invalid configuration: server_id is required (set MAESTRO_SERVER_ID or server_id in config file)
```

## Running as a systemd service

```ini
[Unit]
Description=Maestro Agent
After=network.target

[Service]
ExecStart=/usr/local/bin/maestro-agent --config /etc/maestro/agent.yaml
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

## Graceful shutdown

On `SIGINT` or `SIGTERM`, the agent:

1. Stops accepting new metrics from collectors immediately
2. Flushes any metrics accumulated in the current batch
3. Redis: drains the ring buffer (up to `shutdown_timeout`, default 10s); what is left is lost
4. NATS: sends what it can of the disk buffer in the same time; what is left stays on disk for the next start
5. Logs the result and exits

## Transport

| `transport` | Sends to | Registration |
|-------------|----------|--------------|
| `redis` (default until 0.4.0) | Redis Streams on the API host | `POST /agents/register` (answers 401: the route needs a user token) |
| `nats` | `maestro.ingest.<server_id>.*` on NATS | `agent_registered` event, authenticated by the server's NKey |
| `both` | both, with the same message id | as `nats` |

With NATS, `server_id` must be a subject token (lowercase letters, digits, `-`, `_`) and match the NKey user
the NATS server knows; see `docs/nats.md`. Each message is a JSON envelope (`id`, `server_id`, `type`,
`sent_at`, `data`) published with `Nats-Msg-Id` set to the id, and Redis entries carry the same id in `msg_id`,
so the worker can drop repeats from either path.

## Development

```bash
# Run with debug output (no Redis or NATS required)
MAESTRO_DEBUG=true go run ./cmd/agent

# Run tests
go test ./...

# Vet
go vet ./...
```
