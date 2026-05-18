#!/usr/bin/env python3
"""
Maestro data seeder — for open-source contributors, testers, and local development.

Generates realistic metric data with daily patterns, weekly trends, and configurable
anomaly injection. Writes directly to ClickHouse.

NOT needed when a real Maestro agent is running — only for bootstrapping demo or dev environments.

Usage:
    python seeder.py
    python seeder.py --server-id myserver --days 14 --anomalies 10
    python seeder.py --days 7 --interval 5 --batch-size 2000

Environment variables (same as the API):
    MAESTRO_CLICKHOUSE_HOST      (default: localhost)
    MAESTRO_CLICKHOUSE_PORT      (default: 8123)
    MAESTRO_CLICKHOUSE_USER      (default: default)
    MAESTRO_CLICKHOUSE_PASSWORD  (default: "")
    MAESTRO_CLICKHOUSE_DATABASE  (default: maestro)
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import clickhouse_connect


def _ch_client() -> clickhouse_connect.driver.Client:
    return clickhouse_connect.get_client(
        host=os.getenv("MAESTRO_CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("MAESTRO_CLICKHOUSE_PORT", "8123")),
        username=os.getenv("MAESTRO_CLICKHOUSE_USER", "default"),
        password=os.getenv("MAESTRO_CLICKHOUSE_PASSWORD", ""),
        database=os.getenv("MAESTRO_CLICKHOUSE_DATABASE", "maestro"),
    )


def _business_hour_factor(ts: datetime) -> float:
    """Returns a load multiplier [0.25, 1.0] that peaks around 10:00 UTC (business hours)."""
    hour = ts.hour + ts.minute / 60
    raw = math.sin(math.pi * (hour - 7) / 12)
    return 0.25 + 0.75 * max(0.0, raw)


def _generate_rows(
    server_id: str,
    start: datetime,
    days: int,
    interval_seconds: int,
    anomaly_timestamps: list[datetime],
) -> list[tuple]:
    total_seconds = days * 86400
    rows: list[tuple] = []
    ts = start
    end = start + timedelta(days=days)

    metrics: dict[str, dict] = {
        "cpu_usage_percent":   {"base": 12.0,           "range": 65.0,          "noise": 4.0,         "drift": 0.0},
        "memory_used_bytes":   {"base": 900_000_000,     "range": 1_100_000_000, "noise": 40_000_000,  "drift": 0.25},
        "disk_used_bytes":     {"base": 18_000_000_000,  "range": 8_000_000_000, "noise": 80_000_000,  "drift": 0.40},
        "network_bytes_in":    {"base": 40_000,          "range": 480_000,       "noise": 18_000,      "drift": 0.0},
        "network_bytes_out":   {"base": 15_000,          "range": 180_000,       "noise": 7_000,       "drift": 0.0},
        "process_count":       {"base": 75.0,            "range": 35.0,          "noise": 4.0,         "drift": 0.0},
    }

    while ts < end:
        bh = _business_hour_factor(ts)
        elapsed_ratio = (ts - start).total_seconds() / total_seconds  # 0.0 → 1.0

        # Check if this timestamp is within one interval of any injected anomaly
        is_anomaly = any(
            abs((ts - a).total_seconds()) <= interval_seconds
            for a in anomaly_timestamps
        )

        for metric_name, cfg in metrics.items():
            noise = random.gauss(0, cfg["noise"])
            drift = cfg["range"] * cfg["drift"] * elapsed_ratio
            value = cfg["base"] + cfg["range"] * bh + drift + noise

            if is_anomaly:
                value *= random.uniform(2.0, 3.5)

            rows.append((server_id, metric_name, max(0.0, value), ts, {}))

        ts += timedelta(seconds=interval_seconds)

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Maestro data seeder — generates synthetic metric data for demo/dev environments."
    )
    parser.add_argument("--server-id", default="demo-server", metavar="ID",
                        help="Server identifier written into the metrics (default: demo-server)")
    parser.add_argument("--days", type=int, default=7,
                        help="Days of historical data to generate (default: 7)")
    parser.add_argument("--interval", type=int, default=15,
                        help="Seconds between data points (default: 15)")
    parser.add_argument("--anomalies", type=int, default=5,
                        help="Number of anomaly spikes to inject at random timestamps (default: 5)")
    parser.add_argument("--batch-size", type=int, default=1000,
                        help="ClickHouse insert batch size (default: 1000)")
    args = parser.parse_args()

    if args.days < 1:
        print("Error: --days must be at least 1", file=sys.stderr)
        sys.exit(1)
    if args.interval < 1:
        print("Error: --interval must be at least 1 second", file=sys.stderr)
        sys.exit(1)

    end = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    anomaly_timestamps = [
        start + timedelta(seconds=random.randint(3600, max(3601, args.days * 86400 - 3600)))
        for _ in range(args.anomalies)
    ]

    metrics_count = 6
    expected_rows = (args.days * 86400 // args.interval) * metrics_count
    print(f"Server:    {args.server_id}")
    print(f"Window:    {start.strftime('%Y-%m-%d %H:%M')} → {end.strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"Interval:  {args.interval}s   Anomalies: {args.anomalies}   Est. rows: ~{expected_rows:,}")
    print()

    rows = _generate_rows(args.server_id, start, args.days, args.interval, anomaly_timestamps)
    print(f"Generated {len(rows):,} rows.")

    try:
        client = _ch_client()
        client.ping()
    except Exception as exc:
        print(f"Error: cannot connect to ClickHouse — {exc}", file=sys.stderr)
        print("Check MAESTRO_CLICKHOUSE_* environment variables.", file=sys.stderr)
        sys.exit(1)

    columns = ["server_id", "metric_name", "value", "timestamp", "tags"]
    total = 0
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i : i + args.batch_size]
        client.insert("maestro.metrics", batch, column_names=columns)
        total += len(batch)
        pct = total * 100 // len(rows)
        print(f"  Inserting... {total:,}/{len(rows):,} ({pct}%)", end="\r", flush=True)

    print(f"\nDone. {total:,} rows written to ClickHouse table maestro.metrics.")
    if args.anomalies:
        print(f"Anomaly timestamps injected:")
        for a in sorted(anomaly_timestamps):
            print(f"  {a.strftime('%Y-%m-%d %H:%M:%S')} UTC")


if __name__ == "__main__":
    main()
