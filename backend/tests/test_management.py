"""User, customer and product management, plus order/ledger list filters."""

from datetime import date, timedelta

from tests.conftest import PASSWORD

ORDERS = "/api/v1/orders"


def _order(client, headers, customer, product, qty=1):
    payload = {"customer_id": customer.id, "items": [{"product_id": product.id, "quantity": qty}]}
    return client.post(ORDERS, json=payload, headers=headers).json()


# ------------------------------------------------------------------ users


def test_admin_manages_users_end_to_end(client, auth):
    created = client.post(
        "/api/v1/users",
        json={"name": "Priya Patel", "email": "Priya@Example.com", "password": "Welcome2Sims", "role": "SALES"},
        headers=auth("admin"),
    )
    assert created.status_code == 201
    user = created.json()
    assert user["email"] == "priya@example.com"
    assert "password" not in user and "password_hash" not in user

    duplicate = client.post(
        "/api/v1/users",
        json={"name": "Again", "email": "priya@example.com", "password": "Welcome2Sims", "role": "SALES"},
        headers=auth("admin"),
    )
    assert duplicate.status_code == 409

    login = client.post("/api/v1/auth/login", json={"email": "priya@example.com", "password": "Welcome2Sims"})
    assert login.status_code == 200

    managers = client.get("/api/v1/users?role=MANAGER", headers=auth("admin")).json()
    assert [u["email"] for u in managers["items"]] == ["manager@example.com"]

    promoted = client.patch(f"/api/v1/users/{user['id']}", json={"role": "MANAGER"}, headers=auth("admin"))
    assert promoted.json()["role"] == "MANAGER"

    client.patch(f"/api/v1/users/{user['id']}", json={"password": "NewSecret456"}, headers=auth("admin"))
    old = client.post("/api/v1/auth/login", json={"email": "priya@example.com", "password": "Welcome2Sims"})
    new = client.post("/api/v1/auth/login", json={"email": "priya@example.com", "password": "NewSecret456"})
    assert (old.status_code, new.status_code) == (401, 200)

    client.patch(f"/api/v1/users/{user['id']}", json={"is_active": False}, headers=auth("admin"))
    disabled = client.post("/api/v1/auth/login", json={"email": "priya@example.com", "password": "NewSecret456"})
    assert disabled.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_unknown_user_returns_404(client, auth):
    assert client.patch("/api/v1/users/9999", json={"name": "Ghost"}, headers=auth("admin")).status_code == 404


# ------------------------------------------------------------------ customers


def test_customer_search_update_and_reactivation(client, auth):
    first = client.post(
        "/api/v1/customers", json={"name": "Northwind Traders", "email": "nw@example.com"}, headers=auth("sales")
    ).json()
    client.post("/api/v1/customers", json={"name": "Contoso Ltd", "email": "c@example.com"}, headers=auth("sales"))

    found = client.get("/api/v1/customers?search=north", headers=auth("sales")).json()
    assert [c["name"] for c in found["items"]] == ["Northwind Traders"]

    clash = client.patch(f"/api/v1/customers/{first['id']}", json={"email": "c@example.com"}, headers=auth("sales"))
    assert clash.status_code == 409

    updated = client.patch(
        f"/api/v1/customers/{first['id']}", json={"phone": "+91 98765 43210"}, headers=auth("sales")
    ).json()
    assert updated["phone"] == "+91 98765 43210"
    assert client.get(f"/api/v1/customers/{first['id']}", headers=auth("sales")).json()["phone"] == "+91 98765 43210"

    client.delete(f"/api/v1/customers/{first['id']}", headers=auth("manager"))
    active = client.get("/api/v1/customers?is_active=true", headers=auth("sales")).json()
    assert [c["name"] for c in active["items"]] == ["Contoso Ltd"]
    revived = client.patch(f"/api/v1/customers/{first['id']}", json={"is_active": True}, headers=auth("manager"))
    assert revived.json()["is_active"] is True

    assert client.get("/api/v1/customers/9999", headers=auth("sales")).status_code == 404


# ------------------------------------------------------------------ products


def test_product_edit_sku_conflict_and_deactivation(client, auth, make_product, customer):
    lamp = make_product(sku="LAMP-1", price="500.00", stock=10)
    make_product(sku="DESK-1")

    clash = client.patch(f"/api/v1/products/{lamp.id}", json={"sku": "desk-1"}, headers=auth("manager"))
    assert clash.status_code == 409

    edited = client.patch(
        f"/api/v1/products/{lamp.id}", json={"unit_price": 650, "name": "Desk Lamp"}, headers=auth("manager")
    ).json()
    assert (edited["unit_price"], edited["name"]) == (650.0, "Desk Lamp")
    assert client.get(f"/api/v1/products/{lamp.id}", headers=auth("sales")).json()["unit_price"] == 650.0

    assert client.delete(f"/api/v1/products/{lamp.id}", headers=auth("manager")).json()["is_active"] is False
    active = client.get("/api/v1/products?is_active=true", headers=auth("sales")).json()
    assert "LAMP-1" not in [p["sku"] for p in active["items"]]
    order = client.post(
        ORDERS,
        json={"customer_id": customer.id, "items": [{"product_id": lamp.id, "quantity": 1}]},
        headers=auth("sales"),
    )
    assert order.json()["error"]["code"] == "PRODUCT_INACTIVE"

    found = client.get("/api/v1/products?search=lamp", headers=auth("sales")).json()
    assert [p["sku"] for p in found["items"]] == ["LAMP-1"]
    assert client.get("/api/v1/products/9999", headers=auth("sales")).status_code == 404


# ------------------------------------------------------------------ order & ledger filters


def test_order_list_filters(client, auth, customer, make_product):
    cheap = make_product(sku="CHEAP-1", price="100.00", stock=50)
    pricey = make_product(sku="PRICEY-1", price="6000.00", stock=50)
    done = _order(client, auth("sales"), customer, cheap)
    pending = _order(client, auth("sales2"), customer, pricey, qty=2)
    by_manager = _order(client, auth("manager"), customer, cheap)

    def ids(query, who="manager"):
        return {o["id"] for o in client.get(f"{ORDERS}?{query}", headers=auth(who)).json()["items"]}

    assert ids("status=COMPLETED") == {done["id"], by_manager["id"]}
    assert ids("status=PENDING_APPROVAL") == {pending["id"]}
    assert ids(f"search={pending['order_number']}") == {pending["id"]}
    assert ids("search=acme") == {done["id"], pending["id"], by_manager["id"]}
    assert ids("mine=true") == {by_manager["id"]}
    assert ids("") == {done["id"], pending["id"], by_manager["id"]}
    assert ids("", who="sales2") == {pending["id"]}

    today = date.today()
    assert len(ids(f"date_from={today - timedelta(days=1)}&date_to={today + timedelta(days=1)}")) == 3
    assert ids(f"date_from={today + timedelta(days=2)}") == set()


def test_manager_can_cancel_but_completed_orders_cannot_be_cancelled(client, auth, customer, make_product):
    pricey = make_product(sku="PRICEY-2", price="6000.00", stock=50)
    cheap = make_product(sku="CHEAP-2", price="10.00", stock=50)
    pending = _order(client, auth("sales"), customer, pricey, qty=2)
    done = _order(client, auth("sales"), customer, cheap)

    cancelled = client.post(f"{ORDERS}/{pending['id']}/cancel", headers=auth("manager"))
    assert cancelled.json()["status"] == "CANCELLED"
    too_late = client.post(f"{ORDERS}/{done['id']}/cancel", headers=auth("sales"))
    assert too_late.status_code == 409
    assert client.get(f"{ORDERS}/9999", headers=auth("manager")).status_code == 404


def test_ledger_filter_by_type(client, auth, make_product, customer):
    product = make_product(sku="LEDGER-1", price="10.00", stock=20)
    _order(client, auth("sales"), customer, product, qty=3)
    client.post(
        f"/api/v1/products/{product.id}/stock-adjustments",
        json={"txn_type": "RESTOCK", "quantity": 5},
        headers=auth("manager"),
    )
    sales = client.get("/api/v1/inventory/transactions?txn_type=SALE", headers=auth("sales")).json()
    assert [(t["qty_change"], t["balance_after"]) for t in sales["items"]] == [(-3, 17)]
    everything = client.get(f"/api/v1/inventory/transactions?product_id={product.id}", headers=auth("sales")).json()
    assert [t["txn_type"] for t in everything["items"]] == ["RESTOCK", "SALE", "OPENING"]


def test_health_endpoint(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_no_password_only_sign_in_route_exists(client, users):
    """Swagger uses a pasted bearer token; there is no form login that could skip the one-time code."""
    form_login = client.post("/api/v1/auth/token", data={"username": "admin@example.com", "password": PASSWORD})
    assert form_login.status_code in (404, 415)  # no such route; form bodies are refused outright anyway
    assert "/api/v1/auth/token" not in client.get("/openapi.json").json()["paths"]
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert [scheme["scheme"] for scheme in schemes.values()] == ["bearer"]
