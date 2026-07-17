"""Pluggable email sender. Sends via SMTP when configured, otherwise logs the message
(the zero-config default for local/self-host — the reset/verify link appears in the logs)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from ..config import get_settings

log = logging.getLogger("agentman.email")


def send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        # Dev / self-host without SMTP: surface the message (incl. any link) in the logs.
        log.info("EMAIL (no SMTP configured) to=%s subject=%s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from or s.smtp_user or "no-reply@agentman.local"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as srv:
            if s.smtp_starttls:
                srv.starttls()
            if s.smtp_user:
                srv.login(s.smtp_user, s.smtp_password)
            srv.send_message(msg)
    except Exception as exc:
        log.warning("email send failed to=%s: %s", to, exc)
