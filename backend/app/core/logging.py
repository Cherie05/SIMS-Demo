"""Structured logging.

Every record carries timestamp, level, logger, service, environment and - inside a request - the
request id, client IP and user id, so one request can be followed across the proxy, the API and
the worker. LOG_FORMAT=json writes one JSON object per line for log shippers (Loki, ELK,
CloudWatch); text is for local development.

Secrets never reach the log: values of sensitive keys and anything that looks like a bearer token,
JWT or password assignment is masked before the record is written.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core import context
from app.core.config import settings

SENSITIVE_KEYS = re.compile(r"pass(word)?|secret|token|authorization|cookie|api[_-]?key|otp|code_hash", re.I)
_PATTERNS = [
    # Authorization: Bearer <token>
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [REDACTED]"),
    # JSON Web Tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), "[REDACTED_JWT]"),
    # password=..., "password": "...", secret: ...
    (
        re.compile(r"(?i)([\"']?(?:password|passwd|secret|api[_-]?key|token)[\"']?\s*[:=]\s*)([\"']?)[^\s\"',;&}]+"),
        r"\1\2[REDACTED]",
    ),
]
# Attributes of every LogRecord; anything else was passed with extra={...}
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(key: str, value: Any) -> Any:
    # Secrets are strings; flags and counts under a sensitive-sounding name (otp_required) are not.
    if SENSITIVE_KEYS.search(key) and isinstance(value, str | bytes):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(key, v) for v in value]
    return value


class ContextFilter(logging.Filter):
    """Attach request context to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = context.current()
        record.request_id = ctx.request_id
        record.user_id = ctx.user_id
        record.client_ip = ctx.client_ip
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "service": settings.SERVICE_NAME,
            "environment": settings.ENVIRONMENT,
            "version": settings.APP_VERSION,
        }
        for key in ("request_id", "user_id", "client_ip"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        for key, value in record.__dict__.items():
            if key not in _RESERVED and key not in entry and not key.startswith("_"):
                entry[key] = redact_value(key, value)
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = redact(super().format(record))
        request_id = getattr(record, "request_id", None)
        return f"{line} [request_id={request_id}]" if request_id else line


def configure_logging(service: str | None = None) -> None:
    """Idempotent: replaces the root handlers with one structured stdout handler."""
    if service:
        settings.SERVICE_NAME = service
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())
    # uvicorn's own loggers propagate to the root handler; its access log is replaced by ours.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
