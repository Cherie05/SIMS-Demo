"""Audit trail: who did what, to what, when, from where, and what changed - and it can't be rewritten."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app.core import clock
from app.core.database import engine
from app.models import AuditLog
from app.models.audit import AUDIT_TRIGGERS, DROP_AUDIT_TRIGGERS
from app.services import audit_service
from tests.conftest import PASSWORD, sign_in

ORDERS = "/api/v1/orders"


def _entries(db, action_prefix: str = "") -> list[AuditLog]:
    db.expire_all()
    stmt = select(AuditLog).order_by(AuditLog.id)
    if action_prefix:
        stmt = stmt.where(AuditLog.action.startswith(action_prefix))
    return list(db.scalars(stmt).all())


def test_sign_in_attempts_are_audited(client, users, otp_codes, db):
    failed = client.post("/api/v1/auth/login", json={"email": "sales@example.com", "password": "Wrong-guess-1"})
    assert failed.status_code == 401
    sign_in(client, otp_codes, "sales@example.com")

    entries = _entries(db, "auth.login")
    assert [(e.action, e.outcome) for e in entries] == [
        ("auth.login.failed", "failure"),
        ("auth.login.succeeded", "success"),
    ]
    refused, succeeded = entries
    assert refused.actor_email == "sales@example.com" and refused.details["reason"] == "INVALID_CREDENTIALS"
    assert refused.request_id == failed.headers["X-Request-ID"]
    assert succeeded.actor_id == users["sales"].id and succeeded.actor_role == "SALES"
    assert succeeded.details["mfa_method"] == "code"
    assert succeeded.ip_address and succeeded.entity_type == "session"


def test_order_lifecycle_is_audited(client, auth, customer, make_product, db):
    product = make_product(price="6000.00", stock=10)
    created = client.post(
        ORDERS,
        json={"customer_id": customer.id, "items": [{"product_id": product.id, "quantity": 2}]},
        headers=auth("sales"),
    )
    order_id = created.json()["id"]
    client.post(f"{ORDERS}/{order_id}/approve", json={"comment": "Fine"}, headers=auth("manager"))

    created_entry, approved = _entries(db, "order.")
    assert (created_entry.action, created_entry.entity_id) == ("order.created", str(order_id))
    assert created_entry.details["status"] == "PENDING_APPROVAL" and created_entry.details["total_amount"] == 12000.0
    assert created_entry.request_id == created.headers["X-Request-ID"]
    assert (approved.action, approved.actor_role, approved.details["comment"]) == ("order.approved", "MANAGER", "Fine")


def test_user_changes_record_old_and_new_values_but_never_passwords(client, auth, users, db):
    admin = auth("admin")
    client.patch(f"/api/v1/users/{users['sales'].id}", json={"role": "MANAGER"}, headers=admin)
    client.patch(f"/api/v1/users/{users['sales'].id}", json={"password": "Rotated-Pass-77"}, headers=admin)

    role_change, password_change = _entries(db, "user.updated")
    assert role_change.changes == {"role": {"old": "SALES", "new": "MANAGER"}}
    assert role_change.actor_email == "admin@example.com" and role_change.entity_id == str(users["sales"].id)
    assert password_change.details["password_reset_by_admin"] is True
    raw = db.execute(text("SELECT CAST(changes AS CHAR), CAST(details AS CHAR) FROM audit_logs")).all()
    assert not any("Rotated-Pass-77" in (value or "") for row in raw for value in row)


def test_business_setting_changes_are_audited(client, auth, db):
    client.put("/api/v1/settings", json={"approval_threshold": 25000}, headers=auth("admin"))
    (entry,) = _entries(db, "settings.")
    assert entry.changes == {"approval_threshold": {"old": 10000.0, "new": 25000.0}}


def test_access_denials_are_audited(client, auth, users, db):
    response = client.get("/api/v1/users", headers=auth("sales"))
    assert response.status_code == 403
    (entry,) = _entries(db, "access.denied")
    assert entry.outcome == "denied" and entry.actor_id == users["sales"].id
    assert entry.details["path"] == "/api/v1/users" and entry.request_id == response.headers["X-Request-ID"]


def test_the_audit_log_api_is_admin_only_and_filterable(client, auth, users, otp_codes):
    sign_in(client, otp_codes, "manager@example.com")
    assert client.get("/api/v1/audit-logs", headers=auth("manager")).status_code == 403
    logins = client.get("/api/v1/audit-logs", params={"action": "auth.login"}, headers=auth("admin")).json()
    assert logins["total"] >= 2 and {e["action"] for e in logins["items"]} == {"auth.login.succeeded"}
    mine = client.get("/api/v1/audit-logs", params={"actor_id": users["manager"].id}, headers=auth("admin")).json()
    assert {e["actor_email"] for e in mine["items"]} == {"manager@example.com"}


def test_audit_export_is_csv_with_formulas_neutralised(client, auth, db):
    audit_service.record_now("test.injection", actor_email='=HYPERLINK("http://evil")', details={"x": "+1"})
    response = client.get("/api/v1/audit-logs/export", params={"action": "test."}, headers=auth("admin"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    body = response.text
    assert body.splitlines()[0].startswith("id,occurred_at,actor_id")
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body
    assert _entries(db, "audit.exported")  # exporting is itself audited


@pytest.fixture
def append_only_triggers():
    with engine.begin() as conn:
        for statement in DROP_AUDIT_TRIGGERS:
            conn.execute(text(statement))
        for statement in AUDIT_TRIGGERS:
            conn.execute(text(statement))
    yield
    with engine.begin() as conn:
        for statement in DROP_AUDIT_TRIGGERS:
            conn.execute(text(statement))


def test_audit_entries_cannot_be_rewritten_or_deleted(append_only_triggers, db):
    recent = audit_service.record(db, "test.immutable")
    old = audit_service.record(db, "test.expired")
    old.occurred_at = clock.utcnow() - timedelta(days=500)
    db.commit()

    with pytest.raises(DatabaseError, match="append-only"):
        db.execute(text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"), {"id": recent.id})
    db.rollback()
    with pytest.raises(DatabaseError, match="retention"):
        db.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": recent.id})
    db.rollback()
    # Past the retention period, the scheduled purge may delete
    db.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": old.id})
    db.commit()
    assert [e.action for e in _entries(db, "test.")] == ["test.immutable"]


def test_audit_trail_survives_a_failed_request(client, users, db):
    """Failed sign-ins are written in their own transaction, so the refusal can't erase its own record."""
    for _ in range(2):
        client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert len(_entries(db, "auth.login.failed")) == 2
