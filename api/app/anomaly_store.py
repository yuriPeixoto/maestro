"""Reads and writes of the seasonal anomaly detection: per-minute scores and episodes.

Scores go to `anomaly_scores` as one row per metric per minute. They are the
deviation from the seasonal baseline mapped to [0, 1], so the threshold lands on
0.5 and twice the threshold on 1.0: the chart and the ML alert mode keep reading
"0.5 = anomalous" as they did with the old model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from app.ml.seasonal import Z_THRESHOLD, Deviation

SCORE_MODEL_VERSION = "seasonal"
ANOMALOUS_SCORE = 0.5

_SCORE_COLUMNS = ["server_id", "metric_name", "timestamp", "score", "model_version"]
_EPISODE_COLUMNS = ["server_id", "started_at", "ended_at", "is_open", "metrics", "peak_z", "details", "updated_at"]


def to_score(z: pd.DataFrame | float):
    """|z| on a [0, 1] scale where the threshold is 0.5."""
    return np.clip(np.abs(z) / (2 * Z_THRESHOLD), 0.0, 1.0)


async def insert_scores(client, server_id: str, zscores: pd.DataFrame) -> int:
    """One row per metric per minute with a value; returns the number of rows."""
    scores = to_score(zscores)
    rows = [
        [server_id, metric, minute.to_pydatetime(), float(score), SCORE_MODEL_VERSION]
        for minute, row in scores.iterrows()
        for metric, score in row.items()
        if not np.isnan(score)
    ]
    if rows:
        await client.insert("anomaly_scores", data=rows, column_names=_SCORE_COLUMNS)
    return len(rows)


async def recent_flags(client, server_id: str, since: datetime) -> pd.Series:
    """Per minute since `since`: whether any metric scored as anomalous."""
    result = await client.query(
        "SELECT toStartOfMinute(timestamp) AS minute, max(score) >= {anomalous:Float64}"
        " FROM anomaly_scores FINAL"
        " WHERE server_id = {server_id:String}"
        "   AND model_version = {model:String}"
        "   AND timestamp >= {since:DateTime}"
        " GROUP BY minute ORDER BY minute",
        parameters={"server_id": server_id, "model": SCORE_MODEL_VERSION, "since": since,
                    "anomalous": ANOMALOUS_SCORE},
    )
    if not result.result_rows:
        return pd.Series(dtype=bool)
    index = pd.to_datetime([r[0] for r in result.result_rows], utc=True)
    return pd.Series([bool(r[1]) for r in result.result_rows], index=index)


@dataclass(frozen=True)
class EpisodeRecord:
    server_id: str
    started_at: datetime
    ended_at: datetime
    is_open: bool
    deviations: list[dict]

    @property
    def metrics(self) -> list[str]:
        return [d["metric"] for d in self.deviations]


def deviation_dict(deviation: Deviation) -> dict:
    return {
        "metric": deviation.metric,
        "value": deviation.value,
        "z": round(deviation.z, 1),
        "normal_low": deviation.normal_low,
        "normal_high": deviation.normal_high,
        "peak_at": deviation.peak_at.isoformat(),
    }


async def upsert_episodes(client, records: list[EpisodeRecord], now: datetime) -> None:
    if not records:
        return
    rows = [
        [r.server_id, r.started_at, r.ended_at, int(r.is_open), r.metrics,
         max((d["z"] for d in r.deviations), key=abs, default=0.0), json.dumps(r.deviations), now]
        for r in records
    ]
    await client.insert("anomaly_episodes", data=rows, column_names=_EPISODE_COLUMNS)


async def list_episodes(client, server_id: str, since: datetime) -> list[EpisodeRecord]:
    """Episodes still running after `since`, newest first."""
    result = await client.query(
        "SELECT server_id, started_at, ended_at, is_open, details"
        " FROM anomaly_episodes FINAL"
        " WHERE server_id = {server_id:String} AND ended_at >= {since:DateTime}"
        " ORDER BY started_at DESC",
        parameters={"server_id": server_id, "since": since},
    )
    return [
        EpisodeRecord(r[0], r[1], r[2], bool(r[3]), json.loads(r[4]) if r[4] else [])
        for r in result.result_rows
    ]
