def test_create_product_records_opening_stock_in_ledger(client, auth):
    response = client.post(
        "/api/v1/products",
        json={"sku": "lap-1", "name": "Laptop", "unit_price": 50000, "opening_stock": 12, "reorder_level": 3},
        headers=auth("manager"),
    )
    assert response.status_code == 201
    product = response.json()
    assert product["sku"] == "LAP-1"
    assert product["stock_qty"] == 12

    ledger = client.get(f"/api/v1/inventory/transactions?product_id={product['id']}", headers=auth("sales")).json()
    assert ledger["total"] == 1
    assert ledger["items"][0]["txn_type"] == "OPENING"
    assert ledger["items"][0]["balance_after"] == 12


def test_duplicate_sku_conflicts(client, auth, make_product):
    make_product(sku="DUP-1")
    response = client.post(
        "/api/v1/products", json={"sku": "dup-1", "name": "Other", "unit_price": 1}, headers=auth("manager")
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_SKU"


def test_product_validation_errors_are_reported_per_field(client, auth):
    response = client.post(
        "/api/v1/products", json={"sku": "bad sku!", "name": "X", "unit_price": -5}, headers=auth("manager")
    )
    assert response.status_code == 422
    fields = {detail["field"] for detail in response.json()["error"]["details"]}
    assert {"sku", "name", "unit_price"} <= fields


def test_stock_cannot_be_edited_directly(client, auth, make_product):
    product = make_product()
    response = client.patch(f"/api/v1/products/{product.id}", json={"stock_qty": 999}, headers=auth("manager"))
    assert response.status_code == 422


def test_restock_and_adjustment(client, auth, make_product):
    product = make_product(stock=5)
    url = f"/api/v1/products/{product.id}/stock-adjustments"

    restock = client.post(url, json={"txn_type": "RESTOCK", "quantity": 20}, headers=auth("manager"))
    assert restock.status_code == 201
    assert restock.json()["balance_after"] == 25

    no_note = client.post(url, json={"txn_type": "ADJUSTMENT", "quantity": -3}, headers=auth("manager"))
    assert no_note.status_code == 422

    damaged = client.post(
        url, json={"txn_type": "ADJUSTMENT", "quantity": -3, "note": "Damaged in transit"}, headers=auth("manager")
    )
    assert damaged.json()["balance_after"] == 22

    too_many = client.post(
        url, json={"txn_type": "ADJUSTMENT", "quantity": -100, "note": "Write-off"}, headers=auth("manager")
    )
    assert too_many.status_code == 400
    assert too_many.json()["error"]["code"] == "NEGATIVE_STOCK"


def test_low_stock_filter(client, auth, make_product):
    make_product(sku="OK-1", stock=50, reorder=5)
    make_product(sku="LOW-1", stock=3, reorder=5)
    response = client.get("/api/v1/products?low_stock=true", headers=auth("sales")).json()
    assert [p["sku"] for p in response["items"]] == ["LOW-1"]
    assert response["items"][0]["is_low_stock"] is True


def test_customer_crud_and_duplicate_email(client, auth):
    payload = {"name": "Globex", "email": "Buyer@Globex.example.com", "phone": "+91 90000 12345"}
    created = client.post("/api/v1/customers", json=payload, headers=auth("sales"))
    assert created.status_code == 201
    assert created.json()["email"] == "buyer@globex.example.com"

    duplicate = client.post("/api/v1/customers", json=payload, headers=auth("sales"))
    assert duplicate.status_code == 409

    bad_phone = client.post(
        "/api/v1/customers", json={**payload, "email": "x@globex.example.com", "phone": "abc"}, headers=auth("sales")
    )
    assert bad_phone.status_code == 422

    customer_id = created.json()["id"]
    assert client.delete(f"/api/v1/customers/{customer_id}", headers=auth("sales")).status_code == 403
    sneaky = client.patch(f"/api/v1/customers/{customer_id}", json={"is_active": False}, headers=auth("sales"))
    assert sneaky.status_code == 403
    deactivated = client.delete(f"/api/v1/customers/{customer_id}", headers=auth("manager"))
    assert deactivated.json()["is_active"] is False
