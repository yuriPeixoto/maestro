"""Copy the alert configuration and state of 0.1.0 into Postgres.

    python -m app.import_alerting

Reads, and never writes, the ClickHouse and Redis of MAESTRO_CLICKHOUSE_* and
MAESTRO_REDIS_URL:

- active rules (`alert_rules FINAL`), with metric names renamed in the agent fixed;
- active channels (`alert_channels FINAL`); the nil rule id becomes "every rule";
- the legacy per-server webhook (`maestro:webhook:*`) as a server-wide channel;
- where each rule stands (`maestro:alert_state:*`), so nothing fires again on upgrade;
- the servers already given default rules (`maestro:default_rules_applied`).

Safe to run again: a row whose id is already in Postgres is skipped, never
overwritten. A rule equal to one the server already has is reported as a duplicate,
and its channels follow the rule that stays. At the end every source row is looked
up in Postgres; the command exits with status 1 if any is missing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid5

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app import db
from app.alert_store import STATE_FIRING, STATE_INACTIVE, STATE_RESOLVED, AlertState
from app.clickhouse import create_client
from app.config import settings
from app.models import AlertChannelRow, AlertDefaultsApplied, AlertRuleRow, AlertStateRow

logger = logging.getLogger(__name__)

# rule_id of a 0.1.0 channel that took every rule of its server.
_SERVER_WIDE_RULE_ID = UUID(int=0)
# Fixed namespace, so the legacy webhook of a server always gets the same channel id.
_LEGACY_WEBHOOK_NAMESPACE = UUID("3f1c2a7e-6d4b-4f5e-9a8b-1c2d3e4f5a6b")
_LEGACY_WEBHOOK_PATTERN = "maestro:webhook:*"
_STATE_PATTERN = "maestro:alert_state:*"
_KNOWN_STATES = {STATE_INACTIVE, STATE_FIRING, STATE_RESOLVED}

# Metric names the agent renamed; rules created before carry the old ones.
METRIC_ALIASES: dict[str, str] = {
    "cpu_percent":    "cpu_usage_percent",
    "memory_percent": "memory_usage_percent",
    "disk_percent":   "disk_usage_percent",
}

COPIED = "copied"
ALREADY = "already in Postgres"
DUPLICATE = "duplicate of an active rule"
ORPHAN = "rule deleted"
NO_STATE = "none in Redis, INACTIVE"
REJECTED = "rejected"


@dataclass
class Sources:
    rules: list[dict] = field(default_factory=list)
    channels: list[dict] = field(default_factory=list)
    states: dict[UUID, AlertState] = field(default_factory=dict)
    defaults_applied: list[str] = field(default_factory=list)


@dataclass
class Report:
    outcomes: dict[str, Counter] = field(default_factory=lambda: {
        "rules": Counter(), "channels": Counter(), "states": Counter(), "defaults_applied": Counter(),
    })
    # Source id -> the id that stands for it in Postgres (itself, or the rule it duplicates).
    rule_ids: dict[UUID, UUID] = field(default_factory=dict)
    expected_channels: set[UUID] = field(default_factory=set)
    # Rules deleted in Postgres since an earlier run: their channels are not copied.
    deleted_rules: set[UUID] = field(default_factory=set)
    rejections: list[str] = field(default_factory=list)

    def count(self, table: str, outcome: str) -> None:
        self.outcomes[table][outcome] += 1


# ── Reading the 0.1.0 stores ─────────────────────────────────────────────────

def legacy_webhook_channel_id(server_id: str) -> UUID:
    return uuid5(_LEGACY_WEBHOOK_NAMESPACE, f"legacy-webhook:{server_id}")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_state(raw: str) -> AlertState | None:
    """A Redis alert state of 0.1.0, or None when it cannot be read."""
    try:
        data = json.loads(raw)
        state = AlertState(
            state=data["state"],
            last_fired_at=_parse_time(data.get("last_fired_at")),
            last_resolved_at=_parse_time(data.get("last_resolved_at")),
        )
    except (ValueError, KeyError, TypeError):
        return None
    return state if state.state in _KNOWN_STATES else None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def read_clickhouse(client) -> tuple[list[dict], list[dict]]:  # type: ignore[no-untyped-def]
    rules = await client.query(
        "SELECT rule_id, server_id, metric_name, operator, threshold, severity, cooldown_minutes,"
        "       created_at, alert_mode, ml_score_threshold"
        " FROM alert_rules FINAL WHERE enabled = 1 ORDER BY created_at"
    )
    channels = await client.query(
        "SELECT channel_id, rule_id, server_id, channel_type, config, created_at"
        " FROM alert_channels FINAL WHERE enabled = 1 ORDER BY created_at"
    )
    return (
        [
            {
                "rule_id": r[0], "server_id": r[1], "metric_name": METRIC_ALIASES.get(r[2], r[2]),
                "operator": r[3], "threshold": float(r[4]), "severity": r[5], "cooldown_minutes": int(r[6]),
                "created_at": _as_utc(r[7]), "alert_mode": r[8] or "static",
                "ml_score_threshold": float(r[9]) if r[9] is not None else 0.7,
            }
            for r in rules.result_rows
        ],
        [
            {
                "channel_id": c[0], "rule_id": None if c[1] == _SERVER_WIDE_RULE_ID else c[1],
                "server_id": c[2], "channel_type": c[3], "config": c[4], "created_at": _as_utc(c[5]),
            }
            for c in channels.result_rows
        ],
    )


async def read_redis(redis) -> tuple[list[dict], dict[UUID, AlertState], list[str]]:  # type: ignore[no-untyped-def]
    webhooks: list[dict] = []
    async for key in redis.scan_iter(match=_LEGACY_WEBHOOK_PATTERN):
        url = await redis.get(key)
        if not url:
            continue
        server_id = key.removeprefix(_LEGACY_WEBHOOK_PATTERN[:-1])
        webhooks.append({
            "channel_id": legacy_webhook_channel_id(server_id), "rule_id": None, "server_id": server_id,
            "channel_type": "webhook", "config": json.dumps({"url": url}),
            "created_at": datetime.now(timezone.utc),
        })

    states: dict[UUID, AlertState] = {}
    async for key in redis.scan_iter(match=_STATE_PATTERN):
        raw = await redis.get(key)
        state = parse_state(raw) if raw else None
        try:
            rule_id = UUID(key.rsplit(":", 1)[1])
        except ValueError:
            continue
        if state is not None:
            states[rule_id] = state

    defaults = sorted(await redis.smembers(settings.default_rules_applied_key))
    return webhooks, states, defaults


async def read_sources(clickhouse, redis) -> Sources:  # type: ignore[no-untyped-def]
    rules, channels = await read_clickhouse(clickhouse)
    webhooks, states, defaults = await read_redis(redis)
    return Sources(rules=rules, channels=channels + webhooks, states=states, defaults_applied=defaults)


# ── Writing to Postgres ──────────────────────────────────────────────────────

async def _import_rule(rule: dict, state: AlertState | None, report: Report) -> None:
    async with db.session() as s:
        stored = await s.scalar(select(AlertRuleRow).where(AlertRuleRow.rule_id == rule["rule_id"]))
        if stored is not None:
            _point_to(stored, rule, report, ALREADY, state)
            return
        # A deleted rule counts too: its twin must not bring it back.
        same = await s.scalar(
            select(AlertRuleRow)
            .where(
                AlertRuleRow.scope == "server",
                AlertRuleRow.server_id == rule["server_id"], AlertRuleRow.metric_name == rule["metric_name"],
                AlertRuleRow.operator == rule["operator"], AlertRuleRow.threshold == rule["threshold"],
                AlertRuleRow.severity == rule["severity"],
            )
            .order_by(AlertRuleRow.deleted_at.nulls_first())
            .limit(1)
        )
        if same is not None:
            _point_to(same, rule, report, DUPLICATE, state)
            return
        await s.execute(insert(AlertRuleRow).values(**rule))
        applied = state or AlertState()
        await s.execute(insert(AlertStateRow).values(
            rule_id=rule["rule_id"], server_id=rule["server_id"], state=applied.state, last_fired_at=applied.last_fired_at,
            last_resolved_at=applied.last_resolved_at,
        ))
    report.rule_ids[rule["rule_id"]] = rule["rule_id"]
    report.count("rules", COPIED)
    report.count("states", COPIED if state is not None else NO_STATE)


def _point_to(stored: AlertRuleRow, rule: dict, report: Report, outcome: str, state: AlertState | None) -> None:
    """The source rule is already represented in Postgres by `stored`."""
    report.rule_ids[rule["rule_id"]] = stored.rule_id
    if stored.deleted_at is not None:
        report.deleted_rules.add(stored.rule_id)
    report.count("rules", outcome)
    if state is not None:
        report.count("states", outcome)


async def _import_channel(channel: dict, report: Report) -> None:
    rule_id = channel["rule_id"]
    if rule_id is not None:
        rule_id = report.rule_ids.get(rule_id)
        if rule_id is None or rule_id in report.deleted_rules:
            report.count("channels", ORPHAN)
            return
    try:
        config = json.loads(channel["config"])
    except json.JSONDecodeError:
        report.count("channels", REJECTED)
        report.rejections.append(f"channel {channel['channel_id']}: config is not JSON")
        return
    report.expected_channels.add(channel["channel_id"])
    async with db.session() as s:
        inserted = await s.scalar(
            insert(AlertChannelRow)
            .values(
                channel_id=channel["channel_id"], server_id=channel["server_id"], rule_id=rule_id,
                channel_type=channel["channel_type"], config=config, created_at=channel["created_at"],
            )
            .on_conflict_do_nothing(index_elements=["channel_id"])
            .returning(AlertChannelRow.channel_id)
        )
    report.count("channels", COPIED if inserted else ALREADY)


async def _import_defaults(server_id: str, report: Report) -> None:
    async with db.session() as s:
        inserted = await s.scalar(
            insert(AlertDefaultsApplied)
            .values(server_id=server_id)
            .on_conflict_do_nothing(index_elements=["server_id"])
            .returning(AlertDefaultsApplied.server_id)
        )
    report.count("defaults_applied", COPIED if inserted else ALREADY)


async def import_sources(sources: Sources) -> Report:
    report = Report()
    for rule in sources.rules:
        try:
            await _import_rule(rule, sources.states.get(rule["rule_id"]), report)
        except IntegrityError as exc:
            report.count("rules", REJECTED)
            report.rejections.append(f"rule {rule['rule_id']}: {exc.orig}")
    for channel in sources.channels:
        try:
            await _import_channel(channel, report)
        except IntegrityError as exc:
            report.expected_channels.discard(channel["channel_id"])
            report.count("channels", REJECTED)
            report.rejections.append(f"channel {channel['channel_id']}: {exc.orig}")
    for server_id in sources.defaults_applied:
        await _import_defaults(server_id, report)
    return report


async def missing_in_postgres(sources: Sources, report: Report) -> list[str]:
    """Source rows that should be in Postgres and are not."""
    expected_rules = {report.rule_ids[r["rule_id"]] for r in sources.rules if r["rule_id"] in report.rule_ids}
    async with db.session() as s:
        rules = set(await s.scalars(select(AlertRuleRow.rule_id).where(AlertRuleRow.rule_id.in_(expected_rules))))
        states = set(await s.scalars(select(AlertStateRow.rule_id).where(AlertStateRow.rule_id.in_(expected_rules))))
        channels = set(await s.scalars(
            select(AlertChannelRow.channel_id).where(AlertChannelRow.channel_id.in_(report.expected_channels))
        ))
        defaults = set(await s.scalars(select(AlertDefaultsApplied.server_id)))
    missing = [f"rule {rid}" for rid in expected_rules - rules]
    missing += [f"state of rule {rid}" for rid in expected_rules - states]
    missing += [f"channel {cid}" for cid in report.expected_channels - channels]
    missing += [f"defaults of {sid}" for sid in set(sources.defaults_applied) - defaults]
    return missing


# ── Command ──────────────────────────────────────────────────────────────────

def _print_report(sources: Sources, report: Report, missing: list[str]) -> None:
    source_counts = {
        "rules": len(sources.rules), "channels": len(sources.channels),
        "defaults_applied": len(sources.defaults_applied),
    }
    source_counts["states"] = len(sources.states)
    for table, total in source_counts.items():
        outcomes = ", ".join(f"{n} {name}" for name, n in report.outcomes[table].most_common()) or "nothing"
        print(f"{table:<17} source {total:>4}: {outcomes}")
    for line in report.rejections:
        print(f"  rejected: {line}")
    if missing:
        print(f"MISSING in Postgres ({len(missing)}):")
        for line in missing:
            print(f"  {line}")
    else:
        print("Check: every source row is in Postgres.")


async def _main() -> int:
    db.set_application_name("maestro-import")
    db.check_database_url(settings.database_url)
    await db.check_schema_is_current()
    clickhouse = await create_client()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        sources = await read_sources(clickhouse, redis)
        report = await import_sources(sources)
        missing = await missing_in_postgres(sources, report)
    finally:
        await redis.aclose()
        await clickhouse.close()
        await db.dispose_engine()
    _print_report(sources, report, missing)
    return 1 if missing or report.rejections else 0


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
