"""Seasonal anomaly detection, once a minute (worker task).

For every server with a heartbeat:
1. once a day, refit the seasonal baseline on the last 28 days of per-minute data
   (in the ML child process);
2. every minute, score the minutes that settled since the last run and store one
   score per metric per minute;
3. rebuild the recent episodes from the stored scores and rewrite the ones still
   running or just ended, with what was unusual and what normal would have been.

Scores are stored once and never recomputed, so an episode keeps its start minute
even when the baseline is refitted in the middle of it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
import redis.asyncio as aioredis

from app.anomaly_store import EpisodeRecord, deviation_dict, insert_scores, recent_flags, upsert_episodes
from app.config import settings
from app.ml.episodes import MAX_GAP_MINUTES, find_episodes
from app.ml.frames import fetch_minute_frame
from app.ml.pool import run_in_ml_process
from app.ml.seasonal import SeasonalBaseline

logger = logging.getLogger(__name__)

CYCLE_SECONDS = 60
TRAINING_DAYS = 28
REFIT_EVERY = timedelta(hours=24)
# Judge nothing before a day of history: one day already gives every hour of the day.
MIN_TRAINING_MINUTES = 1440
# Samples of the last minutes may still be on their way through the stream.
SETTLE_MINUTES = 2
# How far back episodes are rebuilt; longer ones are rare and keep their last version.
EPISODE_WINDOW = timedelta(hours=12)
# Episodes that ended this recently are still rewritten, so their end is final.
REWRITE_RECENT = timedelta(minutes=15)

_MINUTE = timedelta(minutes=1)


@dataclass
class _ServerState:
    baseline: SeasonalBaseline | None = None
    fitted_at: datetime | None = None
    scored_until: datetime | None = None


class AnomalyJob:
    def __init__(self, client, redis, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._client = client
        self._redis = redis
        self._clock = clock
        self._states: dict[str, _ServerState] = {}

    async def run_once(self) -> None:
        server_ids: list[str] = await self._redis.hkeys(settings.heartbeat_state_key)
        for server_id in server_ids:
            try:
                await self.process(server_id)
            except Exception as exc:
                logger.error("anomaly-job: %s failed: %s", server_id, exc, exc_info=True)

    async def process(self, server_id: str) -> None:
        now = self._clock()
        until = now.replace(second=0, microsecond=0) - timedelta(minutes=SETTLE_MINUTES)
        state = self._states.setdefault(server_id, _ServerState())

        if state.baseline is None or now - state.fitted_at >= REFIT_EVERY:
            if not await self._refit(server_id, state, until, now):
                return

        window_start = until - EPISODE_WINDOW
        start = max(state.scored_until or window_start, window_start)
        if start >= until:
            return
        # After a (re)start every episode of the window is written once; then only the recent ones.
        rewrite_since = window_start if state.scored_until is None else until - REWRITE_RECENT
        frame = await fetch_minute_frame(self._client, server_id, window_start, until)
        zscores = state.baseline.zscores(frame[frame.index >= pd.Timestamp(start)]).dropna(how="all")
        await insert_scores(self._client, server_id, zscores)
        state.scored_until = until

        flags = await recent_flags(self._client, server_id, window_start)
        records = self._episodes(server_id, state, frame, flags, until, rewrite_since)
        await upsert_episodes(self._client, records, now)

    async def _refit(self, server_id: str, state: _ServerState, until: datetime, now: datetime) -> bool:
        history = await fetch_minute_frame(self._client, server_id, until - timedelta(days=TRAINING_DAYS), until)
        minutes_with_data = int(history.notna().any(axis=1).sum())
        if minutes_with_data < MIN_TRAINING_MINUTES:
            logger.info("anomaly-job: %s has %d minutes of history, needs %d — waiting",
                        server_id, minutes_with_data, MIN_TRAINING_MINUTES)
            return False
        state.baseline = await run_in_ml_process(SeasonalBaseline.fit, history)
        state.fitted_at = now
        logger.info("anomaly-job: %s baseline refitted by %s on %d minutes",
                    server_id, state.baseline.granularity, minutes_with_data)
        return True

    def _episodes(
        self, server_id: str, state: _ServerState, frame: pd.DataFrame, flags: pd.Series,
        until: datetime, rewrite_since: datetime,
    ) -> list[EpisodeRecord]:
        flags = flags.reindex(frame.index, fill_value=False)
        window_start = frame.index[0]
        records = []
        for episode in find_episodes(flags):
            # Cut by the window: its true start is older, and that version stays as it is.
            if episode.start == window_start or episode.end < pd.Timestamp(rewrite_since):
                continue
            stretch = frame.loc[episode.start:episode.end - _MINUTE]
            deviations = state.baseline.deviations(stretch)
            records.append(EpisodeRecord(
                server_id=server_id,
                started_at=episode.start.to_pydatetime(),
                ended_at=episode.end.to_pydatetime(),
                is_open=episode.end >= pd.Timestamp(until - timedelta(minutes=MAX_GAP_MINUTES)),
                deviations=[deviation_dict(d) for d in deviations],
            ))
        return records


async def run_anomaly_job(client, on_cycle: Callable[[], None] = lambda: None) -> None:
    redis = aioredis.from_url(settings.redis_url, decode_responses=True, socket_timeout=None)
    job = AnomalyJob(client, redis)
    logger.info("anomaly-job: started (every %ds)", CYCLE_SECONDS)
    try:
        while True:
            started = time.monotonic()
            await job.run_once()
            on_cycle()
            await asyncio.sleep(max(CYCLE_SECONDS - (time.monotonic() - started), 1))
    finally:
        await redis.aclose()
