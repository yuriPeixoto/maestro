#!/bin/sh
# Checks the permission layout of ADR-015 against a NATS server: a server's credential publishes to
# its own subjects and hears its own commands, and is refused on its neighbour's.
#
# Usage: check.sh OWN_SERVER OWN_SEED_FILE NEIGHBOUR_SERVER
# Connection: NATS_URL, and NATS_CA when the server uses TLS (the nats CLI's environment).
# A refusal only counts when the server reported a permissions violation; any other error fails
# the check. Exit status 0 when every check behaved as expected.
set -u

[ $# -eq 3 ] || { echo "usage: $0 OWN_SERVER OWN_SEED_FILE NEIGHBOUR_SERVER" >&2; exit 64; }
own=$1
seed=$2
neighbour=$3
failures=0
# A subscription that is allowed waits for messages; it is stopped after this many seconds.
listen_seconds=3

as_own() { nats --nkey "$seed" --inbox-prefix "_INBOX_$own" --timeout 3s "$@"; }
listen_as_own() { timeout "$listen_seconds" nats --nkey "$seed" --inbox-prefix "_INBOX_$own" sub "$1" --count 1; }

outcome() {
  status=$1
  output=$2
  case $output in
    *"Permissions Violation"*) echo refused; return ;;
  esac
  case $status in
    0 | 124 | 143) echo allowed ;;   # 124/143: `timeout` stopped a subscription that was listening
    *) echo error ;;
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

payload="{\"check\":\"$(date +%s)\"}"

expect allowed "publish maestro.ingest.$own.events (JetStream ack)" \
  as_own pub --jetstream "maestro.ingest.$own.events" "$payload"
expect allowed "subscribe maestro.cmd.$own" \
  listen_as_own "maestro.cmd.$own"
expect refused "publish maestro.ingest.$neighbour.events" \
  as_own pub --jetstream "maestro.ingest.$neighbour.events" "$payload"
expect refused "publish maestro.cmd.$neighbour" \
  as_own pub "maestro.cmd.$neighbour" "{}"
expect refused "subscribe maestro.cmd.$neighbour" \
  listen_as_own "maestro.cmd.$neighbour"
expect refused "subscribe maestro.ingest.$neighbour.>" \
  listen_as_own "maestro.ingest.$neighbour.>"
expect refused "JetStream API (list streams)" \
  as_own stream ls

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed for $own"
  exit 1
fi
echo "all checks passed for $own"
