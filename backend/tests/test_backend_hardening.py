"""Regression coverage for credential invalidation and safe operational checks."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock, health, security
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import BusinessRuleError
from app.models import (
    IdempotencyKey,
    JobStatus,
    OtpChallenge,
    OutboxJob,
    Product,
    SalesOrder,
    User,
    UserRole,
    UserSession,
)
from app.schemas.user import UserUpdate
from app.services import notification_service, session_service, user_service
from tests.conftest import PASSWORD, PASSWORD_HASH, sign_in
from tests.database_safety import validate_test_database_url

AUTH = "/api/v1/auth"


def test_two_admins_cannot_concurrently_deactivate_each_other(users, db):
    first_id = users["admin"].id
    second = User(
        name="Second Admin",
        email="second-admin@example.com",
        password_hash=PASSWORD_HASH,
        role=UserRole.ADMIN,
        email_verified_at=clock.utcnow(),
    )
    db.add(second)
    db.commit()
    second_id = second.id
    barrier = threading.Barrier(2)

    def deactivate(actor_id, target_id):
        with SessionLocal() as session:
            actor = session.get(User, actor_id)
            barrier.wait()
            try:
                user_service.update_user(session, target_id, UserUpdate(is_active=False), actor)
                return "deactivated"
            except BusinessRuleError as exc:
                assert exc.code == "LAST_ADMIN"
                return "preserved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(deactivate, first_id, second_id), pool.submit(deactivate, second_id, first_id)]
        assert sorted(future.result(timeout=15) for future in futures) == ["deactivated", "preserved"]
    db.expire_all()
    assert len(db.scalars(select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))).all()) == 1


@pytest.mark.parametrize("action", ["change", "reset", "admin"])
def test_password_changes_invalidate_unredeemed_sign_in_codes(client, users, otp_codes, auth, action):
    session = sign_in(client, otp_codes, "sales@example.com")
    challenge = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
    old_code = otp_codes["sales@example.com"][-1]
    new_password = "New-Secure-Pass-42"
    if action == "change":
        response = client.post(
            f"{AUTH}/password/change",
            headers={"Authorization": f"Bearer {session['access_token']}"},
            json={"current_password": PASSWORD, "new_password": new_password},
        )
        assert response.status_code == 204
    elif action == "reset":
        client.post(f"{AUTH}/password/forgot", json={"email": "sales@example.com"})
        response = client.post(
            f"{AUTH}/password/reset",
            json={
                "email": "sales@example.com",
                "code": otp_codes["sales@example.com"][-1],
                "new_password": new_password,
            },
        )
        assert response.status_code == 204
    else:
        response = client.patch(
            f"/api/v1/users/{users['sales'].id}", headers=auth("admin"), json={"password": new_password}
        )
        assert response.status_code == 200
    refused = client.post(f"{AUTH}/otp/verify", json={"challenge_id": challenge["challenge_id"], "code": old_code})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "OTP_INVALID_CHALLENGE"
    sign_in(client, otp_codes, "sales@example.com", password=new_password)


def test_second_factor_redemption_rolls_back_if_session_creation_fails(client, users, otp_codes, db, monkeypatch):
    challenge = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
    original_start = session_service.start

    def fail(*_args, **_kwargs):
        raise RuntimeError("database operation failed before session commit")

    monkeypatch.setattr(session_service, "start", fail)
    body = {"challenge_id": challenge["challenge_id"], "code": otp_codes["sales@example.com"][-1]}
    response = TestClient(client.app, raise_server_exceptions=False).post(f"{AUTH}/otp/verify", json=body)
    assert response.status_code == 500
    stored = db.get(OtpChallenge, challenge["challenge_id"])
    assert stored.consumed_at is None
    assert db.scalars(select(UserSession)).all() == []
    monkeypatch.setattr(session_service, "start", original_start)
    assert client.post(f"{AUTH}/otp/verify", json=body).status_code == 200


def test_enabling_mfa_invalidates_previous_email_sign_in_challenges(client, users, otp_codes):
    session = sign_in(client, otp_codes, "sales@example.com")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    pending = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
    old_code = otp_codes["sales@example.com"][-1]
    setup = client.post(f"{AUTH}/mfa/totp/setup", headers=headers, json={"password": PASSWORD}).json()
    response = client.post(f"{AUTH}/mfa/totp/enable", headers=headers, json={"code": pyotp.TOTP(setup["secret"]).now()})
    assert response.status_code == 200
    old = client.post(f"{AUTH}/otp/verify", json={"challenge_id": pending["challenge_id"], "code": old_code})
    assert old.status_code == 400 and old.json()["error"]["code"] == "OTP_INVALID_CHALLENGE"


def test_mfa_enrolment_code_guesses_trigger_account_lockout(client, users, otp_codes):
    session = sign_in(client, otp_codes, "sales@example.com")
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    setup = client.post(f"{AUTH}/mfa/totp/setup", headers=headers, json={"password": PASSWORD}).json()
    totp = pyotp.TOTP(setup["secret"])
    # Pick a code that cannot match any tolerated time step.
    valid = {totp.at(time.time() + shift) for shift in (-30, 0, 30)}
    wrong = next(f"{n:06}" for n in range(10) if f"{n:06}" not in valid)
    for _ in range(settings.LOGIN_MAX_FAILURES_PER_EMAIL):
        response = client.post(f"{AUTH}/mfa/totp/enable", headers=headers, json={"code": wrong})
        assert response.status_code == 400
    response = client.post(f"{AUTH}/mfa/totp/enable", headers=headers, json={"code": totp.now()})
    assert response.status_code == 429


def test_email_login_codes_are_queued_with_their_challenge_and_stale_codes_are_scrubbed(
    client, users, db, monkeypatch, later, run_jobs, sent_emails, otp_codes
):
    monkeypatch.setattr(settings, "OTP_DELIVERY", "email")
    first = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
    job = db.scalars(select(OutboxJob)).one()
    original_code = security.decrypt(job.payload["code_encrypted"])
    assert job.payload["challenge_id"] == first["challenge_id"] and otp_codes["sales@example.com"] == []
    assert job.expires_at == db.get(OtpChallenge, first["challenge_id"]).expires_at
    later(settings.OTP_RESEND_COOLDOWN_SECONDS + 1)
    assert client.post(f"{AUTH}/otp/resend", json={"challenge_id": first["challenge_id"]}).status_code == 200
    run_jobs()
    assert len(sent_emails) == 1
    assert not sent_emails[0]["Subject"].startswith(original_code)
    db.expire_all()
    assert {row.status for row in db.scalars(select(OutboxJob))} == {JobStatus.DONE}
    assert all(row.payload == {"scrubbed": True} for row in db.scalars(select(OutboxJob)))


def test_email_queue_failure_rolls_back_the_corresponding_challenge(client, users, db, monkeypatch):
    monkeypatch.setattr(settings, "OTP_DELIVERY", "email")

    def fail(*_args, **_kwargs):
        raise RuntimeError("queue insertion failed")

    monkeypatch.setattr(notification_service, "enqueue_otp", fail)
    response = TestClient(client.app, raise_server_exceptions=False).post(
        f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}
    )
    assert response.status_code == 500
    assert db.scalars(select(OtpChallenge)).all() == []
    assert db.scalars(select(OutboxJob)).all() == []


def test_idle_sessions_stop_access_and_are_omitted_from_active_devices(client, users, otp_codes, db, later):
    session = sign_in(client, otp_codes, "sales@example.com")
    later(settings.session_idle_timeout_seconds + 1)
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    assert client.get(f"{AUTH}/me", headers=headers).status_code == 401
    assert session_service.list_active(db, users["sales"].id) == []


def test_failed_order_creation_rolls_back_its_idempotency_reservation(client, auth, customer, make_product, db):
    product = make_product(stock=0)
    headers = {**auth("sales"), "Idempotency-Key": "stock-after-failed-attempt-001"}
    body = {"customer_id": customer.id, "items": [{"product_id": product.id, "quantity": 1}]}
    assert client.post("/api/v1/orders", json=body, headers=headers).status_code == 409
    assert db.scalars(select(IdempotencyKey)).all() == []
    assert db.scalars(select(SalesOrder)).all() == []
    client.post(
        f"/api/v1/products/{product.id}/stock-adjustments",
        headers=auth("manager"),
        json={"txn_type": "RESTOCK", "quantity": 1},
    )
    assert client.post("/api/v1/orders", json=body, headers=headers).status_code == 201
    db.expire_all()
    assert db.get(Product, product.id).stock_qty == 0


@pytest.mark.parametrize("name", ["sims", "production", "sims_production", "prod_sims_test", ""])
def test_destructive_tests_reject_application_databases(name):
    # Test-only prefixes are required; ordinary application and production names are rejected.
    with pytest.raises(RuntimeError, match="Refusing destructive tests"):
        validate_test_database_url(f"mysql+pymysql://sims:password@localhost/{name}")


def test_destructive_migration_tests_reject_the_main_test_database():
    with pytest.raises(RuntimeError, match="sims_migrations"):
        validate_test_database_url("mysql+pymysql://sims:password@localhost/sims_test", migrations=True)
    assert validate_test_database_url("mysql+pymysql://sims:password@localhost/sims_test_ci").database == "sims_test_ci"


def test_deployed_readiness_fails_when_migration_version_table_is_missing(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    for path in ("/health/ready", "/health"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
        if path == "/health/ready":
            assert response.json()["checks"]["migrations"]["status"] == "down"


def test_deployed_readiness_fails_when_packaged_migrations_are_missing(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(health, "migration_head", lambda: None)
    db = Mock(spec=Session)
    db.scalar.return_value = "previous_head"
    assert health.check_migrations(db).status == "down"
