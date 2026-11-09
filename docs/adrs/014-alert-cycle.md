# ADR-014: The Alert Cycle

**Status:** Accepted
**Date:** 2026-11-09

## Context

Until this change, an alert said one thing when it fired and one when it resolved, and nothing
in between. A firing alert nobody looked at stayed quiet; there was no way to say "I'm on it". A rule whose
metric stopped arriving kept its last state, so a dead collector looked healthy. Several rules crossing at once
on one server sent one message each. A delivery that failed was recorded and lost. A change that happened during
a silence or maintenance was never told, even when the alert was still firing after it ended. ML rules fired on
the score of the last minute, which one noisy minute could trip.

## Decision

**What the channels heard is state.** `alert_state.notified_state` keeps what the channels last heard about a
rule on a server, apart from `state` (what is true now). Each cycle the evaluator compares the two: when they
differ and nothing keeps the alert quiet, it announces the difference. A change held back by a silence or
maintenance is therefore announced when the quiet ends, saying how long ago it happened; one that came and went
during the quiet says nothing. Before a line is queued, `notified_state` is written with the same
compare-and-set on `version` that guards state changes (ADR-011), so two evaluators never send it twice.

**Repeat until acknowledged.** A firing alert repeats every `cooldown_minutes` while nobody acknowledged it
(`last_notified_at`). The field keeps its first meaning too: a rule does not fire again sooner than that after
resolving. Acknowledging (`alerts.acknowledge`, operators and admins) marks an open alert as seen: it stays
open, stops repeating, the channels hear who acknowledged it (unless the alert is quiet) and the audit log
records it as an event; the state row is not audited, because the evaluator changes it all the time. The
acknowledgement belongs to one open alert: it is dropped when the alert opens or closes, kept between firing and
no data. It is not versioned; the evaluator never writes it except to drop it.

**No data is a state.** A missing value moves a rule to `NO_DATA`, announced once. Two exceptions keep it from
becoming noise: a metric the server never sent in the last 24 hours is a rule that cannot work (a typo, a metric
this agent does not collect), not one that stopped, and is left alone; and while a server has no heartbeat, its
rules' "no data" is recorded but not sent, because "no signal" already says it. The chat never hears that data
went missing, so it does not hear it come back either. The heartbeat rule itself is unchanged.

**One message per server and channel.** The evaluator collects the lines of a cycle and `alert_outbox` sends
one message per server and channel, a line per alert, to the channels that take each rule. The history keeps a
row per alert, so each alert's deliveries can still be told apart.

**Retries are state too.** A delivery that still fails after the sender's quick retries goes to
`notification_retries` (Postgres) and is tried after 1, 2, 4, 8, 16 and 32 minutes, then given up and logged.
Each attempt is a `notification_log` row like any delivery. A retry says how late it is, and is dropped when
every alert it speaks of has a newer event: a stale "firing" must not arrive after the "back to normal" that
replaced it.

**ML on episodes.** `ml` and `both` rules fire on an anomaly episode (ADR-010) open for at least 5 minutes that
includes the metric; `ml_score_threshold` applies to the metric's deviation in it. Without any recent score the
rule is judged on its threshold, as before.

## Consequences

- A firing alert repeats until someone acknowledges it; a rule with `cooldown_minutes` 0 never repeats. The
  default "no signal" rule repeats every 5 minutes during an outage, which is what acknowledging is for.
- An alert whose first message failed every retry is not repeated by the retries, but by the reminder: the
  channels' `notified_state` already says firing.
- `alert_events.state` and `notification_log.kind` gain values (`NO_DATA`; `no_data`, `data_back`, `reminder`,
  `acknowledged`); both are strings, no ClickHouse migration.
- Grouping works within one 30-second cycle. A burst spread over several cycles is several messages.
