"""Transactional outbox: enqueue work inside a business transaction, run it in the worker.

    enqueue()   in the caller's transaction (no commit here)
    claim()     worker: lock due jobs with FOR UPDATE SKIP LOCKED, mark RUNNING, commit
    complete()  / fail()   worker: record the outcome; failures retry with exponential backoff
                           plus jitter until max_attempts, then the job goes DEAD (dead-letter)

Delivery is at-least-once: if a worker dies after sending an email but before recording it,
the job runs again when its lock expires. Handlers are written to be safe to repeat.
"""

import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.orm import Session

from app.core import clock, context
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models import JobStatus, OutboxJob
from app.services.pagination import paginate

logger = logging.getLogger(__name__)

PRIORITY_URGENT = 0  # sign-in / reset codes
PRIORITY_HIGH = 2  # security notices
PRIORITY_NORMAL = 5  # workflow notifications

BACKOFF_BASE_SECONDS = 15
BACKOFF_MAX_SECONDS = 3600
_DUE = (JobStatus.PENDING, JobStatus.RETRY)


def enqueue(
    db: Session,
    job_type: str,
    payload: dict[str, Any],
    *,
    priority: int = PRIORITY_NORMAL,
    dedupe_key: str | None = None,
    delay_seconds: int = 0,
    expires_at: datetime | None = None,
    max_attempts: int | None = None,
    order_id: int | None = None,
) -> OutboxJob | None:
    """Add a job to the caller's transaction. With a dedupe_key, an existing job is reused."""
    if dedupe_key is not None:
        existing = db.scalar(select(OutboxJob).where(OutboxJob.dedupe_key == dedupe_key))
        if existing is not None:
            return existing
    ctx = context.current()
    job = OutboxJob(
        job_type=job_type,
        payload=payload,
        status=JobStatus.PENDING,
        priority=priority,
        attempts=0,
        max_attempts=max_attempts or settings.JOB_MAX_ATTEMPTS,
        available_at=clock.utcnow().replace(microsecond=0) + timedelta(seconds=delay_seconds),
        expires_at=expires_at,
        dedupe_key=dedupe_key,
        request_id=ctx.request_id,
        created_by_id=ctx.user_id,
        order_id=order_id,
    )
    db.add(job)
    return job


@dataclass
class ClaimedJob:
    id: int
    job_type: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    expires_at: datetime | None
    request_id: str | None
    lease_owner: str


def claim(db: Session, worker_id: str, limit: int, only_types: list[str] | None = None) -> list[ClaimedJob]:
    """Lock up to `limit` due jobs for this worker. Other workers skip locked rows instead of waiting."""
    now = clock.utcnow()
    try:
        stmt = (
            select(OutboxJob)
            .where(
                or_(
                    (OutboxJob.status.in_(_DUE)) & (OutboxJob.available_at <= now),
                    # a worker died mid-job: its lock has expired, so the job is free again
                    (OutboxJob.status == JobStatus.RUNNING) & (OutboxJob.locked_until < now),
                )
            )
            .order_by(OutboxJob.priority, OutboxJob.available_at, OutboxJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if only_types is not None:
            stmt = stmt.where(OutboxJob.job_type.in_(only_types))
        jobs = db.scalars(stmt).all()
        claimed = []
        for job in jobs:
            job.status = JobStatus.RUNNING
            job.attempts += 1
            # A worker may reclaim the same job after a restart or operator retry. Give each
            # claim its own owner token so a slow, obsolete claim cannot finish the new one.
            job.locked_by = f"{worker_id[:47]}:{uuid.uuid4().hex}"
            job.locked_until = now + timedelta(seconds=settings.JOB_LOCK_SECONDS)
            claimed.append(
                ClaimedJob(
                    job.id,
                    job.job_type,
                    dict(job.payload),
                    job.attempts,
                    job.max_attempts,
                    job.expires_at,
                    job.request_id,
                    job.locked_by,
                )
            )
        db.commit()
        return claimed
    except Exception:
        db.rollback()
        raise


def _finish(db: Session, job: ClaimedJob, **values: Any) -> bool:
    result = cast(
        CursorResult,
        db.execute(
            update(OutboxJob)
            .where(
                OutboxJob.id == job.id,
                OutboxJob.status == JobStatus.RUNNING,
                OutboxJob.locked_by == job.lease_owner,
                OutboxJob.attempts == job.attempts,
            )
            .values(locked_until=None, locked_by=None, **values)
        ),
    )
    if result.rowcount != 1:
        # Roll back handler-side records too; this worker no longer owns the transaction outcome.
        db.rollback()
        logger.warning("Discarding outcome for obsolete claim of job %s", job.id)
        return False
    db.commit()
    return True


def complete(db: Session, job: ClaimedJob, *, scrub_payload: bool = False) -> bool:
    values: dict[str, Any] = {"status": JobStatus.DONE, "completed_at": clock.utcnow(), "last_error": None}
    if scrub_payload:
        values["payload"] = {"scrubbed": True}  # e.g. a one-time code that was just sent
    return _finish(db, job, **values)


def expire(db: Session, job: ClaimedJob) -> bool:
    return _finish(db, job, status=JobStatus.EXPIRED, completed_at=clock.utcnow(), payload={"scrubbed": True})


def backoff_seconds(attempt: int) -> int:
    """15 s, 30 s, 60 s, ... capped at an hour, with +-20% jitter so retries don't stampede."""
    delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
    return int(delay * random.uniform(0.8, 1.2))  # nosec B311 - jitter, not security


def fail(db: Session, job: ClaimedJob, error: str, *, permanent: bool = False) -> str:
    """Schedule a retry, or dead-letter the job. Returns the new status."""
    error = error[:2000]
    if permanent or job.attempts >= job.max_attempts:
        if not _finish(db, job, status=JobStatus.DEAD, last_error=error, completed_at=clock.utcnow()):
            return "STALE"
        logger.error(
            "Job %s (%s) moved to dead-letter after %d attempts: %s",
            job.id,
            job.job_type,
            job.attempts,
            error,
            extra={"event": "job.dead", "job_id": job.id, "job_type": job.job_type},
        )
        return JobStatus.DEAD
    available_at = clock.utcnow() + timedelta(seconds=backoff_seconds(job.attempts))
    if not _finish(db, job, status=JobStatus.RETRY, last_error=error, available_at=available_at):
        return "STALE"
    logger.warning(
        "Job %s (%s) failed (attempt %d/%d), retrying at %s: %s",
        job.id,
        job.job_type,
        job.attempts,
        job.max_attempts,
        available_at.isoformat(timespec="seconds"),
        error,
        extra={"event": "job.retry", "job_id": job.id, "job_type": job.job_type},
    )
    return JobStatus.RETRY


# ----------------------------------------------------------------------------- operations


def pending_for_order(db: Session, order_id: int) -> list[OutboxJob]:
    return list(
        db.scalars(
            select(OutboxJob)
            .where(
                OutboxJob.order_id == order_id,
                OutboxJob.status.in_((JobStatus.PENDING, JobStatus.RETRY, JobStatus.RUNNING)),
            )
            .order_by(OutboxJob.id)
        ).all()
    )


def counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(OutboxJob.status, func.count()).group_by(OutboxJob.status)).all()
    result = {status.value: 0 for status in JobStatus}
    result.update({status: count for status, count in rows})
    return result


def oldest_due_age_seconds(db: Session) -> int:
    oldest = db.scalar(
        select(func.min(OutboxJob.available_at)).where(
            OutboxJob.status.in_(_DUE), OutboxJob.available_at <= clock.utcnow()
        )
    )
    return int((clock.utcnow() - oldest).total_seconds()) if oldest else 0


def list_jobs(db: Session, *, status: JobStatus | None, job_type: str | None, page: int, page_size: int):
    stmt = select(OutboxJob).order_by(OutboxJob.id.desc())
    if status:
        stmt = stmt.where(OutboxJob.status == status)
    if job_type:
        stmt = stmt.where(OutboxJob.job_type == job_type)
    return paginate(db, stmt, page, page_size)


def retry_dead(db: Session, job_id: int) -> OutboxJob:
    """Operator action: give a dead-lettered job a fresh set of attempts."""
    job = db.get(OutboxJob, job_id, with_for_update=True)
    if job is None:
        raise NotFoundError(f"Job {job_id} not found")
    if job.status != JobStatus.DEAD:
        raise ConflictError(f"Job {job_id} is {job.status}, only DEAD jobs can be retried", code="JOB_NOT_DEAD")
    job.status = JobStatus.PENDING
    job.attempts = 0
    job.available_at = clock.utcnow()
    job.completed_at = None
    return job
