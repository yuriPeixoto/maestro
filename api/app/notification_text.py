"""The sentence a notification carries, in the installation's language."""
from __future__ import annotations

from app.clickhouse import AlertEvent
from app.config import settings
from app.rule_values import HEARTBEAT_AGE_METRIC

_SECONDS_PER_MINUTE = 60

_TEXTS: dict[str, dict[str, str]] = {
    "pt-BR": {
        "critical": "Crítico",
        "warning": "Atenção",
        "firing": "🔴 {severity} em {server}: {metric} em {value} (limite {threshold})",
        "resolved": "🟢 Normalizou em {server}: {metric} em {value} (limite {threshold})",
        "offline_firing": "🔴 {severity} em {server}: sem sinal há {minutes} min",
        "offline_resolved": "🟢 Normalizou em {server}: voltou a enviar sinal",
        "test": "✅ Teste do Maestro: este canal recebe os alertas de {server}.",
        "test_shared": "✅ Teste do Maestro: este canal recebe alertas de vários servidores.",
        "no_data": "⚪ Sem dados em {server}: {metric} parou de chegar",
        "data_back": "🟢 Voltou a chegar em {server}: {metric}",
        "reminder_suffix": ", há {minutes} min",
        "late_suffix": " · há {minutes} min, durante um silêncio ou manutenção",
        "acknowledged": "👀 {user} reconheceu: {severity} em {server}: {metric}",
        "acknowledged_no_data": "👀 {user} reconheceu: sem dados em {server}: {metric}",
        "grouped": "📣 {count} avisos de {server}:",
        "delayed": "⏱ Atrasada {minutes} min · ",
        "offline": "sem sinal",
        "cpu_usage_percent": "CPU (média de 5 min)",
        "memory_usage_percent": "Memória",
        "disk_usage_percent": "Disco",
        "load_1m": "Carga (1 min)",
    },
    "en": {
        "critical": "Critical",
        "warning": "Warning",
        "firing": "🔴 {severity} on {server}: {metric} at {value} (limit {threshold})",
        "resolved": "🟢 Back to normal on {server}: {metric} at {value} (limit {threshold})",
        "offline_firing": "🔴 {severity} on {server}: no signal for {minutes} min",
        "offline_resolved": "🟢 Back to normal on {server}: reporting again",
        "test": "✅ Maestro test: this channel receives the alerts of {server}.",
        "test_shared": "✅ Maestro test: this channel receives alerts of several servers.",
        "no_data": "⚪ No data on {server}: {metric} stopped arriving",
        "data_back": "🟢 Arriving again on {server}: {metric}",
        "reminder_suffix": ", for {minutes} min",
        "late_suffix": " · {minutes} min ago, during a silence or maintenance",
        "acknowledged": "👀 {user} acknowledged: {severity} on {server}: {metric}",
        "acknowledged_no_data": "👀 {user} acknowledged: no data on {server}: {metric}",
        "grouped": "📣 {count} alerts on {server}:",
        "delayed": "⏱ {minutes} min late · ",
        "offline": "no signal",
        "cpu_usage_percent": "CPU (5 min average)",
        "memory_usage_percent": "Memory",
        "disk_usage_percent": "Disk",
        "load_1m": "Load (1 min)",
    },
}
_DEFAULT_LANGUAGE = "pt-BR"


def _texts() -> dict[str, str]:
    return _TEXTS.get(settings.notification_language, _TEXTS[_DEFAULT_LANGUAGE])


def _number(value: float, texts: dict[str, str]) -> str:
    formatted = f"{value:.1f}".removesuffix(".0")
    return formatted.replace(".", ",") if texts is _TEXTS["pt-BR"] else formatted


def _with_unit(metric_name: str, value: float, texts: dict[str, str]) -> str:
    number = _number(value, texts)
    return f"{number}%" if metric_name.endswith("_percent") else number


def server_name(server_id: str, label: str | None = None) -> str:
    """The shared label beside the hostname, which stays the identity in a shared chat."""
    return f"{label} ({server_id})" if label else server_id


def alert_text(event: AlertEvent, label: str | None = None) -> str:
    texts = _texts()
    firing = event.state == "FIRING"
    severity = texts.get(event.severity, event.severity)
    server = server_name(event.server_id, label)

    if event.metric_name == HEARTBEAT_AGE_METRIC:
        if not firing:
            return texts["offline_resolved"].format(server=server)
        minutes = _minutes(event.value)
        return texts["offline_firing"].format(severity=severity, server=server, minutes=minutes)

    return texts["firing" if firing else "resolved"].format(
        severity=severity,
        server=server,
        metric=texts.get(event.metric_name, event.metric_name),
        value=_with_unit(event.metric_name, event.value, texts),
        threshold=_with_unit(event.metric_name, event.threshold, texts),
    )


def _minutes(seconds: float) -> int:
    return max(round(seconds / _SECONDS_PER_MINUTE), 1)


def _metric(metric_name: str, texts: dict[str, str]) -> str:
    if metric_name == HEARTBEAT_AGE_METRIC:
        return texts["offline"]
    return texts.get(metric_name, metric_name)


def no_data_text(event: AlertEvent, label: str | None = None) -> str:
    texts = _texts()
    return texts["no_data"].format(server=server_name(event.server_id, label), metric=_metric(event.metric_name, texts))


def data_back_text(event: AlertEvent, label: str | None = None) -> str:
    texts = _texts()
    return texts["data_back"].format(server=server_name(event.server_id, label), metric=_metric(event.metric_name, texts))


def reminder_text(event: AlertEvent, open_seconds: float, label: str | None = None) -> str:
    """The firing sentence again, marked as a repeat. "No signal" already says for how long."""
    texts = _texts()
    sentence = "🔁" + alert_text(event, label).removeprefix("🔴")
    if event.metric_name == HEARTBEAT_AGE_METRIC:
        return sentence
    return sentence + texts["reminder_suffix"].format(minutes=_minutes(open_seconds))


def late_suffix(seconds_ago: float) -> str:
    """For a change announced only now, because a silence or maintenance held it back."""
    return _texts()["late_suffix"].format(minutes=_minutes(seconds_ago))


def acknowledged_text(event: AlertEvent, user: str, label: str | None = None) -> str:
    texts = _texts()
    key = "acknowledged_no_data" if event.state == "NO_DATA" else "acknowledged"
    return texts[key].format(
        user=user, severity=texts.get(event.severity, event.severity),
        server=server_name(event.server_id, label), metric=_metric(event.metric_name, texts),
    )


def grouped_text(server_id: str, lines: list[str], label: str | None = None) -> str:
    """One line as it is; several under a heading that names the server once."""
    if len(lines) == 1:
        return lines[0]
    heading = _texts()["grouped"].format(count=len(lines), server=server_name(server_id, label))
    return "\n".join([heading, *lines])


def delayed_text(text: str, seconds_late: float) -> str:
    return _texts()["delayed"].format(minutes=_minutes(seconds_late)) + text


def channel_test_text(server_id: str | None, label: str | None = None) -> str:
    """None: a channel for every server, or for a group."""
    texts = _texts()
    if server_id is None:
        return texts["test_shared"]
    return texts["test"].format(server=server_name(server_id, label))
