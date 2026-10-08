"""Periodic housekeeping, run by the workers.

Each task runs on at most one worker at a time (MySQL GET_LOCK named lock) and no more often than
its interval, however many workers are running. Runs are recorded in scheduled_task_runs and
shown on the admin System page.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.database import SessionLocal, named_lock
from app.models import (
    AuditLog,
    EmailLog,
    IdempotencyKey,
    JobStatus,
    OtpChallenge,
    OutboxJob,
    RefreshToken,
    ScheduledTaskRun,
    UserSession,
    WorkerHeartbeat,
)

logger = logging.getLogger(__name__)


def _deleted(db: Session, stmt) -> int:
    result = cast(CursorResult, db.execute(stmt))
    return result.rowcount or 0


def cleanup_auth(db: Session) -> dict[str, Any]:
    """Expired codes, tokens, sessions and idempotency keys are useless after a grace period."""
    now = clock.utcnow()
    day_ago = now - timedelta(days=1)
    month_ago = now - timedelta(days=30)
    return {
        "otp_challenges": _deleted(db, delete(OtpChallenge).where(OtpChallenge.expires_at < day_ago)),
        "refresh_tokens": _deleted(db, delete(RefreshToken).where(RefreshToken.expires_at < day_ago)),
        "user_sessions": _deleted(
            db,
            delete(UserSession).where(or_(UserSession.expires_at < month_ago, UserSession.revoked_at < month_ago)),
        ),
        "idempotency_keys": _deleted(db, delete(IdempotencyKey).where(IdempotencyKey.expires_at < now)),
    }


def cleanup_jobs(db: Session) -> dict[str, Any]:
    """Finished jobs are kept for RETENTION_JOBS_DAYS; dead-lettered ones three times as long."""
    now = clock.utcnow()
    finished = now - timedelta(days=settings.RETENTION_JOBS_DAYS)
    dead = now - timedelta(days=settings.RETENTION_JOBS_DAYS * 3)
    return {
        "finished": _deleted(
            db,
            delete(OutboxJob).where(
                OutboxJob.status.in_((JobStatus.DONE, JobStatus.EXPIRED)), OutboxJob.completed_at < finished
            ),
        ),
        "dead": _deleted(
            db, delete(OutboxJob).where(OutboxJob.status == JobStatus.DEAD, OutboxJob.completed_at < dead)
        ),
        "worker_heartbeats": _deleted(
            db, delete(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at < now - timedelta(days=1))
        ),
    }


def retention(db: Session) -> dict[str, Any]:
    """Data retention policy (docs/operations/data-classification.md)."""
    now = clock.utcnow()
    return {
        # The database trigger only allows deleting audit entries older than its own minimum.
        "audit_logs": _deleted(
            db, delete(AuditLog).where(AuditLog.occurred_at < now - timedelta(days=settings.RETENTION_AUDIT_DAYS))
        ),
        "email_logs": _deleted(
            db, delete(EmailLog).where(EmailLog.created_at < now - timedelta(days=settings.RETENTION_EMAIL_LOG_DAYS))
        ),
    }


@dataclass(frozen=True)
class Task:
    name: str
    interval: timedelta
    run: Callable[[Session], dict[str, Any]]


TASKS = [
    Task("cleanup.auth", timedelta(hours=1), cleanup_auth),
    Task("cleanup.jobs", timedelta(hours=1), cleanup_jobs),
    Task("retention", timedelta(days=1), retention),
]


def _due(db: Session, task: Task) -> bool:
    last = db.scalar(select(ScheduledTaskRun.last_started_at).where(ScheduledTaskRun.name == task.name))
    return last is None or clock.utcnow() - last >= task.interval


def run_task(task: Task, *, force: bool = False) -> str:
    """Run one task if it is due and no other worker is running it. Returns ran / skipped / busy / failed."""
    with named_lock(f"sims.task.{task.name}") as acquired:
        if not acquired:
            return "busy"
        with SessionLocal() as db:
            if not force and not _due(db, task):
                return "skipped"
            row = db.get(ScheduledTaskRun, task.name) or ScheduledTaskRun(name=task.name, run_count=0)
            row.last_started_at = clock.utcnow()
            db.merge(row)
            db.commit()
            try:
                result = task.run(db)
                db.commit()
                status, error = "ok", None
            except Exception as exc:
                db.rollback()
                result, status, error = None, "failed", f"{type(exc).__name__}: {exc}"[:2000]
                logger.exception("Scheduled task %s failed", task.name, extra={"event": "task.failed"})
            finished = db.get(ScheduledTaskRun, task.name)
            assert finished is not None  # nosec B101 - created above
            finished.last_finished_at = clock.utcnow()
            finished.last_status = status
            finished.last_error = error
            finished.last_result = result
            finished.run_count += 1
            db.commit()
            if status == "ok":
                logger.info("Scheduled task %s: %s", task.name, result, extra={"event": "task.done"})
            return "ran" if status == "ok" else "failed"


def run_due_tasks() -> dict[str, str]:
    return {task.name: run_task(task) for task in TASKS}
