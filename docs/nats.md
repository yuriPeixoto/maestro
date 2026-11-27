# NATS: Maestro's transport

Maestro is moving its ingestion from Redis Streams to NATS JetStream (ADR-015). The agent publishes to it
with `transport: nats` or `both` (see [Agents](#agents)); the worker consumes it from 0.4.0. This page
installs the server and the credentials.

- One `nats-server` with JetStream, next to the alerting service (on a host other than the API's, so that
  alerts survive the loss of the API host).
- Clients connect over TLS on 4222. Monitoring listens on `127.0.0.1:8222`.
- Each monitored server has its own NKey. It may publish `maestro.ingest.<server>.>`, hear
  `maestro.cmd.<server>`, and answer the commands it receives. Nothing else.

Files in `deploy/nats/`:

| File | What it is |
|------|------------|
| `nats-server.conf.example` | Server configuration (TLS, JetStream limits, `include users.conf`) |
| `render-users.sh` | Writes `users.conf` from public keys: the operator plus one user per server |
| `streams/*.json` | The four streams: `MAESTRO_METRICS`, `MAESTRO_LOGS`, `MAESTRO_EVENTS`, `MAESTRO_HEARTBEAT` |
| `create-streams.sh` | Creates the streams that do not exist yet (never edits one) |
| `check-permissions.sh` | Checks, from a monitored server, that its credential reaches only its own subjects |
| `maestro-nats.service` | systemd unit, runs as the `maestro` user |

## Local development

```bash
docker compose up -d nats-streams        # nats-keys -> nats -> nats-streams
docker compose run --rm nats-check       # permission check for the fake servers dev-a and dev-b
```

`nats-keys` generates fresh NKeys into the `nats-dev` volume on first start (operator `admin`, and `dev-a`,
`dev-b`). The development server has the same accounts, permissions and streams as production, without TLS,
on host port `14222` (`NATS_HOST_PORT`). `docker compose down -v` drops the keys and the stored messages.

## Production

Requirements on the NATS host: a `maestro` system user, `/var/lib/maestro` owned by it, and a TLS certificate
for the host's address signed by your own CA (`/etc/maestro/tls/nats.crt` and `nats.key`, the key readable by
the `maestro` group). Every agent host needs the CA certificate, to verify the server.

### 1. Binaries

Download `nats-server` (and the `nats` CLI, for the operator) from the official releases and check them
against the release's `SHA256SUMS` before copying them to the host:

```bash
sha256sum -c --ignore-missing SHA256SUMS
install -m 755 nats-server /usr/local/bin/nats-server
install -m 755 nats /usr/local/bin/nats
```

An archive built or unpacked on Windows keeps mode 777: always install with an explicit mode, and extract with
`tar --no-same-permissions`.

### 2. Keys

One NKey per server, plus one for the operator. Generate them where `nk` is available (`go install
github.com/nats-io/nkeys/nk@latest`, or the `natsio/nats-box` image):

```bash
nk -gen user > admin.nk
nk -gen user > web-1.nk
nk -inkey web-1.nk -pubout        # the public key, for users.conf
```

The `.nk` file is the **seed**: it is the credential. Keep each one only on its own host (mode `0600`) and in
your password manager. Never commit one; `*.nk` is in `.gitignore`. The public keys are not secret.

### 3. Configuration

```bash
install -d -m 750 -o root -g maestro /etc/maestro/nats
install -d -m 750 -o maestro -g maestro /var/lib/maestro/nats
install -m 640 -o root -g maestro nats-server.conf /etc/maestro/nats/nats-server.conf
sh render-users.sh "$(nk -inkey admin.nk -pubout)" "web-1=$(nk -inkey web-1.nk -pubout)" > users.conf
install -m 640 -o root -g maestro users.conf /etc/maestro/nats/users.conf
nats-server --config /etc/maestro/nats/nats-server.conf -t     # syntax check
```

The server name in `render-users.sh` is the server id its agent reports (its hostname), lowercase, with no dots.
Set `max_file_store` below the disk's free space: it is the ceiling for the whole server, and the streams'
own limits (`max_bytes`) add up to less.

### 4. Service and streams

```bash
cp maestro-nats.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now maestro-nats
curl -s 'http://127.0.0.1:8222/healthz?js-enabled-only=true'
NATS_URL=tls://<nats-host>:4222 NATS_CA=/etc/maestro/tls/ca.crt NATS_NKEY=/root/admin.nk sh create-streams.sh streams
```

Adding a server later: generate its key, render `users.conf` again with every server, install it and run
`systemctl reload maestro-nats` (connections stay up).

### 5. Checking a server's permissions

From the monitored server, with its own seed and the CA certificate:

```bash
NATS_URL=tls://<nats-host>:4222 NATS_CA=ca.crt sh check-permissions.sh web-1 web-1.nk web-2
```

Every line must read `ok`: publishing to its own subjects is allowed, the neighbour's subjects and the JetStream
API are refused with a permissions violation.

## Agents

On each monitored server, with the seed and the CA certificate in place (`/etc/maestro/nats.nk`, mode `0600`, and
`/etc/maestro/nats-ca.crt`), set in `/etc/maestro/agent.yaml`:

```yaml
server_id: web-1          # the NKey user's name in users.conf
transport: both           # redis | nats | both
nats:
  url: tls://<nats-host>:4222
  nkey_file: /etc/maestro/nats.nk
  ca_file: /etc/maestro/nats-ca.crt
  buffer:
    dir: /var/lib/maestro/agent/buffer
    max_mb: 256
```

The agent connects with the inbox prefix `_INBOX_<server_id>`, the only inbox its credential may subscribe to,
and waits for JetStream's acknowledgement of every message. Metrics, logs and events are written to the buffer
directory first and deleted only once acknowledged, so a NATS outage or an agent restart delays them instead of
losing them; past `max_mb` the oldest go first. Heartbeats are not buffered. The agent starts even when NATS is
unreachable.

Messages are JSON envelopes, published with `Nats-Msg-Id` set to `id`:

```json
{"id": "<UUIDv7>", "server_id": "web-1", "type": "metrics", "sent_at": "...", "data": []}
```

| Subject | `type` | `data` |
|---------|--------|--------|
| `maestro.ingest.<server>.metrics` | `metrics` | a batch of metrics (up to 50, or 5 s) |
| `maestro.ingest.<server>.logs` | `logs` | `{"log_file", "lines": [{"timestamp", "line"}]}`, up to 500 lines or 512 KB |
| `maestro.ingest.<server>.heartbeat` | `heartbeat` | the heartbeat (version, watched logs, inventory) |
| `maestro.ingest.<server>.events` | `agent_registered`, `agent_deregistered` | hostname, OS, tags, agent version |
| `maestro.ingest.<server>.events` | `packages` | the OS package snapshot |
| `maestro.ingest.<server>.events` | `db_connections` | `{"db_type", "connections"}` |

With `transport: both` the Redis entries carry the same id in a `msg_id` field. The subject is the identity:
a consumer takes the server from the subject and drops a message whose `server_id` disagrees.

## Streams

| Stream | Subjects | Kept for | Size cap |
|--------|----------|----------|----------|
| `MAESTRO_METRICS` | `maestro.ingest.*.metrics` | 3 days | 4 GiB |
| `MAESTRO_LOGS` | `maestro.ingest.*.logs` | 3 days | 4 GiB |
| `MAESTRO_EVENTS` | `maestro.ingest.*.events` | 7 days | 512 MiB |
| `MAESTRO_HEARTBEAT` | `maestro.ingest.*.heartbeat` | last message per server | 64 MiB |

When a stream is full the oldest messages go first. Commands (`maestro.cmd.<server>`) are request/reply and are
never stored: a command for an agent that is offline is not run when it comes back.
