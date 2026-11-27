#!/bin/sh
# Checks the permissions of Maestro's own NATS users (ADR-015) against a NATS server with the
# streams and consumers in place: maestro-worker reads the ingest consumers and the last
# heartbeats, maestro-api only the heartbeats, and neither publishes data, manages streams or
# consumers, or reads another stream.
#
# Usage: check-maestro-users.sh WORKER_SEED_FILE API_SEED_FILE
# Connection: NATS_URL, and NATS_CA when the server uses TLS (the nats CLI's environment).
# Asking a consumer for a message may deliver one without acking it: it is redelivered after the
# consumer's ack wait, and the ingest process drops it if it was already written.
set -u

[ $# -eq 2 ] || { echo "usage: $0 WORKER_SEED_FILE API_SEED_FILE" >&2; exit 64; }
worker_seed=$1
api_seed=$2
failures=0

as_user() {
  user=$1
  seed=$2
  shift 2
  nats --nkey "$seed" --inbox-prefix "_INBOX_$user" --timeout 3s "$@"
}
as_worker() { as_user maestro-worker "$worker_seed" "$@"; }
as_api() { as_user maestro-api "$api_seed" "$@"; }
listen_as_worker() {
  timeout 3 nats --nkey "$worker_seed" --inbox-prefix "_INBOX_maestro-worker" sub "$1" --count 1
}

outcome() {
  status=$1
  output=$2
  case $output in
    *"Permissions Violation"* | *"permissions violation"*) echo refused; return ;;
  esac
  case $status in
    0 | 124 | 143) echo allowed ;;   # 124/143: `timeout` stopped a subscription that was listening
    *)
      # JetStream answering "no messages" or "not found" still means the request got through.
      case $output in
        *"No Messages"* | *"no message found"* | *"10037"* | *"404"*) echo allowed ;;
        *) echo error ;;
      esac
      ;;
  esac
}

expect() {
  wanted=$1
  label=$2
  shift 2
  output=$("$@" 2>&1)
  got=$(outcome $? "$output")
  if [ "$got" = "$wanted" ]; then
    echo "ok    $label: $got"
    return
  fi
  echo "FAIL  $label: $got, expected $wanted"
  echo "$output" | sed 's/^/      /'
  failures=$((failures + 1))
}

next_request='{"batch":1,"no_wait":true}'
last_heartbeat='{"last_by_subj":"maestro.ingest.nobody.heartbeat"}'

for consumer in MAESTRO_METRICS.maestro-ingest-metrics MAESTRO_LOGS.maestro-ingest-logs \
                MAESTRO_EVENTS.maestro-ingest-events; do
  stream=${consumer%%.*}
  name=${consumer#*.}
  expect allowed "worker: next message of $stream/$name" \
    as_worker req "\$JS.API.CONSUMER.MSG.NEXT.$stream.$name" "$next_request"
  expect refused "api: next message of $stream/$name" \
    as_api req "\$JS.API.CONSUMER.MSG.NEXT.$stream.$name" "$next_request"
done

expect allowed "worker: heartbeat stream info" as_worker req '$JS.API.STREAM.INFO.MAESTRO_HEARTBEAT' ''
expect allowed "worker: last heartbeat of a server" \
  as_worker req '$JS.API.DIRECT.GET.MAESTRO_HEARTBEAT.maestro.ingest.nobody.heartbeat' ''
expect allowed "api: heartbeat stream info" as_api req '$JS.API.STREAM.INFO.MAESTRO_HEARTBEAT' ''
expect allowed "api: last heartbeat of a server" \
  as_api req '$JS.API.DIRECT.GET.MAESTRO_HEARTBEAT.maestro.ingest.nobody.heartbeat' ''

expect refused "worker: publish maestro.ingest.nobody.metrics" \
  as_worker pub --jetstream maestro.ingest.nobody.metrics '{}'
expect refused "worker: subscribe maestro.ingest.>" listen_as_worker 'maestro.ingest.>'
expect refused "worker: publish maestro.cmd.nobody" as_worker pub maestro.cmd.nobody '{}'
expect refused "worker: list streams" as_worker stream ls
expect refused "worker: create a consumer" \
  as_worker req '$JS.API.CONSUMER.CREATE.MAESTRO_METRICS.rogue' '{"stream_name":"MAESTRO_METRICS"}'
expect refused "worker: direct get on MAESTRO_METRICS" \
  as_worker req '$JS.API.DIRECT.GET.MAESTRO_METRICS' "$last_heartbeat"
expect refused "worker: another consumer of MAESTRO_METRICS" \
  as_worker req '$JS.API.CONSUMER.MSG.NEXT.MAESTRO_METRICS.rogue' "$next_request"
expect refused "api: publish maestro.ingest.nobody.metrics" \
  as_api pub --jetstream maestro.ingest.nobody.metrics '{}'
expect refused "api: list streams" as_api stream ls

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed for Maestro's users"
  exit 1
fi
echo "all checks passed for maestro-worker and maestro-api"
