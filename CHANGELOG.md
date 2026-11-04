# Changelog

All notable changes to Maestro. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/). Before 1.0.0 the installation contract
(transport, stores, deployment steps) may still change between minor versions.

The version lives in `VERSION`; `api/pyproject.toml` and `frontend/package.json` repeat it, and a test keeps
them equal. Notes for the dashboard's users are in `api/app/release_notes.json`; this file is the technical
history.

## [0.1.0] — 2026-11-04

First numbered release. It covers everything built so far: phases 1–4 of the roadmap and the hardening
done in 2026-10/11.

### Added
- Go agent: CPU, memory, disk, network and process metrics, log tailing, inventory, Debian package list,
  opt-in database pool monitoring, heartbeats, local ring buffer.
- Ingestion through Redis Streams into ClickHouse, acking a message only after it is written.
- Hourly rollup of every metric (`metrics_hourly`, migrations 012–013), kept for two years; charts longer
  than a day and capacity read it. Column codecs on the time-series tables (migration 014).
- Separate worker process (`python -m app.worker`) for consumers, the alert evaluator and scheduled jobs;
  the API only serves HTTP. `/health` reports both and the external watchdog alerts on either.
- Alerting: default rules per server, threshold and ML rules, Telegram, webhook, Slack and e-mail channels,
  delivery history, offline detection.
- Anomaly detection against a seasonal baseline, reported as episodes with what deviated and the normal
  range (`anomaly_episodes`, migration 015). See ADR-010.
- Capacity: disk trend since the last level shift; CPU and memory as the daily 5-minute peak against the
  limits (`GET /forecasts/{server}/peaks`).
- Evaluation bench for anomaly detection and forecasts: `python -m app.ml.evaluation`.
- Security signals (SSH, UFW), vulnerability scan of runtimes and Debian packages against OSV.dev.
- Accounts with forced password change, login throttling, and a required JWT secret of 32+ characters.
- About screen and "what's new" modal; `GET /about`; `POST /auth/me/release-seen`.

### Changed
- Python dependencies are locked with uv (`api/uv.lock`); tokens are signed with PyJWT.
- ML work runs in a low-priority child process of the worker.

### Removed
- River, the per-metric Isolation Forest, the feature pipeline (`metric_features` is no longer written),
  the model store (`MAESTRO_ML_MODELS_DIR`) and Prophet.

### Fixed
- A server in attention now says why.
- The network charts used metric names the agent never sent.
