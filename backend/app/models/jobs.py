from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OutboxJob(Base):
    """Transactional outbox: work to do after a business change (mostly emails).

    Jobs are inserted in the same database transaction as the change that causes them, so a
    notification is never lost when the API crashes after commit, and never sent for a change that
    was rolled back. Worker processes claim due jobs with SELECT ... FOR UPDATE SKIP LOCKED (any
    number of workers can run), retry failures with exponential backoff, and move jobs that keep
    failing to DEAD (the dead-letter state) for an operator to inspect and retry.
    """

    __tablename__ = "outbox_jobs"
    __table_args__ = (
        Index("ix_outbox_jobs_due", "status", "available_at", "priority"),
        UniqueConstraint("dedupe_key", name="uq_outbox_jobs_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # PENDING -> RUNNING -> DONE | (RETRY -> RUNNING ...) | DEAD | EXPIRED
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")
    # Lower runs first (sign-in codes before routine notifications)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # A RUNNING job whose lock expired belonged to a worker that died; it is picked up again.
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    locked_by: Mapped[str | None] = mapped_column(String(80))
    # Jobs that are pointless after a deadline (e.g. a sign-in code) are dropped instead of sent late.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Enqueueing the same logical job twice is a no-op
    dedupe_key: Mapped[str | None] = mapped_column(String(150))
    last_error: Mapped[str | None] = mapped_column(Text)
    # Correlates the job with the API request that created it
    request_id: Mapped[str | None] = mapped_column(String(128))
    # The order a notification is about, so the order page can show queued emails
    order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class WorkerHeartbeat(Base):
    """Liveness of each worker process, shown on the admin System page and checked by alerts."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    jobs_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ScheduledTaskRun(Base):
    """Last run of each periodic task (housekeeping, retention). One row per task."""

    __tablename__ = "scheduled_task_runs"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_status: Mapped[str | None] = mapped_column(String(10))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class IdempotencyKey(Base):
    """Remembers which resource a client's Idempotency-Key created, so a retried POST returns the
    original result instead of creating a duplicate. Written in the same transaction as the resource."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "scope", "idem_key", name="uq_idempotency_keys_user_scope_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # e.g. "POST /orders"
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    idem_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # SHA-256 of the request body: the same key with a different body is a client bug
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
