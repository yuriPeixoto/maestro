# Watchdog

The Maestro API sends alerts about the servers it watches, but it cannot send one about itself: if its host
goes down, nobody is told. The watchdog is a small binary that runs on **another** host, polls health URLs
and posts on Telegram when one stops answering, again while it stays down, and when it comes back.

It has no dependencies (a static Go binary), keeps its state in memory and needs only outbound HTTPS to the
watched URLs and to `api.telegram.org`.

## What counts as down

A target is healthy when it answers any 2xx within `WATCHDOG_TIMEOUT`. Anything else is a failure:
timeout, refused connection, unknown host, TLS error or a non-2xx status. The alert goes out after
`WATCHDOG_FAILURES` failures in a row, so a single slow answer does not page anyone.

Point it at the Maestro `/health` endpoint (through the proxy: `https://maestro.example.com/api/health`).
That endpoint answers 503 when a consumer or the alert evaluator stopped working or Redis or ClickHouse is
unreachable, and the watchdog repeats what failed:

```
🔴 Vigia: Maestro não responde (HTTP 503 (clickhouse: down, alert-evaluator: stale))
```

Any other service with a health URL can be a target too.

## Build

```bash
cd agent
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "-s -w" -o maestro-watchdog ./cmd/watchdog
```

## Configure

All settings come from the environment, usually an `EnvironmentFile` (start from
[`watchdog.env.example`](../agent/configs/watchdog.env.example)):

| Variable | Default | Meaning |
|----------|---------|---------|
| `WATCHDOG_TARGETS` | required | `name=url` pairs separated by commas |
| `TELEGRAM_BOT_TOKEN` | required | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | required | Chat that receives the messages |
| `WATCHDOG_INTERVAL` | `1m` | Time between polls (Go duration) |
| `WATCHDOG_TIMEOUT` | `10s` | Per request |
| `WATCHDOG_FAILURES` | `3` | Failures in a row before alerting |
| `WATCHDOG_REMIND` | `1h` | Repeat the alert while down; `0` never repeats |
| `WATCHDOG_LANGUAGE` | `pt-BR` | `pt-BR` or `en` |
| `WATCHDOG_ANNOUNCE` | `true` | Post a message on start, which also proves the token and chat work |

The file holds the bot token: make it readable by root only (`chmod 600`).

## Run

With systemd, using [`maestro-watchdog.service`](../agent/configs/maestro-watchdog.service):

```bash
install -m 755 maestro-watchdog /usr/local/bin/maestro-watchdog
install -m 600 watchdog.env /etc/maestro/watchdog.env
cp maestro-watchdog.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now maestro-watchdog
journalctl -u maestro-watchdog -f
```

The unit runs as a dynamic unprivileged user. A message that Telegram did not accept is retried on the next
poll, and the error is logged without the token.
