"""Background worker: transactional outbox, retries with backoff, dead-lettering, kill switch,
skip-locked work sharing, scheduled housekeeping and heartbeats."""

import smtplib
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core import clock
from app.core.database import SessionLocal, named_lock
from app.core.security import new_session_id
from app.models import (
    EmailLog,
    EmailStatus,
    IdempotencyKey,
    JobStatus,
    OtpChallenge,
    OtpPurpose,
    OutboxJob,
    RefreshToken,
    ScheduledTaskRun,
    UserSession,
    WorkerHeartbeat,
)
from app.services import email_service, feature_flags, outbox_service
from app.worker import scheduler
from app.worker.runner import Worker
from tests.conftest import REAL_OTP_DELIVER

ORDERS = "/api/v1/orders"


def _pending_order(client, auth, customer, make_product) -> dict:
    product = make_product(price="6000.00", stock=10)
    response = client.post(
        ORDERS,
        json={"customer_id": customer.id, "items": [{"product_id": product.id, "quantity": 2}]},
        headers=auth("sales"),
    )
    assert response.json()["status"] == "PENDING_APPROVAL"
    return response.json()


def _job(db) -> OutboxJob:
    db.expire_all()
    return db.scalars(select(OutboxJob)).one()


def _make_due(db, job_id: int, **values) -> None:
    db.execute(update(OutboxJob).where(OutboxJob.id == job_id).values(available_at=clock.utcnow(), **values))
    db.commit()


def test_failed_deliveries_retry_with_backoff_then_go_to_the_dead_letter_state(
    client, auth, customer, make_product, db, monkeypatch, run_jobs
):
    def smtp_down(_message):
        raise smtplib.SMTPServerDisconnected("mail server down")

    monkeypatch.setattr(email_service, "_deliver", smtp_down)
    order = _pending_order(client, auth, customer, make_product)

    run_jobs()
    job = _job(db)
    assert (job.status, job.attempts) == (JobStatus.RETRY, 1)
    delay = (job.available_at - clock.utcnow()).total_seconds()
    assert 8 <= delay <= 20  # first retry after ~15 s (with jitter)
    assert run_jobs() == 0  # not due yet

    _make_due(db, job.id, attempts=job.max_attempts - 1)
    run_jobs()
    job = _job(db)
    assert job.status == JobStatus.DEAD and "mail server down" in job.last_error
    log = db.scalars(select(EmailLog)).one()
    assert (log.status, log.order_id) == (EmailStatus.FAILED, order["id"])
    emails = client.get(f"{ORDERS}/{order['id']}", headers=auth("manager")).json()["emails"]
    assert [e["status"] for e in emails] == ["FAILED"]


def test_permanent_smtp_rejections_are_not_retried(client, auth, customer, make_product, db, monkeypatch, run_jobs):
    def refused(_message):
        raise smtplib.SMTPRecipientsRefused({"manager@example.com": (550, b"No such user")})

    monkeypatch.setattr(email_service, "_deliver", refused)
    _pending_order(client, auth, customer, make_product)
    run_jobs()
    job = _job(db)
    assert (job.status, job.attempts) == (JobStatus.DEAD, 1)
    log = db.scalars(select(EmailLog)).one()
    assert log.status == EmailStatus.FAILED and "Recipient refused" in log.error


def test_jobs_past_their_deadline_are_dropped(db, users, run_jobs, sent_emails):
    outbox_service.enqueue(db, "email.otp_code", {"secret": "x"}, expires_at=clock.utcnow() - timedelta(seconds=1))
    db.commit()
    run_jobs()
    job = _job(db)
    assert job.status == JobStatus.EXPIRED and job.payload == {"scrubbed": True}
    assert sent_emails == []


def test_sign_in_codes_wait_encrypted_and_are_scrubbed_after_sending(db, users, monkeypatch, run_jobs, sent_emails):
    from app.core.config import settings

    monkeypatch.setattr(settings, "OTP_DELIVERY", "email")
    REAL_OTP_DELIVER("sales@example.com", "Sales", OtpPurpose.LOGIN, "482913")
    job = _job(db)
    assert "482913" not in str(job.payload) and job.payload["code_encrypted"]
    assert job.priority == outbox_service.PRIORITY_URGENT

    run_jobs()
    assert sent_emails[0]["Subject"] == "482913 is your SIMS verification code"
    job = _job(db)
    assert job.status == JobStatus.DONE and job.payload == {"scrubbed": True}
    assert db.scalars(select(EmailLog.subject)).one() == "****** is your SIMS verification code"


def test_the_email_kill_switch_holds_notifications_but_not_sign_in_codes(
    client, auth, customer, make_product, db, users, monkeypatch, run_jobs, sent_emails
):
    from app.core.config import settings

    feature_flags.set_flag(db, "notifications.email", False, users["admin"])
    _pending_order(client, auth, customer, make_product)
    monkeypatch.setattr(settings, "OTP_DELIVERY", "email")
    REAL_OTP_DELIVER("sales@example.com", "Sales", OtpPurpose.LOGIN, "123123")
    run_jobs()
    assert [m["To"] for m in sent_emails] == ["sales@example.com"]  # only the sign-in code went out

    feature_flags.set_flag(db, "notifications.email", True, users["admin"])
    run_jobs()
    assert "manager@example.com" in [m["To"] for m in sent_emails]  # held, not lost


def test_a_decision_before_sending_skips_the_stale_approval_request(
    client, auth, customer, make_product, db, run_jobs, sent_emails
):
    order = _pending_order(client, auth, customer, make_product)
    client.post(f"{ORDERS}/{order['id']}/approve", headers=auth("manager"))
    run_jobs()
    assert [m["To"] for m in sent_emails] == ["sales@example.com"]  # the decision, not the old request
    assert {j.status for j in db.scalars(select(OutboxJob))} == {JobStatus.DONE}


def test_workers_share_the_queue_without_waiting_on_each_other(db, users):
    for n in range(3):
        outbox_service.enqueue(
            db, "email.security_notice", {"user_id": users["sales"].id, "kind": "new_sign_in", "n": n}
        )
    db.commit()
    with SessionLocal() as first_worker:
        held = first_worker.scalars(select(OutboxJob).limit(2).with_for_update(skip_locked=True)).all()
        with SessionLocal() as second_worker:
            claimed = outbox_service.claim(second_worker, "worker-2", limit=10)
        assert len(held) == 2 and len(claimed) == 1
        assert claimed[0].id not in {job.id for job in held}
        first_worker.rollback()


def test_jobs_of_a_crashed_worker_are_picked_up_again(db, users):
    job = outbox_service.enqueue(db, "email.security_notice", {"user_id": users["sales"].id, "kind": "new_sign_in"})
    db.commit()
    db.execute(
        update(OutboxJob)
        .where(OutboxJob.id == job.id)
        .values(
            status=JobStatus.RUNNING,
            attempts=1,
            locked_by="dead-worker",
            locked_until=clock.utcnow() - timedelta(seconds=1),
        )
    )
    db.commit()
    with SessionLocal() as worker_db:
        claimed = outbox_service.claim(worker_db, "worker-2", limit=10)
    assert [(c.id, c.attempts) for c in claimed] == [(job.id, 2)]


@pytest.mark.parametrize("outcome", ["complete", "expire", "retry", "dead"])
def test_obsolete_claims_cannot_overwrite_a_new_worker_claim(db, users, outcome):
    job = outbox_service.enqueue(db, "email.security_notice", {"user_id": users["sales"].id, "kind": "new_sign_in"})
    db.commit()
    old = outbox_service.claim(db, "worker-a", 1)[0]
    db.execute(
        update(OutboxJob).where(OutboxJob.id == job.id).values(locked_until=clock.utcnow() - timedelta(seconds=1))
    )
    db.commit()
    # Even a restarted worker with the same worker id must receive a distinct lease owner.
    new = outbox_service.claim(db, "worker-a", 1)[0]
    assert new.lease_owner != old.lease_owner
    if outcome == "complete":
        assert outbox_service.complete(db, old, scrub_payload=True) is False
    elif outcome == "expire":
        assert outbox_service.expire(db, old) is False
    else:
        assert outbox_service.fail(db, old, "late failure", permanent=outcome == "dead") == "STALE"
    db.expire_all()
    row = db.get(OutboxJob, job.id)
    assert (row.status, row.attempts, row.locked_by) == (JobStatus.RUNNING, new.attempts, new.lease_owner)
    assert row.payload == {"user_id": users["sales"].id, "kind": "new_sign_in"}
    assert outbox_service.complete(db, new)
    db.refresh(row)
    assert row.status == JobStatus.DONE


def test_dead_jobs_can_be_retried_by_an_operator(client, auth, db, users):
    job = outbox_service.enqueue(db, "email.security_notice", {"user_id": users["sales"].id, "kind": "new_sign_in"})
    db.commit()
    assert client.post(f"/api/v1/system/jobs/{job.id}/retry", headers=auth("admin")).status_code == 409
    db.execute(update(OutboxJob).where(OutboxJob.id == job.id).values(status=JobStatus.DEAD, attempts=6))
    db.commit()
    assert client.post(f"/api/v1/system/jobs/{job.id}/retry", headers=auth("manager")).status_code == 403
    retried = client.post(f"/api/v1/system/jobs/{job.id}/retry", headers=auth("admin")).json()
    assert (retried["status"], retried["attempts"]) == ("PENDING", 0)
    listed = client.get("/api/v1/system/jobs", headers=auth("admin")).json()["items"][0]
    assert listed["reference"] == {"user_id": users["sales"].id, "kind": "new_sign_in"}


def test_scheduled_housekeeping_removes_expired_data(db, users):
    now = clock.utcnow()
    old = now - timedelta(days=40)
    sales = users["sales"]
    session = UserSession(
        id=new_session_id(),
        user_id=sales.id,
        authenticated_at=old,
        last_seen_at=old,
        expires_at=old + timedelta(hours=12),
    )
    db.add(session)
    db.flush()
    db.add_all(
        [
            OtpChallenge(
                id="c" * 43,
                user_id=sales.id,
                purpose=OtpPurpose.LOGIN,
                code_hash="x",
                expires_at=now - timedelta(days=2),
                last_sent_at=now - timedelta(days=2),
            ),
            RefreshToken(
                user_id=sales.id, session_id=session.id, token_hash="h" * 64, expires_at=now - timedelta(days=2)
            ),
            IdempotencyKey(
                user_id=sales.id,
                scope="POST /orders",
                idem_key="old-key-123",
                request_hash="r" * 64,
                resource_type="order",
                resource_id=1,
                expires_at=now - timedelta(hours=1),
            ),
        ]
    )
    db.commit()
    assert scheduler.run_task(scheduler.TASKS[0], force=True) == "ran"
    run = db.get(ScheduledTaskRun, "cleanup.auth")
    assert run.last_status == "ok" and run.run_count == 1
    assert run.last_result == {"otp_challenges": 1, "refresh_tokens": 1, "user_sessions": 1, "idempotency_keys": 1}
    # not due again for an hour
    assert scheduler.run_task(scheduler.TASKS[0]) == "skipped"


def test_a_scheduled_task_runs_on_one_worker_at_a_time(db):
    with named_lock("sims.task.cleanup.auth") as held:
        assert held
        assert scheduler.run_task(scheduler.TASKS[0], force=True) == "busy"


def test_workers_report_a_heartbeat_shown_on_the_system_page(client, auth, db):
    Worker("worker-a").heartbeat(force=True)
    assert db.get(WorkerHeartbeat, "worker-a") is not None
    status = client.get("/api/v1/system/status", headers=auth("admin")).json()
    assert [(w["worker_id"], w["alive"]) for w in status["workers"]] == [("worker-a", True)]
    assert status["database"]["status"] == "ok" and status["jobs"]["DEAD"] == 0
