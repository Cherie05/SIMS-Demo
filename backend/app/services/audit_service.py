"""Audit trail: who did what, to what, when, from where, and what changed.

record() adds the entry to the caller's session, so it commits (or rolls back) together with the
change it describes. record_now() writes immediately in its own transaction, for events that must
survive the request failing (a refused sign-in, a denied action).

Every entry is also emitted as a structured log line (logger sims.audit) so a log pipeline or
SIEM receives it without reading the database.
"""

import logging
from datetime import date, datetime, time
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock, context
from app.core.database import SessionLocal
from app.core.logging import SENSITIVE_KEYS
from app.models import AuditLog, User
from app.services.pagination import paginate

logger = logging.getLogger("sims.audit")


def _clean(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data:
        return None
    cleaned = {}
    for key, value in data.items():
        # Secrets are strings; booleans like password_reset_by_admin are facts worth keeping.
        if SENSITIVE_KEYS.search(str(key)) and isinstance(value, str | bytes):
            cleaned[key] = "[REDACTED]"
        else:
            cleaned[key] = value
    return jsonable_encoder(cleaned)


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """{"field": {"old": x, "new": y}} for every field whose value changed."""
    changes = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if jsonable_encoder(old) != jsonable_encoder(new):
            changes[key] = {"old": old, "new": new}
    return changes


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    return {field: getattr(obj, field) for field in fields}


def _entry(
    action: str,
    *,
    actor: User | None,
    actor_id: int | None,
    actor_email: str | None,
    outcome: str,
    entity_type: str | None,
    entity_id: Any,
    changes: dict[str, Any] | None,
    details: dict[str, Any] | None,
) -> AuditLog:
    ctx = context.current()
    entry = AuditLog(
        occurred_at=clock.utcnow(),
        actor_id=actor.id if actor else (actor_id if actor_id is not None else ctx.user_id),
        actor_email=actor.email if actor else actor_email,
        actor_role=actor.role.value if actor else None,
        action=action,
        outcome=outcome,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        changes=_clean(changes),
        details=_clean(details),
        ip_address=ctx.client_ip,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
    )
    log = logger.warning if outcome != "success" else logger.info
    log(
        "audit %s %s",
        action,
        outcome,
        extra={
            "event": "audit",
            "audit_action": action,
            "audit_outcome": outcome,
            "actor_id": entry.actor_id,
            "entity_type": entity_type,
            "entity_id": entry.entity_id,
        },
    )
    return entry


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
    outcome: str = "success",
    entity_type: str | None = None,
    entity_id: Any = None,
    changes: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    entry = _entry(
        action,
        actor=actor,
        actor_id=actor_id,
        actor_email=actor_email,
        outcome=outcome,
        entity_type=entity_type,
        entity_id=entity_id,
        changes=changes,
        details=details,
    )
    db.add(entry)
    return entry


def record_now(action: str, **kwargs: Any) -> None:
    """Write in a separate transaction (survives the current request failing). Never raises."""
    try:
        with SessionLocal() as db:
            actor = kwargs.pop("actor", None)
            if actor is None:
                # e.g. an access denial: only the user id is known from the request context
                actor_id = kwargs.get("actor_id") or context.current().user_id
                actor = db.get(User, actor_id) if actor_id else None
            if actor is not None:
                kwargs.pop("actor_id", None)
                kwargs.pop("actor_email", None)
                kwargs["actor"] = actor
            record(db, action, **kwargs)
            db.commit()
    except Exception:
        logger.exception("Could not write audit entry %s", action)


def record_denied(code: str, message: str) -> None:
    ctx = context.current()
    record_now(
        "access.denied",
        outcome="denied",
        details={"code": code, "message": message, "method": ctx.method, "path": ctx.path},
    )


def list_audit_logs(
    db: Session,
    *,
    action: str | None,
    actor_id: int | None,
    entity_type: str | None,
    entity_id: str | None,
    outcome: str | None,
    date_from: date | None,
    date_to: date | None,
    page: int,
    page_size: int,
):
    stmt = select(AuditLog).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    if action:
        # "order" matches order.created, order.approved, ...
        stmt = stmt.where(AuditLog.action.startswith(action.strip(), autoescape=True))
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if date_from:
        stmt = stmt.where(AuditLog.occurred_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.occurred_at <= datetime.combine(date_to, time.max))
    return paginate(db, stmt, page, page_size)
