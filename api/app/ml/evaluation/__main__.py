"""Evaluation bench for Maestro's anomaly detection.

    python -m app.ml.evaluation export --server web-1 --days 28 --out web-1.csv.gz
    python -m app.ml.evaluation run --data web-1.csv.gz --train-days 14 --out report.md

`export` reads per-minute metrics from the ClickHouse configured in .env, with
read-only queries; `run` works offline on the exported file, so experiments never
touch the database again.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.ml.evaluation import forecast_bench
from app.ml.evaluation.bench import render_report, run_bench
from app.ml.frames import ANOMALY_METRICS, CAPACITY_METRICS, fetch_minute_frame

_READ_ONLY = {"readonly": "1"}
_ALL_METRICS = tuple(dict.fromkeys(ANOMALY_METRICS + CAPACITY_METRICS))


async def _export(server_id: str, days: int, out: Path) -> None:
    from app.clickhouse import create_client

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    client = await create_client()
    try:
        frame = await fetch_minute_frame(client, server_id, start, end, _ALL_METRICS, settings=_READ_ONLY)
    finally:
        await client.close()
    frame.to_csv(out)
    print(f"{len(frame)} minutes, {frame.notna().any(axis=1).mean():.0%} with data -> {out}")


def _load(path: Path, metrics: tuple[str, ...] = ANOMALY_METRICS) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col="minute")
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[[m for m in metrics if m in frame.columns]]
    # Drop the empty lead-in before the server's first sample.
    first = frame.notna().any(axis=1).idxmax()
    return frame.loc[first.floor("D"):]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ml.evaluation", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser("export", help="read per-minute metrics from ClickHouse into a CSV")
    export.add_argument("--server", required=True)
    export.add_argument("--days", type=int, default=28)
    export.add_argument("--out", type=Path, required=True)

    run = commands.add_parser("run", help="compare the detectors on an exported CSV")
    run.add_argument("--data", type=Path, required=True)
    run.add_argument("--train-days", type=int, default=14)
    run.add_argument("--label", default="")
    run.add_argument("--seed", type=int, default=7)
    run.add_argument("--out", type=Path, help="write the Markdown report here instead of stdout")

    forecast = commands.add_parser("forecast", help="backtest the capacity forecast models on an exported CSV")
    forecast.add_argument("--data", type=Path, required=True)
    forecast.add_argument("--label", default="")
    forecast.add_argument("--out", type=Path)

    args = parser.parse_args(argv)
    if args.command == "export":
        asyncio.run(_export(args.server, args.days, args.out))
        return 0

    label = args.label or args.data.stem
    if args.command == "forecast":
        report = forecast_bench.render(_load(args.data, _ALL_METRICS), list(CAPACITY_METRICS), label)
    else:
        report = render_report(run_bench(_load(args.data), args.train_days, seed=args.seed), label)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"report -> {args.out}")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
