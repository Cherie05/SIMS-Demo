"""Feature flags / kill switches: switch capabilities off during an incident without a deploy."""

from sqlalchemy import select

from app.models import AuditLog

ORDERS = "/api/v1/orders"


def test_order_intake_can_be_paused_and_resumed(client, auth, customer, make_product, db):
    product = make_product(stock=10)
    body = {"customer_id": customer.id, "items": [{"product_id": product.id, "quantity": 1}]}

    off = client.put("/api/v1/feature-flags/orders.create", json={"enabled": False}, headers=auth("admin"))
    assert off.json() == {**off.json(), "name": "orders.create", "enabled": False, "default": True}
    paused = client.post(ORDERS, json=body, headers=auth("sales"))
    assert paused.status_code == 503 and paused.json()["error"]["code"] == "FEATURE_DISABLED"
    assert paused.headers["Retry-After"]

    client.put("/api/v1/feature-flags/orders.create", json={"enabled": True}, headers=auth("admin"))
    assert client.post(ORDERS, json=body, headers=auth("sales")).status_code == 201
    changes = db.scalars(select(AuditLog.changes).where(AuditLog.action == "feature_flag.updated")).all()
    assert changes == [{"enabled": {"old": True, "new": False}}, {"enabled": {"old": False, "new": True}}]


def test_everyone_can_read_flags_but_only_admins_change_them(client, auth):
    flags = client.get("/api/v1/feature-flags", headers=auth("sales")).json()
    assert {f["name"] for f in flags} == {"orders.create", "auth.signup", "notifications.email"}
    assert all(f["enabled"] for f in flags)
    denied = client.put("/api/v1/feature-flags/orders.create", json={"enabled": False}, headers=auth("manager"))
    assert denied.status_code == 403
    unknown = client.put("/api/v1/feature-flags/does.not.exist", json={"enabled": False}, headers=auth("admin"))
    assert unknown.status_code == 404


def test_self_sign_up_has_a_kill_switch(client, auth):
    client.put("/api/v1/feature-flags/auth.signup", json={"enabled": False}, headers=auth("admin"))
    assert client.get("/api/v1/auth/config").json()["signup_enabled"] is False
    response = client.post(
        "/api/v1/auth/signup",
        json={"name": "New Person", "email": "new.person@example.com", "password": "Fresh-Pass-42"},
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "SIGNUP_DISABLED"
