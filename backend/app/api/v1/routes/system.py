"""Operations: system health for admins, the background job queue, and feature flags (kill switches)."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, PageParams, require
from app.core import clock, health
from app.core.config import settings
from app.core.database import transaction
from app.core.permissions import Permission
from app.models import JobStatus, OutboxJob, ScheduledTaskRun, User, WorkerHeartbeat
from app.schemas.common import Page
from app.schemas.system import (
    FeatureFlagOut,
    FeatureFlagUpdate,
    JobOut,
    ScheduledTaskOut,
    SystemStatusOut,
    WorkerOut,
)
from app.services import audit_service, feature_flags, outbox_service

router = APIRouter(tags=["System"])

SystemReader = Annotated[User, Depends(require(Permission.SYSTEM_READ))]
SystemOperator = Annotated[User, Depends(require(Permission.SYSTEM_OPERATE))]
WORKER_ALIVE_WITHIN = timedelta(seconds=60)
WORKER_LISTED_FOR = timedelta(hours=1)
_REFERENCE_KEYS = ("order_id", "recipient_id", "user_id", "kind", "purpose")


def _job_out(job: OutboxJob) -> JobOut:
    out = JobOut.model_validate(job)
    out.reference = {key: job.payload[key] for key in _REFERENCE_KEYS if key in (job.payload or {})}
    return out


@router.get("/system/status", response_model=SystemStatusOut, summary="Health of the API, database, cache and workers")
def system_status(db: DbSession, _: SystemReader):
    now = clock.utcnow()
    workers = []
    # Workers replaced by a deploy stop reporting; after an hour they're history, not status.
    recent = select(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at >= now - WORKER_LISTED_FOR)
    for row in db.scalars(recent.order_by(WorkerHeartbeat.last_seen_at.desc())).all():
        worker = WorkerOut.model_validate(row)
        worker.alive = now - row.last_seen_at <= WORKER_ALIVE_WITHIN
        workers.append(worker)
    tasks = db.scalars(select(ScheduledTaskRun).order_by(ScheduledTaskRun.name)).all()
    return SystemStatusOut(
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        uptime_seconds=health.uptime_seconds(),
        database=health.check_database(db),
        redis=health.check_redis(),
        migrations=health.check_migrations(db),
        workers=workers,
        jobs=outbox_service.counts(db),
        oldest_due_job_age_seconds=outbox_service.oldest_due_age_seconds(db),
        scheduled_tasks=[ScheduledTaskOut.model_validate(task) for task in tasks],
    )


@router.get("/system/jobs", response_model=Page[JobOut], summary="Background jobs (outbox), newest first")
def list_jobs(
    db: DbSession, _: SystemReader, pagination: PageParams, status: JobStatus | None = None, job_type: str | None = None
):
    page = outbox_service.list_jobs(
        db, status=status, job_type=job_type, page=pagination.page, page_size=pagination.page_size
    )
    page["items"] = [_job_out(job) for job in page["items"]]
    return page


@router.post("/system/jobs/{job_id}/retry", response_model=JobOut, summary="Retry a dead-lettered job")
def retry_job(job_id: int, db: DbSession, operator: SystemOperator):
    with transaction(db):
        job = outbox_service.retry_dead(db, job_id)
        audit_service.record(
            db, "job.retried", actor=operator, entity_type="job", entity_id=job.id, details={"job_type": job.job_type}
        )
    db.refresh(job)
    return _job_out(job)


@router.get("/feature-flags", response_model=list[FeatureFlagOut], summary="Feature flags (any signed-in user)")
def list_flags(db: DbSession, _: CurrentUser):
    return feature_flags.all_flags(db)


@router.put("/feature-flags/{name}", response_model=FeatureFlagOut, summary="Switch a feature on or off (audited)")
def set_flag(name: str, data: FeatureFlagUpdate, db: DbSession, operator: SystemOperator):
    return feature_flags.set_flag(db, name, data.enabled, operator)
