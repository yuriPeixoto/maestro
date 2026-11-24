#!/bin/sh
# Creates the Maestro streams (ADR-015) from the JSON files next to this script, skipping the ones
# that already exist. It never edits or deletes a stream: compare with `nats stream info` and change
# one by hand.
#
# Connection settings come from the nats CLI's environment: NATS_URL, NATS_NKEY (the operator's
# seed file) and NATS_CA (Maestro's CA certificate, when the server uses TLS).
set -eu

streams_dir=${1:-$(dirname "$0")/streams}

for config in "$streams_dir"/*.json; do
  name=$(basename "$config" .json)
  if nats stream info "$name" >/dev/null 2>&1; then
    echo "exists:  $name"
    continue
  fi
  nats stream add "$name" --config "$config" >/dev/null
  echo "created: $name"
done
