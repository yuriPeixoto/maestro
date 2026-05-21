from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.clickhouse import AlertEvent
from app.config import settings

logger = logging.getLogger(__name__)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<body style="font-family: monospace; background: #0f1117; color: #e2e8f0; padding: 24px;">
  <div style="max-width: 560px; margin: 0 auto; border: 1px solid #2d3748; border-radius: 8px; overflow: hidden;">
    <div style="background: {header_bg}; padding: 16px 24px;">
      <span style="font-size: 20px;">{icon}</span>
      <strong style="font-size: 16px; margin-left: 8px;">{state}: {metric_name}</strong>
    </div>
    <div style="padding: 20px 24px; background: #1a1f2e;">
      <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
        <tr><td style="color: #94a3b8; padding: 6px 0;">Server</td><td style="color: #e2e8f0;">{server_id}</td></tr>
        <tr><td style="color: #94a3b8; padding: 6px 0;">Metric</td><td style="color: #e2e8f0;">{metric_name}</td></tr>
        <tr><td style="color: #94a3b8; padding: 6px 0;">Value</td><td style="color: {value_color}; font-weight: bold;">{value:.2f}</td></tr>
        <tr><td style="color: #94a3b8; padding: 6px 0;">Threshold</td><td style="color: #e2e8f0;">{threshold}</td></tr>
        <tr><td style="color: #94a3b8; padding: 6px 0;">Severity</td><td style="color: {sev_color};">{severity}</td></tr>
        <tr><td style="color: #94a3b8; padding: 6px 0;">Time</td><td style="color: #e2e8f0;">{triggered_at}</td></tr>
      </table>
    </div>
    <div style="padding: 12px 24px; background: #0f1117; font-size: 11px; color: #64748b;">
      Maestro Observability Platform
    </div>
  </div>
</body>
</html>
"""


def _build_html(event: AlertEvent) -> str:
    is_firing = event.state == "FIRING"
    triggered_at = event.triggered_at
    if isinstance(triggered_at, datetime):
        ts = triggered_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    else:
        ts = str(triggered_at)

    return _HTML_TEMPLATE.format(
        icon="🔴" if is_firing else "🟢",
        state=event.state,
        metric_name=event.metric_name,
        header_bg="#3b0d0d" if is_firing else "#0d2b1a",
        server_id=event.server_id,
        value=event.value,
        value_color="#f87171" if is_firing else "#34d399",
        threshold=event.threshold,
        severity=event.severity,
        sev_color="#f87171" if event.severity == "critical" else "#fb923c",
        triggered_at=ts,
    )


async def dispatch(to_address: str, event: AlertEvent) -> None:
    if not settings.smtp_host:
        logger.warning("email: smtp_host not configured — skipping delivery to %s", to_address)
        return

    subject = f"[Maestro] {event.state}: {event.metric_name} on {event.server_id}"
    html = _build_html(event)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_address
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_tls,
        )
        logger.info(
            "email: dispatched %s for rule=%s to %s",
            event.state, event.rule_id, to_address,
        )
    except Exception as exc:
        logger.error(
            "email: failed to send for rule=%s to %s: %s",
            event.rule_id, to_address, exc,
        )
