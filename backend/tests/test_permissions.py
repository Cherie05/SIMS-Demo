"""Authorization: deny by default, a reviewed permission matrix, and object-level rules."""

import pytest

from app.core.exceptions import BusinessRuleError
from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.models import UserRole
from app.schemas.user import UserUpdate
from app.services import user_service

# Every API operation open to anonymous callers. Anything not listed here must require a token.
PUBLIC_OPERATIONS = {
    ("GET", "/api/v1/auth/config"),
    ("POST", "/api/v1/auth/signup"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/otp/verify"),
    ("POST", "/api/v1/auth/otp/resend"),
    ("POST", "/api/v1/auth/refresh"),  # cookie + CSRF header
    ("POST", "/api/v1/auth/logout"),  # cookie + CSRF header
    ("POST", "/api/v1/auth/password/forgot"),
    ("POST", "/api/v1/auth/password/reset"),
    ("POST", "/api/v1/telemetry/client-errors"),
    ("POST", "/api/v1/telemetry/web-vitals"),
}


def _operations(client):
    for path, item in client.get("/openapi.json").json()["paths"].items():
        for method, operation in item.items():
            yield method.upper(), path, operation


def test_every_api_operation_requires_authentication_unless_explicitly_public(client):
    seen_public = set()
    for method, path, operation in _operations(client):
        if not path.startswith("/api/"):
            continue
        if (method, path) in PUBLIC_OPERATIONS:
            seen_public.add((method, path))
            continue
        assert operation.get("security"), f"{method} {path} is reachable without authentication"
    assert seen_public == PUBLIC_OPERATIONS  # no stale entries in the allow-list


def test_protected_operations_refuse_anonymous_callers(client):
    checked = 0
    for method, path, _operation in _operations(client):
        if not path.startswith("/api/") or (method, path) in PUBLIC_OPERATIONS:
            continue
        url = path.replace("{", "").replace("}", "")  # placeholders become harmless literals
        response = client.request(method, url, json={} if method in ("POST", "PUT", "PATCH") else None)
        assert response.status_code in (401, 422), f"{method} {path} -> {response.status_code}"
        checked += 1
    assert checked > 40


ADMIN_ONLY = [
    ("GET", "/api/v1/users"),
    ("GET", "/api/v1/audit-logs"),
    ("GET", "/api/v1/system/status"),
    ("GET", "/api/v1/system/jobs"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
@pytest.mark.parametrize("role", ["sales", "manager"])
def test_admin_areas_are_closed_to_other_roles(client, auth, role, method, path):
    assert client.request(method, path, headers=auth(role)).status_code == 403


@pytest.mark.parametrize(("method", "path"), ADMIN_ONLY)
def test_admins_reach_the_admin_areas(client, auth, method, path):
    assert client.request(method, path, headers=auth("admin")).status_code == 200


def test_sales_cannot_manage_catalogue_or_approve(client, auth, customer, make_product):
    product = make_product()
    sales = auth("sales")
    assert (
        client.post("/api/v1/products", json={"sku": "S-1", "name": "Nope", "unit_price": 1}, headers=sales).status_code
        == 403
    )
    adjust = {"txn_type": "RESTOCK", "quantity": 5}
    assert (
        client.post(f"/api/v1/products/{product.id}/stock-adjustments", json=adjust, headers=sales).status_code == 403
    )
    assert client.get("/api/v1/approvals", headers=sales).status_code == 403
    assert client.get("/api/v1/approvals", headers=auth("manager")).status_code == 200


def test_me_lists_permissions_for_the_web_app(client, auth):
    sales = client.get("/api/v1/auth/me", headers=auth("sales")).json()["permissions"]
    admin = client.get("/api/v1/auth/me", headers=auth("admin")).json()["permissions"]
    assert "order:create" in sales and "order:approve" not in sales and "audit:read" not in sales
    assert set(admin) == {p.value for p in Permission}


def test_roles_only_ever_gain_permissions_going_up():
    """Least privilege, reviewable in one place: each role is a strict superset of the one below."""
    sales, manager, admin = (ROLE_PERMISSIONS[r] for r in (UserRole.SALES, UserRole.MANAGER, UserRole.ADMIN))
    assert sales < manager < admin
    assert Permission.USER_MANAGE not in manager and Permission.ORDER_APPROVE not in sales


def test_the_last_active_admin_cannot_be_demoted_or_deactivated(db, users):
    """Defence in depth at the service layer, whatever the caller (CLI, future roles...)."""
    others = [users["manager"]]  # acting user without admin rights, e.g. a future delegated role
    for change in (UserUpdate(role=UserRole.MANAGER), UserUpdate(is_active=False)):
        with pytest.raises(BusinessRuleError) as exc:
            user_service.update_user(db, users["admin"].id, change, others[0])
        assert exc.value.code == "LAST_ADMIN"
