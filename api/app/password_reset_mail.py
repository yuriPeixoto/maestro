from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<body style="font-family: monospace; background: #0f1117; color: #e2e8f0; padding: 24px;">
  <div style="max-width: 560px; margin: 0 auto; border: 1px solid #2d3748; border-radius: 8px; overflow: hidden;">
    <div style="background: #1e1145; padding: 16px 24px;">
      <strong style="font-size: 16px;">Redefinir senha — Maestro</strong>
    </div>
    <div style="padding: 20px 24px; background: #1a1f2e; font-size: 14px; line-height: 1.6;">
      <p>Foi solicitada a redefinição de senha da sua conta no Maestro.</p>
      <p><a href="{reset_url}" style="color: #a78bfa;">Clique aqui para definir uma nova senha</a></p>
      <p style="color: #94a3b8; font-size: 12px;">O link expira em {expire_minutes} minutos. Se você não pediu isso, ignore este e-mail.</p>
    </div>
    <div style="padding: 12px 24px; background: #0f1117; font-size: 11px; color: #64748b;">
      Maestro Observability Platform
    </div>
  </div>
</body>
</html>
"""


async def send_reset_email(to_address: str, token: str) -> None:
    if not settings.smtp_host:
        logger.warning("password_reset_mail: smtp_host not configured — skipping delivery to %s", to_address)
        return

    reset_url = f"{settings.frontend_url}/reset-password?token={token}"
    html = _HTML_TEMPLATE.format(
        reset_url=reset_url,
        expire_minutes=settings.password_reset_token_expire_minutes,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "[Maestro] Redefinição de senha"
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
        logger.info("password_reset_mail: dispatched reset email to %s", to_address)
    except Exception as exc:
        logger.error("password_reset_mail: failed to send to %s: %s", to_address, exc)
