from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String, func
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """Append-only record of security-relevant and business-critical actions.

    Who (actor), did what (action, outcome), to what (entity), when, from where (IP, user agent,
    request id) and what changed (old/new values). Database triggers reject UPDATE and DELETE,
    except deleting rows older than the retention period (see AUDIT_TRIGGERS).
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_occurred_at", "occurred_at"),
        Index("ix_audit_logs_actor_occurred", "actor_id", "occurred_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_action_occurred", "action", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), server_default=func.now(3), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Snapshot, so the trail stays readable even if the account changes later
    actor_email: Mapped[str | None] = mapped_column(String(255))
    actor_role: Mapped[str | None] = mapped_column(String(20))
    # dotted verb, e.g. auth.login.succeeded, order.approved, user.updated
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    # success | failure | denied
    outcome: Mapped[str] = mapped_column(String(10), nullable=False, default="success")
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    # {"field": {"old": ..., "new": ...}} for updates; never passwords or secrets
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(128))


# Enforced in the database so even a bug (or a compromised app account) can't rewrite history.
AUDIT_RETENTION_DAYS_IN_TRIGGER = 400
AUDIT_TRIGGERS = [
    """
    CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'
    """,
    f"""
    CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW
    BEGIN
        IF OLD.occurred_at > UTC_TIMESTAMP() - INTERVAL {AUDIT_RETENTION_DAYS_IN_TRIGGER} DAY THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs rows can only be deleted after the retention period';
        END IF;
    END
    """,
]
DROP_AUDIT_TRIGGERS = [
    "DROP TRIGGER IF EXISTS audit_logs_no_update",
    "DROP TRIGGER IF EXISTS audit_logs_no_delete",
]
