# ADR-013: Rule Scopes, Silences, Maintenance Windows and Server Names

**Status:** Accepted
**Date:** 2026-11-09

## Context

Up to 0.2.0 every rule and channel belonged to one server. Each new server got its own copy of the five
default rules, and a channel had to be added server by server. Changing a limit for every server meant editing
every copy. There was also no way to keep an alert quiet on purpose: planned work paged people, and the only
way out was deleting the rule.

Servers existed only as heartbeat keys, named by their hostname. A hostname is clear to whoever runs the
machine (`webserver-40`), not to everyone who reads the dashboard ("main applications").

## Decision

**Places.** A rule, a channel and a silence belong to a place: every server (`global`), a group, or one
server. A server is in at most one group, so "most specific" is never ambiguous. For each metric and severity
a server is judged by the most specific rule that covers it (server, then group, then global). A rule with
`enabled = false` switches the one it overrides off there. Channels do not override; an alert goes to every
channel whose place covers its server. The resolution is a pure function (`app.rule_scope`).

**State per rule and server.** A global rule watches many servers, so `alert_state` is keyed by
`(rule_id, server_id)`. The compare-and-set on `version` (ADR-011) is unchanged.

**Global defaults.** The default rules are stored once as global, editable rules. The worker does it
(`app.default_rules`), not the migration, because the limits come from the installation's settings and the
migration's SQL is generated offline. It runs only while no global rule ever existed. The per-server copies
from 0.2.0 are turned into the global rules in one transaction: each copy's state and rule-bound channels move
to the global rule, so an alert that is firing does not fire again. A copy that was edited stays as that
server's own rule, and a default that a server had deleted becomes a switched-off rule there, so it stays off.

**Quiet periods.** A silence has a place, an optional rule, a bounded `tstzrange`, a reason and an author;
ending it early moves its end to now and keeps the row. A maintenance window belongs to one server and
happens once or weekly, at a wall-clock time in a time zone. Each time it happens is a row in
`maintenance_occurrences`, under `EXCLUDE USING gist (server_id WITH =, during WITH &&)`: the database refuses
overlapping windows on one server, and "in maintenance now" is `during @> now()`. Weekly windows are written
eight weeks ahead when created (so an overlap is refused right then), and the worker keeps that horizon.
While quiet, rules are judged and events recorded; only the notification is not sent.

**Names.** A `servers` table holds every server seen (filled from the heartbeats). The hostname stays the
identity in notifications, the audit log and searches: a shared chat where each person saw a different name
would confuse an incident. An admin may set a shared label, shown beside the hostname in notifications.
Each account may set its own nickname. It changes only that account's screens, which show the nickname, then
the label, then the hostname. The hostname stays visible small underneath, and a search matches any of the
three. A nickname is unique per account (case aside), and a label is unique per installation.

**Permissions.** Labels and groups need `servers.manage` (admins). Rules, channels, silences and maintenance
need `alerts.manage`. A nickname is a personal preference, not configuration: every role manages its own.
That is the one write route a viewer may call, and `tests/test_roles.py` names it as an explicit exception.
Groups, labels, silences and windows are audited by trigger; nicknames are not.

## Consequences

- One rule per place, metric and severity (it was per server, metric, operator, threshold and severity). A
  server with two active rules for one metric and severity makes the migration fail; it must be resolved first.
- The per-server routes keep working for the current screen: they list the rules that apply on the server,
  with their place, and refuse (409) to delete one that is set elsewhere.
- `alert_defaults_applied` is only read once, by the conversion; it stays as the way back until 0.4.0.
- A maintenance window covers one server; a group of servers needs one window each. Group-wide quiet is a
  silence.
- What happens when a silence or window ends while the alert is still firing (a reminder) belongs to the alert
  cycle work, not here.
