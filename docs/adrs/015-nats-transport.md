# ADR-015: NATS JetStream as the Transport

**Status:** Accepted
**Date:** 2026-11-24

## Context

The agent publishes to Redis Streams on the API host (`XADD` to `maestro:metrics`, `maestro:logs`,
`maestro:heartbeat`, plus an `HSET` of the package snapshot). That ties every monitored server to the API
host's Redis, which has no authentication and listens on localhost only, so a second server cannot publish at
all, and the API host is a single point of failure for ingestion and alerting. ADR-011 moved configuration and
state to Postgres; what Redis still carries is the queue, the last heartbeat per server and the worker's health.

The plan puts the transport and the alerting service on a second host, so that alerts survive the loss of the
API host, and lets each host watch the other. The transport has to:

- accept data from several servers over the network, each with its own credential (this is also the machine
  authentication ADR-009 and #78 are waiting for);
- keep a server from publishing as another server, or reading another server's commands;
- hold data while the worker is down, within a fixed disk budget;
- carry commands back to an agent (a closed list, empty for now).

## Decision

1. **NATS with JetStream**, one `nats-server` (no cluster) next to the alerting service. Clients connect over
   TLS on 4222, verifying the server against Maestro's own CA. Monitoring (`:8222`) listens on localhost only.
   No leaf nodes, gateways or websockets.

2. **Subjects.** `<server>` is the server id the agent already reports (its hostname), written as one NATS
   token: lowercase, `[a-z0-9_-]`, no dots.

   | Subject | Who publishes | Content |
   |---------|---------------|---------|
   | `maestro.ingest.<server>.metrics` | agent | metric batches |
   | `maestro.ingest.<server>.logs` | agent | log lines |
   | `maestro.ingest.<server>.events` | agent | server events, package snapshot, registration |
   | `maestro.ingest.<server>.heartbeat` | agent | one heartbeat per interval |
   | `maestro.cmd.<server>` | Maestro | a command for that server's agent (request/reply) |

   The subject is the identity: consumers take the server id from the subject, never from the payload, and
   drop a message whose payload names another server.

3. **Streams** (file storage, `limits` retention, `discard: old`, one replica):

   | Stream | Subjects | Max age | Max bytes | Other |
   |--------|----------|---------|-----------|-------|
   | `MAESTRO_METRICS` | `maestro.ingest.*.metrics` | 3 days | 4 GiB | duplicate window 2 min |
   | `MAESTRO_LOGS` | `maestro.ingest.*.logs` | 3 days | 4 GiB | duplicate window 2 min |
   | `MAESTRO_EVENTS` | `maestro.ingest.*.events` | 7 days | 512 MiB | duplicate window 2 min |
   | `MAESTRO_HEARTBEAT` | `maestro.ingest.*.heartbeat` | 1 day | 64 MiB | one message per subject, direct get |

   The server caps JetStream at `max_file_store: 10G` and `max_memory_store: 256M`, below the streams' sum, so a
   wrong stream setting cannot fill the disk. Three days cover a weekend with the worker down; past that the
   oldest data goes first, because the newest is what alerts need. `limits` rather than `workqueue` so that a
   second reader (the alerting service reading heartbeats, a replay after a bug) needs no change.
   Messages carry `Nats-Msg-Id` (stage 13), so a retried publish inside the duplicate window is stored once.
   Commands get **no stream**: a command for an agent that is offline must not run when it comes back.
   Streams are infrastructure: defined in `deploy/nats/streams/*.json` and created by the operator with the
   `nats` CLI. No Maestro process holds stream-management permissions.

4. **Authentication: one NKey user per server**, all in one account `MAESTRO`. The server configuration holds
   only public keys; each seed lives on its own host (`0600`) and in the operator's password manager, never in
   the repository. Permissions of the user for `<server>`:

   - publish `maestro.ingest.<server>.>`;
   - subscribe `maestro.cmd.<server>` and `_INBOX_<server>.>` (its own reply inbox for JetStream acks; the
     client sets that inbox prefix);
   - replies to commands through `allow_responses` (one reply, one minute), so it can answer a command without
     being able to publish anywhere else.

   Everything else is denied, which is what "refused on the neighbour's subject" means. Maestro's own processes
   get their own users when they need them (`maestro-worker` in stage 14, `maestro-alerts` in stage 15), with
   consumer permissions on named durable consumers only. An `admin` user exists only on the NATS host, for the
   CLI.

   Considered and not chosen: mTLS client certificates mapped to users (strong, but every new server needs the
   CA key and a renewal every two years); user and password (a shared secret sits in the server config); the
   operator/JWT mode with `nsc` (multi-tenant, more moving parts than one installation needs).

5. **Where the state Redis holds today goes:**

   - **Last heartbeat per server:** the `MAESTRO_HEARTBEAT` stream keeps the last message of each subject, read
     with a direct get. It lives on the same host as the alerting service, which keeps working when the API host
     or Postgres is down. Nothing has to copy it anywhere.
   - **Worker health:** Postgres, a row per worker process written every 15 s. Its reader, the API's `/health`,
     already depends on Postgres; keeping it in NATS would make a NATS outage look like a dead worker to the
     watchdog.
   - **Package snapshot and agent registry:** from the `events` subject into Postgres (stage 14), keyed by the
     subject's server.

6. **Consumers** are durable pull consumers, explicit ack after the ClickHouse write, `max_ack_pending` bounded,
   redelivery with back-off. The ingesting process is its own process role (stage 14), so it can run on the API
   host or on the NATS host by configuration.

## Consequences

- Ingestion from any server in the network, authenticated per server: the agent's 401 at registration goes
  away (stage 13), unblocking #78.
- One more service to run and watch, on a host with a 29 GB disk: the 10 GiB cap is the budget.
- A NATS outage stops ingestion; the agent keeps data in its buffer. Today that buffer is 1000 batches in memory
  (40–80 minutes) and is lost on restart. **Stage 13 moves it to disk, capped in MB**, so a long outage of the
  NATS host becomes a delay instead of a gap.
- With the ingesting consumers on the API host, losing that host also stops ingestion from the other servers
  while their data piles up in JetStream, and the alerting service sees "no data". Running the ingesting
  consumers on the NATS host closes that gap; it is a deployment choice made possible by item 6.
- The alerting service (stage 15) takes its lease and keys every delivery with an idempotency key from day
  one, so a second evaluator later is configuration, not code.
- Redis stays until 1.0.0 for the parallel run; the agent publishes to both in 0.4.0.

## Alternatives considered

- **Keep Redis Streams and expose Redis on the network.** No ACL per stream key prefix that maps cleanly to a
  server, no TLS on the current install, shared with other applications' queues. Rejected.
- **Kafka / Redpanda.** More than an on-premise install of three servers needs. Rejected (ADR-002's reasoning).
- **HTTP ingestion to the API.** Simple, but puts the API host back in the path the move is meant to remove, and
  gives no buffer or command channel. Rejected.
