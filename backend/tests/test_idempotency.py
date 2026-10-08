"""Idempotency-Key: a retried POST returns the original result instead of creating a duplicate."""

import threading

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models import InventoryTransaction, Product, SalesOrder, User
from app.schemas.order import OrderCreate, OrderItemIn
from app.services import order_service
from app.services.idempotency_service import IdempotencyClaim

ORDERS = "/api/v1/orders"


def _order_body(customer, product, qty=1) -> dict:
    return {"customer_id": customer.id, "items": [{"product_id": product.id, "quantity": qty}]}


def _count(db, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


def test_retrying_with_the_same_key_returns_the_original_order(client, auth, customer, make_product, db):
    product = make_product(stock=10)
    headers = {**auth("sales"), "Idempotency-Key": "order-7c9e6679-7425-40de"}
    first = client.post(ORDERS, json=_order_body(customer, product, 2), headers=headers)
    retry = client.post(ORDERS, json=_order_body(customer, product, 2), headers=headers)

    assert first.status_code == retry.status_code == 201
    assert retry.json()["id"] == first.json()["id"]
    assert retry.headers["Idempotent-Replayed"] == "true" and "Idempotent-Replayed" not in first.headers
    assert _count(db, SalesOrder) == 1
    assert db.get(Product, product.id).stock_qty == 8  # deducted once


def test_reusing_a_key_for_a_different_request_is_refused(client, auth, customer, make_product):
    product = make_product(stock=10)
    headers = {**auth("sales"), "Idempotency-Key": "order-key-reused-001"}
    client.post(ORDERS, json=_order_body(customer, product, 1), headers=headers)
    response = client.post(ORDERS, json=_order_body(customer, product, 3), headers=headers)
    assert response.status_code == 422 and response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_keys_belong_to_one_user(client, auth, customer, make_product, db):
    product = make_product(stock=10)
    key = {"Idempotency-Key": "shared-key-0000001"}
    a = client.post(ORDERS, json=_order_body(customer, product), headers={**auth("sales"), **key}).json()
    b = client.post(ORDERS, json=_order_body(customer, product), headers={**auth("sales2"), **key}).json()
    assert a["id"] != b["id"] and _count(db, SalesOrder) == 2


@pytest.mark.parametrize("key", ["short", "has spaces in it", "x" * 300])
def test_malformed_keys_are_refused(client, auth, customer, make_product, key):
    product = make_product(stock=10)
    response = client.post(
        ORDERS, json=_order_body(customer, product), headers={**auth("sales"), "Idempotency-Key": key}
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"


def test_stock_adjustments_are_applied_once(client, auth, make_product, db):
    product = make_product(stock=10)
    headers = {**auth("manager"), "Idempotency-Key": "restock-2026-10-07-a"}
    url = f"/api/v1/products/{product.id}/stock-adjustments"
    first = client.post(url, json={"txn_type": "RESTOCK", "quantity": 5}, headers=headers)
    retry = client.post(url, json={"txn_type": "RESTOCK", "quantity": 5}, headers=headers)
    assert retry.json()["id"] == first.json()["id"] and retry.headers["Idempotent-Replayed"] == "true"
    db.expire_all()
    assert db.get(Product, product.id).stock_qty == 15
    assert _count(db, InventoryTransaction) == 2  # opening stock + one restock


@pytest.mark.parametrize("stock", [1, 10], ids=["last-stock-unit", "stock-remaining"])
def test_concurrent_retries_with_one_key_create_one_order(users, customer, make_product, db, stock):
    """Two copies of the same request racing each other: the unique key index lets exactly one commit."""
    product = make_product(stock=stock)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    data = OrderCreate(customer_id=customer.id, items=[OrderItemIn(product_id=product.id, quantity=1)])

    def submit():
        with SessionLocal() as session:
            user = session.get(User, users["sales"].id)
            claim = IdempotencyClaim(user.id, "POST /orders", "race-key-12345678", "f" * 64)
            barrier.wait()
            try:
                order_service.create_order(session, data, user, idempotency=claim)
                outcomes.append("created")
            except IntegrityError:
                outcomes.append("duplicate")

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["created", "duplicate"]
    assert _count(db, SalesOrder) == 1
    assert db.get(Product, product.id).stock_qty == stock - 1
