"""Acceptance tests for the assignment brief, one step per requirement, through the real UI.

The steps run in order and build on each other (the product created in step 2 is ordered in
step 5, and so on). Quoted lines are the requirements from the brief.
"""

import re
from decimal import Decimal

import httpx
import pytest
from playwright.sync_api import Page, expect

from conftest import (
    API_BASE_URL,
    BASE_URL,
    TLS_VERIFY,
    USER_PASSWORD,
    Api,
    Mailbox,
    World,
    codes_so_far,
    new_page,
    read_new_code,
)

ORDER_URL = re.compile(r"/orders/(\d+)$")
ORDER_NUMBER = re.compile(r"^SO-\d{8}-[0-9A-F]{6}$")


def _open_new_order(page: Page, world: World, quantity: int, with_customer: bool = True) -> None:
    page.goto(f"{BASE_URL}/orders/new")
    if with_customer:
        # role=combobox: once open, the suggestion list carries the same label as the input
        page.get_by_role("combobox", name="Search customers").fill(world.customer_name)
        page.get_by_role("option", name=re.compile(world.customer_name)).click()
    product = page.get_by_role("combobox", name="Product")
    product.click()
    product.fill(world.sku)
    page.get_by_role("option", name=re.compile(world.sku)).click()
    page.get_by_label("Qty").fill(str(quantity))


def _submit_order(page: Page) -> dict:
    page.locator("button[type=submit]").click()
    page.wait_for_url(ORDER_URL)
    order_id = int(ORDER_URL.search(page.url).group(1))
    heading = page.get_by_role("heading", level=1)
    expect(heading).to_have_text(ORDER_NUMBER)  # the URL changes before the order page has rendered
    return {"id": order_id, "number": heading.inner_text().strip()}


def _stock(api: Api, world: World) -> int:
    return api.get(f"/products/{world.product_id}")["stock_qty"]


# ----------------------------------------------------------------------------------------------


def test_01_users_sign_in_and_roles_are_enforced(anonymous_page: Page, sales_page: Page, world: World):
    """Authentication: protected pages need a sign-in, and each role only sees what it may use."""
    anonymous_page.goto(f"{BASE_URL}/orders/new")
    expect(anonymous_page).to_have_url(re.compile(r"/login$"))
    anonymous_page.get_by_label("Email").fill(world.sales_email)
    anonymous_page.get_by_label("Password", exact=True).fill("not-the-password1")
    anonymous_page.get_by_role("button", name="Continue").click()
    expect(anonymous_page.get_by_text("Invalid email or password")).to_be_visible()

    sales_page.goto(f"{BASE_URL}/approvals")  # managers only
    expect(sales_page).to_have_url(f"{BASE_URL}/")
    expect(sales_page.get_by_role("link", name="Approvals")).to_have_count(0)
    expect(sales_page.get_by_role("link", name="Settings")).to_have_count(0)


def test_02_manage_products(manager_page: Page, admin_api: Api, world: World):
    """'The application should allow users to manage products...'"""
    page = manager_page
    page.goto(f"{BASE_URL}/products")
    page.get_by_role("button", name="Add product").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("SKU").fill(world.sku)
    dialog.get_by_label("Name").fill(world.product_name)
    dialog.get_by_label("Unit price").fill(str(world.unit_price))
    dialog.get_by_label("Reorder level").fill("2")
    dialog.get_by_label("Opening stock").fill("10")
    dialog.get_by_role("button", name="Create product").click()
    expect(page.get_by_text(f"{world.product_name} created")).to_be_visible()

    product = admin_api.get("/products", search=world.sku)["items"][0]
    world.product_id = product["id"]
    assert (product["stock_qty"], Decimal(str(product["unit_price"]))) == (10, world.unit_price)

    page.get_by_placeholder("Search name or SKU").fill(world.sku)
    row = page.get_by_role("row").filter(has_text=world.sku)
    row.get_by_role("button", name="Edit").click()
    dialog.get_by_label("Reorder level").fill("3")
    dialog.get_by_role("button", name="Save changes").click()
    expect(page.get_by_text(f"{world.product_name} updated")).to_be_visible()
    assert admin_api.get(f"/products/{world.product_id}")["reorder_level"] == 3


def test_03_manage_customers(sales_page: Page, admin_api: Api, world: World):
    """'...and customers'"""
    page = sales_page
    page.goto(f"{BASE_URL}/customers")
    page.get_by_role("button", name="Add customer").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill(world.customer_name)
    dialog.get_by_label("Email").fill(world.customer_email)
    dialog.get_by_label("Phone").fill("+91 90000 12345")
    dialog.get_by_role("button", name="Add customer").click()
    expect(page.get_by_text(f"{world.customer_name} added")).to_be_visible()

    page.get_by_placeholder("Search name, email or phone").fill(world.customer_name)
    page.get_by_role("row").filter(has_text=world.customer_name).get_by_role("button", name="Edit").click()
    dialog.get_by_label("Address").fill("1 Acceptance Road, Hyderabad")
    dialog.get_by_role("button", name="Save changes").click()
    expect(page.get_by_text(f"{world.customer_name} updated")).to_be_visible()

    customer = admin_api.get("/customers", search=world.customer_name)["items"][0]
    world.customer_id = customer["id"]
    assert customer["address"] == "1 Acceptance Road, Hyderabad"


def test_04_order_and_stock_are_validated(sales_page: Page, sales_api: Api, admin_api: Api, world: World):
    """'When a sales order is created, the system should validate the order and stock.'"""
    _open_new_order(sales_page, world, quantity=50, with_customer=False)  # only 10 in stock
    sales_page.locator("button[type=submit]").click()
    expect(sales_page.get_by_text("Select a customer")).to_be_visible()
    expect(sales_page.get_by_text("Only 10 in stock")).to_be_visible()

    # The server enforces the same rules independently of the browser.
    item = {"product_id": world.product_id, "quantity": 50}
    too_many = sales_api.request("POST", "/orders", json={"customer_id": world.customer_id, "items": [item]})
    assert too_many.status_code == 409
    assert too_many.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert too_many.json()["error"]["details"][0]["available"] == 10
    zero = sales_api.request(
        "POST", "/orders", json={"customer_id": world.customer_id, "items": [{**item, "quantity": 0}]}
    )
    assert zero.status_code == 422

    assert admin_api.get("/orders", search=world.customer_name)["total"] == 0
    assert _stock(admin_api, world) == 10


def test_05_order_within_the_threshold_is_confirmed_immediately(
    sales_page: Page, admin_api: Api, mailbox: Mailbox, world: World
):
    """Orders up to the defined amount need no approval: stock is deducted and the order completed."""
    _open_new_order(sales_page, world, quantity=1)
    expect(sales_page.get_by_text("Within the")).to_be_visible()
    world.orders["small"] = order = _submit_order(sales_page)
    expect(sales_page.get_by_text("Completed", exact=True).first).to_be_visible()

    saved = admin_api.get(f"/orders/{order['id']}")
    assert saved["status"] == "COMPLETED" and saved["requires_approval"] is False
    assert Decimal(str(saved["total_amount"])) == world.order_total(1)
    assert _stock(admin_api, world) == 9
    assert mailbox.subjects_mentioning(order["number"]) == []


def test_06_order_above_the_threshold_requires_approval_and_emails_the_manager(
    sales_page: Page, sales_api: Api, admin_api: Api, mailbox: Mailbox, world: World
):
    """'Orders above a defined amount should require manager approval before they can be confirmed.'
    'The system should send an email notification to the manager when approval is required.'"""
    _open_new_order(sales_page, world, quantity=2)
    expect(sales_page.get_by_text("Manager approval required")).to_be_visible()
    world.orders["approved"] = order = _submit_order(sales_page)
    expect(sales_page.get_by_text("Pending Approval").first).to_be_visible()
    expect(sales_page.get_by_text("waiting for a manager")).to_be_visible()

    assert admin_api.get(f"/orders/{order['id']}")["status"] == "PENDING_APPROVAL"
    assert _stock(admin_api, world) == 9  # nothing deducted before approval
    assert sales_api.request("POST", f"/orders/{order['id']}/approve").status_code == 403  # not a manager

    email = mailbox.wait_for(to=world.manager_email, subject_contains=order["number"])
    assert email["Subject"].startswith("Approval required")
    link = re.search(r'href="([^"]+/orders/(\d+))"', mailbox.html(email))
    assert link and int(link.group(2)) == order["id"], "email must link to the order"
    world.approval_link = link.group(1)


def test_07_manager_approves_from_the_email_and_inventory_is_updated(manager_page: Page, admin_api: Api, world: World):
    """'The manager should be able to approve...' 'Once an order is approved, the system should
    update the inventory and complete the order.'"""
    order = world.orders["approved"]
    manager_page.goto(world.approval_link)  # exactly what the manager clicks in the email
    expect(manager_page.get_by_role("heading", level=1)).to_have_text(order["number"])
    manager_page.get_by_role("button", name="Approve", exact=True).click()
    manager_page.get_by_label("Comment (optional)").fill("Approved by the acceptance test")
    manager_page.get_by_role("button", name="Approve & complete").click()
    expect(manager_page.get_by_text("Completed", exact=True).first).to_be_visible()

    saved = admin_api.get(f"/orders/{order['id']}")
    assert saved["status"] == "COMPLETED"
    assert [h["to_status"] for h in saved["history"]] == ["PENDING_APPROVAL", "APPROVED", "COMPLETED"]
    assert _stock(admin_api, world) == 7
    ledger = admin_api.get("/inventory/transactions", product_id=world.product_id)["items"]
    assert any(t["order_id"] == order["id"] and t["txn_type"] == "SALE" and t["qty_change"] == -2 for t in ledger)


def test_08_user_is_emailed_the_approval(mailbox: Mailbox, world: World):
    """'...and the user should be notified of the decision by email.' (approved)"""
    order = world.orders["approved"]
    email = mailbox.wait_for(to=world.sales_email, subject_contains=f"Order {order['number']} approved")
    html = mailbox.html(email)
    assert "APPROVED" in html and "Approved by the acceptance test" in html


def test_09_manager_rejects_with_a_reason_and_the_user_is_emailed(
    manager_page: Page, sales_api: Api, admin_api: Api, mailbox: Mailbox, world: World
):
    """'The manager should be able to approve or reject the order' (rejected), plus the email."""
    created = sales_api.post(
        "/orders",
        {"customer_id": world.customer_id, "items": [{"product_id": world.product_id, "quantity": 2}]},
    )
    assert created["status"] == "PENDING_APPROVAL"
    world.orders["rejected"] = {"id": created["id"], "number": created["order_number"]}

    manager_page.get_by_role("link", name=re.compile(r"^Approvals\b")).click()
    expect(manager_page).to_have_url(f"{BASE_URL}/approvals")
    row = manager_page.get_by_role("row").filter(has_text=created["order_number"])
    row.get_by_role("button", name="Reject").click()
    manager_page.get_by_label("Reason for rejection").fill("Please re-quote with the bulk discount")
    manager_page.get_by_role("button", name="Reject order").click()
    # Wait for the confirmation: while the dialog is open the table is hidden from the accessibility tree.
    expect(manager_page.get_by_text(f"{created['order_number']} rejected")).to_be_visible()
    expect(manager_page.get_by_role("dialog")).to_have_count(0)
    expect(row).to_have_count(0)  # gone from the pending queue

    saved = admin_api.get(f"/orders/{created['id']}")
    assert saved["status"] == "REJECTED"
    assert saved["approval"]["comment"] == "Please re-quote with the bulk discount"
    assert _stock(admin_api, world) == 7  # a rejected order never touches stock

    email = mailbox.wait_for(to=world.sales_email, subject_contains=f"Order {created['order_number']} rejected")
    assert "Please re-quote with the bulk discount" in mailbox.html(email)


def test_10_maintain_inventory(manager_page: Page, admin_api: Api, world: World):
    """'...maintain inventory': restock through the UI, and every movement is in the stock ledger."""
    page = manager_page
    page.goto(f"{BASE_URL}/products")
    page.get_by_placeholder("Search name or SKU").fill(world.sku)
    # Keep the page mounted: identical, intentional deliveries must each apply, while a retry
    # of one delivery remains idempotent. Reloading between saves would hide a stale key bug.
    for balance in (12, 17):
        page.get_by_role("row").filter(has_text=world.sku).get_by_role("button", name="Adjust stock").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Quantity").fill("5")
        dialog.get_by_label("Note (optional)").fill("Supplier delivery")
        dialog.get_by_role("button", name="Save").click()
        expect(page.get_by_text(f"{world.sku}: stock is now {balance}")).to_be_visible()

    page.goto(f"{BASE_URL}/inventory")
    page.get_by_placeholder("All products").fill(world.sku)
    page.get_by_role("option", name=re.compile(world.sku)).click()
    ledger = page.get_by_role("region", name="Table")
    for movement in ["Restock", "+5", "Sale", "-2", "-1", "Opening", "+10"]:
        expect(ledger.get_by_text(movement, exact=True).first).to_be_visible()

    types = [t["txn_type"] for t in admin_api.get("/inventory/transactions", product_id=world.product_id)["items"]]
    assert types == ["RESTOCK", "RESTOCK", "SALE", "SALE", "OPENING"]
    assert _stock(admin_api, world) == 17


def test_11_dashboard_shows_sales_order_approval_and_inventory_information(
    manager_page: Page, admin_api: Api, world: World
):
    """'The application should also provide basic sales, order, approval, and inventory information
    through a dashboard.'"""
    before, after = world.dashboard_before, admin_api.get("/dashboard/summary")
    assert after["orders"]["completed"] - before["orders"]["completed"] == 2
    assert after["orders"]["rejected"] - before["orders"]["rejected"] == 1
    assert after["approvals"]["approved"] - before["approvals"]["approved"] == 1
    assert after["approvals"]["rejected"] - before["approvals"]["rejected"] == 1
    assert after["inventory"]["active_products"] - before["inventory"]["active_products"] == 1
    revenue = Decimal(str(after["sales"]["total_revenue"])) - Decimal(str(before["sales"]["total_revenue"]))
    assert abs(revenue - (world.order_total(1) + world.order_total(2))) < Decimal("0.01")

    page = manager_page
    page.goto(f"{BASE_URL}/")
    for panel in ["Sales overview", "Orders by status", "Top products", "Low stock", "Recent orders"]:
        expect(page.get_by_role("heading", name=panel, exact=True)).to_be_visible()
    for kpi in ["Revenue", "Completed orders", "Pending approvals", "Inventory value"]:
        expect(page.get_by_role("region", name=kpi)).to_be_visible()

    pending = page.get_by_role("region", name="Pending approvals")
    expect(pending.get_by_text(str(after["approvals"]["pending"]), exact=True)).to_be_visible()
    statuses = page.get_by_role("img", name=re.compile("orders:"))
    expect(statuses).to_have_attribute("aria-label", re.compile(rf"Completed {after['orders']['completed']}\b"))
    expect(statuses).to_have_attribute("aria-label", re.compile(rf"Rejected {after['orders']['rejected']}\b"))
    recent = page.get_by_role("region", name="Recent orders")
    for key in ("small", "approved", "rejected"):
        expect(recent.get_by_text(world.orders[key]["number"])).to_be_visible()


def test_12_no_errors_in_the_browser(browser_errors: list[str]):
    # The deliberate wrong-password attempt in step 1 makes the browser log the API's 401; nothing else may.
    unexpected = [e for e in browser_errors if not ("/login" in e and "401" in e)]
    assert unexpected == []


def test_13_the_users_created_here_can_sign_in(world: World):
    """Sanity check of the fixtures themselves (keeps failures in the steps above meaningful)."""
    assert Api.login(world.manager_email, USER_PASSWORD) and Api.login(world.sales_email, USER_PASSWORD)


def test_14_new_users_sign_up_and_verify_their_email(browser, browser_errors, admin_api: Api, world: World):
    """Self sign-up: the account only works after the emailed/logged one-time code, and is always Sales."""
    if not httpx.get(f"{API_BASE_URL}/api/v1/auth/config", timeout=30, verify=TLS_VERIFY).json()["signup_enabled"]:
        pytest.skip("Self sign-up is turned off on this deployment (SIGNUP_ENABLED=false)")

    errors_before = len(browser_errors)
    page = new_page(browser, browser_errors)
    email = f"e2e-signup-{world.run}@example.com"
    page.goto(f"{BASE_URL}/signup")
    page.get_by_label("Full name").fill("New Starter")
    page.get_by_label("Work email").fill(email)
    page.get_by_label("Password", exact=True).fill("Welcome2026!")
    page.get_by_label("Confirm password").fill("Welcome2026!")
    seen = codes_so_far(email)
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("heading", name="Verify your email")).to_be_visible()

    created = admin_api.get("/users", role="SALES", page_size=100)["items"]
    assert any(u["email"] == email and not u["is_verified"] for u in created)

    page.get_by_label("Digit 1 of 6").fill(read_new_code(email, seen))
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    verified = next(u for u in admin_api.get("/users", role="SALES", page_size=100)["items"] if u["email"] == email)
    assert verified["is_verified"] is True and verified["role"] == "SALES"
    assert browser_errors[errors_before:] == []
    page.context.close()
