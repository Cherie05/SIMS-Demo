from app.core.config import Settings, settings
from tests.conftest import PASSWORD, sign_in


def test_password_alone_does_not_sign_in(client, users, otp_codes):
    response = client.post("/api/v1/auth/login", json={"email": "manager@example.com", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["otp_required"] is True
    assert "access_token" not in body
    assert (body["purpose"], body["delivery"], body["destination"]) == ("LOGIN", "log", "ma***@example.com")
    assert body["expires_in"] == 300 and body["code_length"] == 6
    assert len(otp_codes["manager@example.com"]) == 1


def test_one_time_code_completes_sign_in(client, users, otp_codes):
    session = sign_in(client, otp_codes, "manager@example.com")
    assert session["token_type"] == "bearer"
    assert session["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert Settings.model_fields["ACCESS_TOKEN_EXPIRE_MINUTES"].default == 15  # short-lived by default
    assert session["user"]["role"] == "MANAGER"
    assert "password_hash" not in session["user"]


def test_login_is_case_insensitive_on_email(client, users):
    response = client.post("/api/v1/auth/login", json={"email": "Manager@Example.com", "password": PASSWORD})
    assert response.status_code == 200


def test_login_with_wrong_password_is_rejected(client, users):
    response = client.post("/api/v1/auth/login", json={"email": "manager@example.com", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_disabled_user_cannot_log_in(client, users, db):
    users["sales"].is_active = False
    db.commit()
    response = client.post("/api/v1/auth/login", json={"email": "sales@example.com", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_protected_endpoint_requires_token(client, users):
    assert client.get("/api/v1/products").status_code == 401
    bad = client.get("/api/v1/products", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "INVALID_TOKEN"


def test_me_returns_current_user(client, auth):
    response = client.get("/api/v1/auth/me", headers=auth("sales"))
    assert response.json()["email"] == "sales@example.com"


def test_role_checks(client, auth):
    product = {"sku": "X-1", "name": "Thing", "unit_price": 10}
    assert client.post("/api/v1/products", json=product, headers=auth("sales")).status_code == 403
    assert client.post("/api/v1/products", json=product, headers=auth("manager")).status_code == 201
    assert client.get("/api/v1/users", headers=auth("manager")).status_code == 403
    assert client.get("/api/v1/approvals", headers=auth("sales")).status_code == 403


def test_admin_cannot_deactivate_self(client, auth, users):
    response = client.patch(f"/api/v1/users/{users['admin'].id}", json={"is_active": False}, headers=auth("admin"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SELF_MODIFICATION"
