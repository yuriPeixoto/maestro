#!/bin/sh
# Creates the Maestro streams and the ingest process's durable consumers (ADR-015) from the JSON
# files next to this script, skipping the ones that already exist. It never edits or deletes one:
# compare with `nats stream info` / `nats consumer info` and change it by hand.
#
# Consumer files are named <STREAM>.<consumer>.json.
#
# Usage: create-streams.sh [STREAMS_DIR] [CONSUMERS_DIR]
# Connection settings come from the nats CLI's environment: NATS_URL, NATS_NKEY (the operator's
# seed file) and NATS_CA (Maestro's CA certificate, when the server uses TLS).
set -eu

here=$(dirname "$0")
streams_dir=${1:-$here/streams}
consumers_dir=${2:-$here/consumers}

for config in "$streams_dir"/*.json; do
  name=$(basename "$config" .json)
  if nats stream info "$name" >/dev/null 2>&1; then
    echo "exists:  stream $name"
    continue
  fi
  nats stream add "$name" --config "$config" >/dev/null
  echo "created: stream $name"
done

for config in "$consumers_dir"/*.json; do
  file=$(basename "$config" .json)
  stream=${file%%.*}
  name=${file#*.}
  if nats consumer info "$stream" "$name" >/dev/null 2>&1; then
    echo "exists:  consumer $stream/$name"
    continue
  fi
  nats consumer add "$stream" "$name" --config "$config" >/dev/null
  echo "created: consumer $stream/$name"
done
