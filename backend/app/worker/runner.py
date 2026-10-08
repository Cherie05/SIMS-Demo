"""The worker loop: claim due outbox jobs, run their handlers, record outcomes, keep a heartbeat,
and run periodic housekeeping. Any number of workers can run side by side."""

import contextlib
import logging
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import clock, context, metrics
from app.core.config import settings
from app.core.database import SessionLocal
from app.models import JobStatus, WorkerHeartbeat
from app.services import email_service, feature_flags, notification_service, outbox_service
from app.services.notification_service import SkipJob
from app.worker import scheduler

logger = logging.getLogger("sims.worker")

# Read by the container health check (docker-compose.yml): /tmp in the container, the user's
# temporary folder when the worker runs directly on Windows or macOS.
HEARTBEAT_FILE = Path(os.getenv("WORKER_HEARTBEAT_FILE") or Path(tempfile.gettempdir()) / "sims-worker-heartbeat")
HEARTBEAT_EVERY = 15
SCHEDULE_EVERY = 30


class Worker:
    def __init__(self, worker_id: str | None = None):
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.started_at = clock.utcnow()
        self.jobs_processed = 0
        self.stopping = threading.Event()
        self._last_heartbeat = 0.0
        self._last_schedule = 0.0

    # ------------------------------------------------------------------ jobs

    def run_once(self) -> int:
        """Claim and run one batch of due jobs. Returns how many ran."""
        with SessionLocal() as db:
            only = None
            if not feature_flags.is_enabled(db, "notifications.email"):
                only = [notification_service.OTP_CODE]  # sign-in codes keep flowing during an email freeze
            jobs = outbox_service.claim(db, self.worker_id, settings.WORKER_BATCH_SIZE, only_types=only)
        for job in jobs:
            self._run(job)
        return len(jobs)

    def _run(self, job: outbox_service.ClaimedJob) -> None:
        token = context.bind(context.RequestContext(request_id=job.request_id))
        started = time.perf_counter()
        outcome = "done"
        with SessionLocal() as db:
            try:
                if job.expires_at is not None and clock.utcnow() > job.expires_at:
                    outcome = "expired" if outbox_service.expire(db, job) else "stale"
                else:
                    handler = notification_service.HANDLERS.get(job.job_type)
                    if handler is None:
                        outbox_service.fail(db, job, f"No handler for job type {job.job_type}", permanent=True)
                        outcome = "dead"
                    else:
                        handler(db, job.payload)
                        completed = outbox_service.complete(
                            db, job, scrub_payload=job.job_type in notification_service.SCRUB_ON_COMPLETE
                        )
                        if not completed:
                            outcome = "stale"
            except SkipJob as exc:
                db.rollback()
                completed = outbox_service.complete(
                    db, job, scrub_payload=job.job_type in notification_service.SCRUB_ON_COMPLETE
                )
                outcome = "skipped" if completed else "stale"
                logger.info("Job %s (%s) skipped: %s", job.id, job.job_type, exc)
            except email_service.PermanentEmailError as exc:
                db.rollback()
                _log_final_failure(db, job, exc)
                status = outbox_service.fail(db, job, str(exc), permanent=True)
                outcome = "stale" if status == "STALE" else "dead"
            except Exception as exc:
                db.rollback()
                if job.attempts >= job.max_attempts:
                    _log_final_failure(db, job, exc)
                status = outbox_service.fail(db, job, f"{type(exc).__name__}: {exc}")
                outcome = "stale" if status == "STALE" else ("dead" if status == JobStatus.DEAD else "retry")
            finally:
                context.reset(token)
        self.jobs_processed += 1
        metrics.JOBS_PROCESSED.labels(job.job_type, outcome).inc()
        metrics.JOB_DURATION.labels(job.job_type).observe(time.perf_counter() - started)

    # ------------------------------------------------------------------ heartbeat & schedule

    def heartbeat(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_heartbeat < HEARTBEAT_EVERY:
            return
        self._last_heartbeat = now
        with SessionLocal() as db:
            row = db.get(WorkerHeartbeat, self.worker_id) or WorkerHeartbeat(
                worker_id=self.worker_id,
                hostname=socket.gethostname()[:120],
                version=settings.APP_VERSION,
                started_at=self.started_at,
            )
            row.last_seen_at = clock.utcnow()
            row.jobs_processed = self.jobs_processed
            db.merge(row)
            db.commit()
            for state, count in outbox_service.counts(db).items():
                metrics.JOBS_BACKLOG.labels(state).set(count)
        metrics.WORKER_HEARTBEAT.set(time.time())
        with contextlib.suppress(OSError):  # the container health check reads this file
            HEARTBEAT_FILE.write_text(str(int(time.time())))

    def schedule(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_schedule < SCHEDULE_EVERY:
            return
        self._last_schedule = now
        scheduler.run_due_tasks()

    # ------------------------------------------------------------------ loop

    def run_forever(self) -> None:
        logger.info("Worker %s started", self.worker_id, extra={"event": "worker.start"})
        while not self.stopping.is_set():
            try:
                self.heartbeat()
                self.schedule()
                ran = self.run_once()
            except Exception:
                # Database blip or similar: log, back off, keep going (the container also restarts on crash).
                logger.exception("Worker loop error")
                metrics.DEPENDENCY_ERRORS.labels("database").inc()
                ran = 0
                self.stopping.wait(5)
            if ran == 0:
                self.stopping.wait(settings.WORKER_POLL_SECONDS)
        logger.info(
            "Worker %s stopped after %d jobs", self.worker_id, self.jobs_processed, extra={"event": "worker.stop"}
        )


def _log_final_failure(db: Session, job: outbox_service.ClaimedJob, exc: Exception) -> None:
    from app.models import EmailStatus, SalesOrder, User

    payload = job.payload
    to = payload.get("email")
    if to is None and payload.get("recipient_id"):
        recipient = db.get(User, payload["recipient_id"])
        to = recipient.email if recipient else None
    if to is None and payload.get("user_id"):
        user = db.get(User, payload["user_id"])
        to = user.email if user else None
    order_id = payload.get("order_id")
    if to is None and order_id:
        order = db.get(SalesOrder, order_id)
        to = order.created_by.email if order else None
    email_service.log_outcome(
        db,
        to=to or "unknown",
        subject=f"Undelivered: {job.job_type.removeprefix('email.')}",
        template=job.job_type.removeprefix("email."),
        status=EmailStatus.FAILED,
        error=f"{type(exc).__name__}: {exc}"[:2000],
        order_id=order_id,
    )


def drain(max_rounds: int = 20) -> int:
    """Run every due job now (tests and one-off scripts). Returns how many jobs ran."""
    worker = Worker("inline")
    total = 0
    for _ in range(max_rounds):
        ran = worker.run_once()
        total += ran
        if ran == 0:
            break
    return total
