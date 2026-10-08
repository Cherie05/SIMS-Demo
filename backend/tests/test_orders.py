"""Order creation, validation, approval workflow, inventory updates and email notifications.

Threshold in tests is 10,000 with 0% tax (see conftest.users).
"""

import smtplib
import threading
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.core.exceptions import InsufficientStockError
from app.models import ApprovalStatus, EmailLog, EmailStatus, OrderStatus, OutboxJob, Product, User
from app.schemas.order import OrderCreate, OrderItemIn
from app.services import email_service, order_service

ORDERS = "/api/v1/orders"


def place(client, headers, customer, *items):
    payload = {"customer_id": customer.id, "items": [{"product_id": p.id, "quantity": q} for p, q in items]}
    return client.post(ORDERS, json=payload, headers=headers)


def stock_of(db, product) -> int:
    db.expire_all()
    return db.get(Product, product.id).stock_qty


# ------------------------------------------------------------------ orders under the threshold


def test_small_order_is_auto_approved_and_deducts_stock(
    client, auth, db, customer, make_product, sent_emails, run_jobs
):
    product = make_product(price="1000.00", stock=10)
    response = place(client, auth("sales"), customer, (product, 3))

    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "COMPLETED"
    assert order["requires_approval"] is False
    assert order["total_amount"] == 3000.0
    assert order["approval"] is None
    assert [h["to_status"] for h in order["history"]] == ["APPROVED", "COMPLETED"]
    assert stock_of(db, product) == 7
    run_jobs()
    assert sent_emails == []

    ledger = client.get(f"/api/v1/inventory/transactions?product_id={product.id}", headers=auth("sales")).json()
    sale = ledger["items"][0]
    assert (sale["txn_type"], sale["qty_change"], sale["balance_after"], sale["order_id"]) == (
        "SALE",
        -3,
        7,
        order["id"],
    )


def test_order_exactly_at_threshold_does_not_need_approval(client, auth, customer, make_product):
    product = make_product(price="5000.00", stock=10)
    response = place(client, auth("sales"), customer, (product, 2))  # 10,000 == threshold
    assert response.json()["status"] == "COMPLETED"


def test_totals_include_tax_and_use_price_snapshot(client, auth, db, customer, make_product):
    from app.models import AppSetting

    db.get(AppSetting, "tax_rate").value = "18"
    db.commit()
    product = make_product(price="99.99", stock=10)
    order = place(client, auth("sales"), customer, (product, 3)).json()
    assert order["subtotal"] == 299.97
    assert order["tax_amount"] == 53.99  # 299.97 * 18% = 53.9946 -> 53.99
    assert order["total_amount"] == 353.96

    client.patch(f"/api/v1/products/{product.id}", json={"unit_price": 150}, headers=auth("manager"))
    again = client.get(f"{ORDERS}/{order['id']}", headers=auth("sales")).json()
    assert again["items"][0]["unit_price"] == 99.99


# ------------------------------------------------------------------ approval workflow


def test_large_order_waits_for_approval_and_emails_manager(
    client, auth, db, customer, make_product, sent_emails, run_jobs
):
    product = make_product(price="6000.00", stock=10)
    response = place(client, auth("sales"), customer, (product, 2))  # 12,000 > 10,000

    order = response.json()
    assert order["status"] == "PENDING_APPROVAL"
    assert order["requires_approval"] is True
    assert order["approval"]["status"] == "PENDING"
    assert order["approval"]["threshold_amount"] == 10000.0
    assert stock_of(db, product) == 10  # untouched until approved
    # The email is queued with the order (transactional outbox) and sent by the worker.
    assert [(e["status"], e["to_email"]) for e in order["emails"]] == [("QUEUED", "manager@example.com")]
    assert sent_emails == []
    run_jobs()

    assert len(sent_emails) == 1
    assert sent_emails[0]["To"] == "manager@example.com"
    assert order["order_number"] in sent_emails[0]["Subject"]
    log = db.query(EmailLog).one()
    assert (log.status, log.template, log.order_id) == (EmailStatus.SENT, "approval_request", order["id"])

    queue = client.get("/api/v1/approvals", headers=auth("manager")).json()
    assert [a["order"]["id"] for a in queue["items"]] == [order["id"]]


def test_manager_approval_deducts_stock_completes_order_and_notifies_creator(
    client, auth, db, customer, make_product, sent_emails, run_jobs
):
    product = make_product(price="6000.00", stock=10)
    order_id = place(client, auth("sales"), customer, (product, 2)).json()["id"]
    run_jobs()
    sent_emails.clear()

    response = client.post(f"{ORDERS}/{order_id}/approve", json={"comment": "OK"}, headers=auth("manager"))

    assert response.status_code == 200
    order = response.json()
    assert order["status"] == "COMPLETED"
    assert order["completed_at"] is not None
    assert order["approval"]["status"] == "APPROVED"
    assert order["approval"]["decided_by"]["email"] == "manager@example.com"
    assert [h["to_status"] for h in order["history"]] == ["PENDING_APPROVAL", "APPROVED", "COMPLETED"]
    assert stock_of(db, product) == 8

    run_jobs()
    assert [m["To"] for m in sent_emails] == ["sales@example.com"]
    assert "approved" in sent_emails[0]["Subject"]


def test_rejection_requires_reason_keeps_stock_and_notifies_creator(
    client, auth, db, customer, make_product, sent_emails, run_jobs
):
    product = make_product(price="6000.00", stock=10)
    order_id = place(client, auth("sales"), customer, (product, 2)).json()["id"]
    run_jobs()
    sent_emails.clear()

    no_reason = client.post(f"{ORDERS}/{order_id}/reject", json={}, headers=auth("manager"))
    assert no_reason.status_code == 422

    response = client.post(f"{ORDERS}/{order_id}/reject", json={"comment": "Price too low"}, headers=auth("manager"))
    order = response.json()
    assert order["status"] == "REJECTED"
    assert order["approval"]["comment"] == "Price too low"
    assert stock_of(db, product) == 10
    run_jobs()
    assert [m["To"] for m in sent_emails] == ["sales@example.com"]
    assert "rejected" in sent_emails[0]["Subject"]


def test_order_cannot_be_decided_twice(client, auth, customer, make_product):
    product = make_product(price="6000.00", stock=10)
    order_id = place(client, auth("sales"), customer, (product, 2)).json()["id"]
    client.post(f"{ORDERS}/{order_id}/approve", headers=auth("manager"))

    again = client.post(f"{ORDERS}/{order_id}/approve", headers=auth("admin"))
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ORDER_NOT_PENDING"
    reject = client.post(f"{ORDERS}/{order_id}/reject", json={"comment": "late"}, headers=auth("admin"))
    assert reject.status_code == 409


def test_sales_user_cannot_approve(client, auth, customer, make_product):
    product = make_product(price="6000.00", stock=10)
    order_id = place(client, auth("sales"), customer, (product, 2)).json()["id"]
    response = client.post(f"{ORDERS}/{order_id}/approve", headers=auth("sales2"))
    assert response.status_code == 403


def test_manager_cannot_approve_own_order(client, auth, customer, make_product):
    product = make_product(price="6000.00", stock=10)
    order_id = place(client, auth("manager"), customer, (product, 2)).json()["id"]
    response = client.post(f"{ORDERS}/{order_id}/approve", headers=auth("manager"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SELF_APPROVAL_NOT_ALLOWED"
    # ...but another approver can
    assert client.post(f"{ORDERS}/{order_id}/approve", headers=auth("admin")).status_code == 200


def test_approval_fails_cleanly_when_stock_ran_out_meanwhile(client, auth, db, customer, make_product):
    product = make_product(price="6000.00", stock=3)
    big = place(client, auth("sales"), customer, (product, 2)).json()  # pending, needs 2
    place(client, auth("sales2"), customer, (product, 1))  # instant sale: 1 unit
    client.post(
        f"/api/v1/products/{product.id}/stock-adjustments",
        json={"txn_type": "ADJUSTMENT", "quantity": -1, "note": "Damaged"},
        headers=auth("manager"),
    )  # only 1 left now

    response = client.post(f"{ORDERS}/{big['id']}/approve", headers=auth("manager"))
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INSUFFICIENT_STOCK"
    assert error["details"][0]["available"] == 1

    # Whole transaction rolled back: order and approval still pending, stock untouched.
    order = client.get(f"{ORDERS}/{big['id']}", headers=auth("manager")).json()
    assert order["status"] == "PENDING_APPROVAL"
    assert order["approval"]["status"] == "PENDING"
    assert stock_of(db, product) == 1


def test_creator_can_cancel_pending_order(client, auth, customer, make_product):
    product = make_product(price="6000.00", stock=10)
    order_id = place(client, auth("sales"), customer, (product, 2)).json()["id"]

    # another sales rep can't even see the order (404, so order ids can't be probed)
    assert client.post(f"{ORDERS}/{order_id}/cancel", headers=auth("sales2")).status_code == 404
    response = client.post(
        f"{ORDERS}/{order_id}/cancel", json={"reason": "Customer changed mind"}, headers=auth("sales")
    )
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["approval"]["status"] == "CANCELLED"


# ------------------------------------------------------------------ validation


def test_insufficient_stock_is_rejected_with_details(client, auth, db, customer, make_product):
    a = make_product(sku="SKU-A", stock=5)
    b = make_product(sku="SKU-B", stock=1)
    response = place(client, auth("sales"), customer, (a, 2), (b, 4))
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INSUFFICIENT_STOCK"
    assert error["details"] == [
        {"product_id": b.id, "sku": "SKU-B", "name": "Product SKU-B", "requested": 4, "available": 1}
    ]
    assert stock_of(db, a) == 5  # nothing partially applied


@pytest.mark.parametrize(
    ("items", "field"),
    [
        ([], "items"),
        ([{"product_id": 1, "quantity": 0}], "items.0.quantity"),
        ([{"product_id": 1, "quantity": 1}, {"product_id": 1, "quantity": 2}], "items"),
    ],
)
def test_order_payload_validation(client, auth, customer, items, field):
    response = client.post(ORDERS, json={"customer_id": customer.id, "items": items}, headers=auth("sales"))
    assert response.status_code == 422
    assert field in [d["field"] for d in response.json()["error"]["details"]]


def test_inactive_customer_and_product_are_rejected(client, auth, db, customer, make_product):
    product = make_product()
    product.is_active = False
    db.commit()
    response = place(client, auth("sales"), customer, (product, 1))
    assert response.json()["error"]["code"] == "PRODUCT_INACTIVE"

    product.is_active = True
    customer.is_active = False
    db.commit()
    response = place(client, auth("sales"), customer, (product, 1))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CUSTOMER_INACTIVE"


def test_unknown_product_returns_404(client, auth, customer):
    response = client.post(
        ORDERS, json={"customer_id": customer.id, "items": [{"product_id": 999, "quantity": 1}]}, headers=auth("sales")
    )
    assert response.status_code == 404


# ------------------------------------------------------------------ visibility


def test_sales_users_only_see_their_own_orders(client, auth, customer, make_product):
    product = make_product(stock=10)
    mine = place(client, auth("sales"), customer, (product, 1)).json()
    theirs = place(client, auth("sales2"), customer, (product, 1)).json()

    listed = client.get(ORDERS, headers=auth("sales")).json()
    assert [o["id"] for o in listed["items"]] == [mine["id"]]
    # 404, not 403: other people's order ids must not be discoverable
    assert client.get(f"{ORDERS}/{theirs['id']}", headers=auth("sales")).status_code == 404
    assert client.get(ORDERS, headers=auth("manager")).json()["total"] == 2


# ------------------------------------------------------------------ resilience


def test_email_failure_does_not_affect_the_order(client, auth, db, customer, make_product, monkeypatch, run_jobs):
    def broken(_message):
        raise smtplib.SMTPServerDisconnected("mail server down")

    monkeypatch.setattr(email_service, "_deliver", broken)
    product = make_product(price="6000.00", stock=10)
    response = place(client, auth("sales"), customer, (product, 2))

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING_APPROVAL"
    run_jobs()
    # The worker keeps the email and retries it with backoff; nothing is lost and the order is unaffected.
    job = db.query(OutboxJob).one()
    assert (job.status, job.attempts) == ("RETRY", 1)
    assert "mail server down" in job.last_error
    assert db.query(EmailLog).count() == 0
    order = client.get(f"{ORDERS}/{response.json()['id']}", headers=auth("sales")).json()
    assert order["status"] == "PENDING_APPROVAL"
    assert order["emails"][0]["status"] == "QUEUED"


def test_concurrent_orders_cannot_oversell(users, customer, make_product):
    """Two simultaneous orders for 3 units each against a stock of 5: exactly one may succeed."""
    product = make_product(price="100.00", stock=5)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def buy(user_id: int):
        with SessionLocal() as session:
            user = session.get(User, user_id)
            barrier.wait()
            try:
                order_service.create_order(
                    session,
                    OrderCreate(customer_id=customer.id, items=[OrderItemIn(product_id=product.id, quantity=3)]),
                    user,
                )
                results.append("ok")
            except InsufficientStockError:
                results.append("insufficient")

    threads = [threading.Thread(target=buy, args=(users[k].id,)) for k in ("sales", "sales2")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == ["insufficient", "ok"]
    with SessionLocal() as session:
        assert session.get(Product, product.id).stock_qty == 2


def test_dashboard_reflects_orders_and_approvals(client, auth, customer, make_product):
    cheap = make_product(sku="CHEAP", price="1000.00", stock=10, reorder=8)
    pricey = make_product(sku="PRICEY", price="6000.00", stock=10)
    place(client, auth("sales"), customer, (cheap, 3))  # completed 3,000 -> stock 7 (low)
    pending = place(client, auth("sales"), customer, (pricey, 2)).json()  # pending 12,000
    rejected = place(client, auth("sales"), customer, (pricey, 3)).json()
    client.post(f"{ORDERS}/{rejected['id']}/reject", json={"comment": "Budget exceeded"}, headers=auth("manager"))

    summary = client.get("/api/v1/dashboard/summary", headers=auth("sales")).json()
    assert summary["sales"]["total_revenue"] == 3000.0
    assert summary["orders"] == {"total": 3, "pending_approval": 1, "completed": 1, "rejected": 1, "cancelled": 0}
    assert summary["approvals"]["pending"] == 1
    assert summary["approvals"]["pending_value"] == pending["total_amount"]
    assert summary["inventory"]["low_stock"] == 1

    top = client.get("/api/v1/dashboard/top-products", headers=auth("sales")).json()
    assert [(t["sku"], t["quantity_sold"]) for t in top] == [("CHEAP", 3)]
    recent = client.get("/api/v1/dashboard/top-products?days=7", headers=auth("sales")).json()
    assert [t["sku"] for t in recent] == ["CHEAP"]

    trend = client.get("/api/v1/dashboard/sales-trend?days=7", headers=auth("sales")).json()
    assert len(trend) == 7
    assert trend[-1]["revenue"] == 3000.0


def test_only_admin_can_change_threshold(client, auth):
    assert client.put("/api/v1/settings", json={"approval_threshold": 1}, headers=auth("manager")).status_code == 403
    response = client.put("/api/v1/settings", json={"approval_threshold": 25000.5}, headers=auth("admin"))
    assert response.json()["approval_threshold"] == 25000.5
    assert Decimal(str(client.get("/api/v1/settings", headers=auth("sales")).json()["approval_threshold"])) == Decimal(
        "25000.5"
    )


def test_approval_status_filter(client, auth, customer, make_product):
    product = make_product(price="6000.00", stock=10)
    first = place(client, auth("sales"), customer, (product, 2)).json()
    place(client, auth("sales"), customer, (product, 2))
    client.post(f"{ORDERS}/{first['id']}/approve", headers=auth("manager"))

    approved = client.get("/api/v1/approvals?status=APPROVED", headers=auth("manager")).json()
    assert [a["order"]["id"] for a in approved["items"]] == [first["id"]]
    assert approved["items"][0]["status"] == ApprovalStatus.APPROVED.value
    assert client.get("/api/v1/approvals?status=PENDING", headers=auth("manager")).json()["total"] == 1
    assert client.get("/api/v1/approvals", headers=auth("manager")).json()["total"] == 2
    assert OrderStatus.PENDING_APPROVAL.value == "PENDING_APPROVAL"
