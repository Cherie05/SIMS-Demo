"""Repeatable layout, navigation and accessibility checks against the running application.

Install frontend dependencies first: axe-core is pinned by its npm lockfile. These checks keep
the real Content-Security-Policy enabled and cover the enterprise pages as well as the brief.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from conftest import ADMIN_EMAIL, ADMIN_PASSWORD, BASE_URL, Api, new_page, sign_in

VIEWPORTS = [(360, 740), (390, 844), (768, 1024), (1024, 768), (1440, 900), (1920, 1080)]
PUBLIC_PATHS = ["/login", "/signup", "/forgot-password"]
PRIVATE_PATHS = [
    "/",
    "/orders",
    "/orders/new",
    "/products",
    "/customers",
    "/inventory",
    "/approvals",
    "/settings",
    "/account",
    "/audit",
    "/system",
]
PRIVATE_HEADINGS = {
    "/": "Dashboard",
    "/orders": "Sales orders",
    "/orders/new": "New sales order",
    "/products": "Products",
    "/customers": "Customers",
    "/inventory": "Stock ledger",
    "/approvals": "Approvals",
    "/settings": "Settings & users",
    "/account": "Account & security",
    "/audit": "Audit log",
    "/system": "System",
}
AXE_PATH = Path(__file__).resolve().parents[1] / "frontend/node_modules/axe-core/axe.min.js"


@pytest.fixture(scope="module")
def axe_script():
    assert AXE_PATH.is_file(), "Run npm ci in frontend before the responsive/accessibility suite"
    return AXE_PATH.read_text(encoding="utf-8")


def check_page(page, label: str, axe_script: str | None = None):
    page.wait_for_load_state("networkidle")
    # MUI dialogs fade in. Playwright counts an element as visible at any opacity, but colour
    # contrast is computed with opacity, so measure only once every dialog is fully opaque.
    page.wait_for_function(
        "() => [...document.querySelectorAll('.MuiDialog-container')].every(el => getComputedStyle(el).opacity === '1')"
    )
    dimensions = page.evaluate("""() => ({
        viewport: document.documentElement.clientWidth,
        content: document.documentElement.scrollWidth
    })""")
    assert dimensions["content"] <= dimensions["viewport"] + 1, f"{label}: horizontal overflow {dimensions}"
    if not page.get_by_role("dialog").count():
        expect(page.get_by_role("heading", level=1)).to_have_count(1, timeout=15_000)
    if axe_script:
        page.evaluate(axe_script)
        violations = page.evaluate("""async () => (await axe.run(document, {
            runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']}
        })).violations.map(v => ({
            id: v.id, impact: v.impact,
            nodes: v.nodes.map(n => ({target: n.target, html: n.html}))
        }))""")
        assert not violations, f"{label}: {json.dumps(violations)}"
    if screenshot_dir := os.getenv("E2E_SCREENSHOT_DIR"):
        output = Path(screenshot_dir)
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f"{label.replace('/', '_').replace(' ', '-')}.png"), full_page=True)


@pytest.mark.parametrize("width,height", VIEWPORTS, ids=[f"{w}px" for w, _ in VIEWPORTS])
def test_all_pages_adapt_to_viewport(browser, browser_errors, admin_api: Api, axe_script, width, height):
    page = new_page(browser, browser_errors)
    page.set_viewport_size({"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: message.type == "error" and errors.append(message.text))
    try:
        scan = axe_script if width in (390, 1440) else None
        for path in PUBLIC_PATHS:
            page.goto(f"{BASE_URL}{path}")
            check_page(page, f"{width} {path}", scan)
            expect(page).to_have_url(f"{BASE_URL}{path}")

        sign_in(page, ADMIN_EMAIL, ADMIN_PASSWORD, lambda challenge: check_page(challenge, f"{width} otp", scan))
        orders = admin_api.get("/orders", page_size=1)["items"]
        paths = PRIVATE_PATHS + ([f"/orders/{orders[0]['id']}"] if orders else [])
        for path in paths:
            page.goto(f"{BASE_URL}{path}")
            if path in PRIVATE_HEADINGS:
                expect(page.get_by_role("heading", level=1)).to_have_text(PRIVATE_HEADINGS[path])
            check_page(page, f"{width} {path}", scan)
            expect(page).to_have_url(f"{BASE_URL}{path}")

        # A dialog has a different focus tree and width constraints from its parent page.
        page.goto(f"{BASE_URL}/products")
        page.get_by_role("button", name="Add product").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        check_page(page, f"{width} product-dialog", scan)
        page.get_by_role("button", name="Cancel", exact=True).click()
        page.goto(f"{BASE_URL}/account")
        page.get_by_role("button", name="Set up authenticator app", exact=True).click()
        expect(page.get_by_role("dialog", name="Set up an authenticator app")).to_be_visible()
        check_page(page, f"{width} authenticator-dialog", scan)
        page.get_by_role("button", name="Cancel", exact=True).click()
        if width < 900:
            page.get_by_label("Open menu").click()
            page.get_by_role("link", name="Customers", exact=True).click()
            expect(page).to_have_url(f"{BASE_URL}/customers")
            expect(page.get_by_label("Open menu")).to_be_visible()
            expect(page.get_by_role("link", name="Products", exact=True)).to_be_hidden()
        assert not errors, f"{width}px browser errors: {errors}"
    finally:
        page.context.close()
