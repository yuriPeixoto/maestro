# Maestro Agent

Lightweight Go binary that collects system metrics and ships them to Redis Streams.

## Features

- CPU, memory, disk I/O, disk space, network, and process count collection
- Configurable sampling rates per metric type
- Local ring buffer for Redis unavailability (no data loss during outages)
- Real-time log tailing (syslog, auth.log, nginx, etc.)
- Runtime inventory detection (PHP, Node, Python, nginx, etc.)
- Heartbeat emission for server health monitoring
- Graceful shutdown with ring buffer flush

## Building

```bash
cd agent
go build -o maestro-agent ./cmd/agent
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
| `MAESTRO_DEBUG` | Print metrics to stdout instead of Redis | `false` |
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
3. Drains the ring buffer to Redis (up to `shutdown_timeout`, default 10s)
4. Logs the result and exits

Shutdown log output:

```
info [publisher]: flushing 3 buffered batch(es) before shutdown...
info [publisher]: flush complete
info: Maestro Agent stopped.
```

## Development

```bash
# Run with debug output (no Redis required)
MAESTRO_DEBUG=true go run ./cmd/agent

# Run tests
go test ./...

# Vet
go vet ./...
```
