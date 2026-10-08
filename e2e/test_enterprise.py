"""Enterprise flows through the real web app and its API, using unique test accounts."""

import uuid

from playwright.sync_api import expect

from conftest import BASE_URL, USER_PASSWORD, Api, codes_so_far, new_page, read_new_code, sign_in


def test_password_reset_revokes_sessions_and_allows_new_sign_in(browser, browser_errors, admin_api: Api):
    email = f"e2e-reset-{uuid.uuid4().hex[:8]}@example.com"
    admin_api.post(
        "/users", {"name": "Password recovery test", "email": email, "password": USER_PASSWORD, "role": "SALES"}
    )
    previous = Api.login(email, USER_PASSWORD)
    unexpected = []
    page = new_page(browser, unexpected)
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{BASE_URL}/forgot-password")
        page.get_by_label("Email", exact=True).fill(email)
        seen = codes_so_far(email)
        page.get_by_role("button", name="Send code", exact=True).click()
        expect(page.get_by_role("heading", name="Choose a new password")).to_be_visible()
        page.get_by_label("Digit 1 of 6").fill(read_new_code(email, seen))
        next_password = "Recovered2026!"
        page.get_by_label("New password", exact=True).fill(next_password)
        page.get_by_label("Confirm new password", exact=True).fill(next_password)
        page.get_by_role("button", name="Set new password", exact=True).click()
        expect(page.get_by_role("heading", name="Password changed", exact=True)).to_be_visible()
        assert previous.request("GET", "/auth/me").status_code == 401
        previous._client.close()
        sign_in(page, email, next_password)
        page.goto(f"{BASE_URL}/account")
        expect(page.get_by_text("This device", exact=True)).to_be_visible()
        page.get_by_role("button", name="Set up authenticator app", exact=True).click()
        expect(page.get_by_role("dialog", name="Set up an authenticator app")).to_be_visible()
        page.get_by_role("button", name="Cancel", exact=True).click()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
        assert not unexpected, unexpected
    finally:
        page.context.close()
        previous._client.close()


def test_logout_remains_signed_out_after_offline_reload(browser, admin_api: Api):
    email = f"e2e-logout-{uuid.uuid4().hex[:8]}@example.com"
    admin_api.post(
        "/users", {"name": "Offline sign-out test", "email": email, "password": USER_PASSWORD, "role": "SALES"}
    )
    page = new_page(browser, [])
    exceptions = []
    # WebKit also exposes deliberately offline XHR failures as Playwright pageerror events.
    # Observe the actual window exception/rejection events without suppressing any of them.
    page.expose_binding("reportUncaughtError", lambda source, message: exceptions.append(message))
    page.add_init_script("""(() => {
        const report = message => window.reportUncaughtError(message).catch(() => {});
        window.addEventListener('error', event => report(event.message));
        window.addEventListener('unhandledrejection', event => report(String(event.reason?.stack || event.reason)));
    })();""")
    if browser.browser_type.name != "webkit":
        page.on("pageerror", lambda error: exceptions.append(str(error)))
    try:
        sign_in(page, email, USER_PASSWORD)
        page.goto(f"{BASE_URL}/account")
        expect(page.get_by_text("This device", exact=True)).to_be_visible()
        page.context.set_offline(True)
        page.get_by_role("button", name="Sign out", exact=True).click()
        expect(page).to_have_url(f"{BASE_URL}/login")
        page.context.set_offline(False)
        page.reload()
        expect(page.get_by_role("heading", name="Welcome back", exact=True)).to_be_visible()
        expect(page).to_have_url(f"{BASE_URL}/login")
        sign_in(page, email, USER_PASSWORD)
        assert not exceptions, exceptions
    finally:
        page.context.set_offline(False)
        page.context.close()


def test_enterprise_permissions_and_audit_are_enforced(admin_api: Api):
    email = f"e2e-permission-{uuid.uuid4().hex[:8]}@example.com"
    user = admin_api.post(
        "/users", {"name": "Permission test", "email": email, "password": USER_PASSWORD, "role": "SALES"}
    )
    sales = Api.login(email, USER_PASSWORD)
    try:
        for path in ("/audit-logs", "/system/status", "/system/jobs"):
            response = sales.request("GET", path)
            assert response.status_code == 403, (path, response.status_code)
            assert response.json()["error"]["request_id"]
        assert sales.request("PUT", "/feature-flags/orders.create", json={"enabled": False}).status_code == 403
        audit = admin_api.get("/audit-logs", entity_type="user", entity_id=str(user["id"]), page_size=100)
        assert any(entry["action"] == "user.created" for entry in audit["items"])
        health = admin_api.get("/system/status")
        assert health["database"]["status"] == "ok"
        assert any(worker["alive"] for worker in health["workers"])
    finally:
        sales._client.close()


def test_list_failure_retry_and_offline_recovery(browser):
    # A controlled API failure must produce an actionable error, then recover without a reload.
    from conftest import ADMIN_EMAIL, ADMIN_PASSWORD

    page = new_page(browser, [])
    exceptions = []
    page.on("pageerror", lambda error: exceptions.append(str(error)))
    try:
        sign_in(page, ADMIN_EMAIL, ADMIN_PASSWORD)
        page.route(
            "**/api/v1/products?*",
            lambda route: route.fulfill(
                status=503,
                content_type="application/json",
                body='{"error":{"code":"SERVICE_UNAVAILABLE","message":"Product list unavailable"}}',
            ),
        )
        page.goto(f"{BASE_URL}/products")
        expect(page.get_by_role("alert").filter(has_text="Product list unavailable")).to_be_visible(timeout=30_000)
        page.unroute("**/api/v1/products?*")
        page.get_by_role("button", name="Retry", exact=True).click()
        expect(page.get_by_text("Product list unavailable", exact=True)).to_be_hidden()
        expect(page.get_by_role("table")).to_be_visible()
        page.context.set_offline(True)
        expect(page.get_by_role("status").filter(has_text="You're offline")).to_be_visible()
        page.context.set_offline(False)
        expect(page.get_by_role("status").filter(has_text="You're offline")).to_be_hidden()
        assert not exceptions, exceptions
    finally:
        page.context.set_offline(False)
        page.context.close()
