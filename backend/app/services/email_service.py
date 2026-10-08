"""SMTP email: HTML templates, a plain-text alternative, and a delivery log.

Emails are sent by the background worker from the transactional outbox (see outbox_service), never
inside an API request, so a slow or failing mail server can't block or roll back business changes.
The worker retries failed deliveries with backoff; each final outcome lands in email_logs.
"""

import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.core import metrics
from app.core.config import settings
from app.models import EmailLog, EmailStatus

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
# SMTP replies that will never succeed on retry (bad address, policy rejection)
PERMANENT_SMTP_CODES = range(500, 600)

# Autoescaping is on for every template (all are .html), so customer-entered text can't inject markup.
_env = Environment(  # nosemgrep: python.flask.security.xss.audit.direct-use-of-jinja2.direct-use-of-jinja2
    loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"], default=True)
)


class PermanentEmailError(Exception):
    """The mail server refused the message for good; retrying won't help."""


def mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"


def render(template: str, context: dict[str, Any]) -> str:
    return _env.get_template(f"{template}.html").render(**context, app_name=settings.APP_NAME)


def _html_to_text(html: str) -> str:
    text = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</tr>|</h\d>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def build_message(*, to: str, subject: str, template: str, context: dict[str, Any]) -> EmailMessage:
    html = render(template, context)
    message = EmailMessage()
    message["From"] = settings.MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=settings.MAIL_FROM.rsplit("@", 1)[-1].strip("> ") or None)
    message.set_content(_html_to_text(html))
    message.add_alternative(html, subtype="html")
    return message


def _deliver(message: EmailMessage) -> None:
    smtp_cls = smtplib.SMTP_SSL if settings.SMTP_SSL else smtplib.SMTP
    with smtp_cls(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS) as smtp:
        if settings.SMTP_STARTTLS and not settings.SMTP_SSL:
            smtp.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)


def send(message: EmailMessage) -> EmailStatus:
    """One delivery attempt. Raises on failure (PermanentEmailError when retrying is pointless)."""
    if not settings.EMAIL_ENABLED:
        return EmailStatus.SKIPPED
    try:
        _deliver(message)
    except smtplib.SMTPRecipientsRefused as exc:
        raise PermanentEmailError(f"Recipient refused: {exc.recipients}") from exc
    except smtplib.SMTPResponseException as exc:
        if exc.smtp_code in PERMANENT_SMTP_CODES and exc.smtp_code not in (421, 450, 451, 452):
            raise PermanentEmailError(f"SMTP {exc.smtp_code}: {exc.smtp_error!r}") from exc
        raise
    return EmailStatus.SENT


def log_outcome(
    db: Session,
    *,
    to: str,
    subject: str,
    template: str,
    status: EmailStatus,
    error: str | None = None,
    order_id: int | None = None,
) -> EmailLog:
    """Record an email's final outcome (the caller commits)."""
    metrics.EMAILS.labels(template, status.value).inc()
    log = EmailLog(order_id=order_id, to_email=to, subject=subject, template=template, status=status, error=error)
    db.add(log)
    if status == EmailStatus.FAILED:
        logger.error("Email '%s' to %s failed: %s", template, mask(to), error, extra={"event": "email.failed"})
    else:
        logger.info("Email '%s' to %s: %s", template, mask(to), status.value, extra={"event": "email.sent"})
    return log
