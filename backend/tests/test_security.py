"""Security regression tests: authentication hardening, authorization, input handling, headers."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.rate_limit import login_limiter
from app.main import app
from app.models import AppSetting, Customer, User, UserRole
from app.services import dashboard_service
from tests.conftest import PASSWORD

LOGIN = "/api/v1/auth/login"


def _login(client, email="sales@example.com", password=PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


# ------------------------------------------------------------------ brute-force protection


def test_login_locks_after_repeated_failures_for_an_account(client, users):
    for _ in range(settings.LOGIN_MAX_FAILURES_PER_EMAIL):
        assert _login(client, password="wrong-guess-1").status_code == 401

    blocked = _login(client)  # even the correct password is refused while locked
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert int(blocked.headers["Retry-After"]) > 0
    # other accounts are unaffected
    assert _login(client, email="manager@example.com").status_code == 200


def test_successful_login_resets_the_failure_count(client, users):
    for _ in range(settings.LOGIN_MAX_FAILURES_PER_EMAIL - 1):
        _login(client, password="nope-123")
    assert _login(client).status_code == 200
    for _ in range(settings.LOGIN_MAX_FAILURES_PER_EMAIL - 1):
        _login(client, password="nope-123")
    assert _login(client).status_code == 200


def test_login_limits_failures_per_client_ip(client, users, monkeypatch):
    monkeypatch.setattr(login_limiter, "max_per_ip", 3)
    for i in range(3):
        _login(client, email=f"unknown{i}@example.com", password="x1")
    assert _login(client, email="manager@example.com").status_code == 429


# ------------------------------------------------------------------ token handling


def _token(user_id: int, sid: str, secret: str = settings.JWT_SECRET_KEY, algorithm: str = "HS256", **overrides) -> str:
    """A well-formed access token; each test changes exactly one property."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": "ADMIN",
        "type": "access",
        "sid": sid,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(hours=1),
        **overrides,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def test_well_formed_token_is_accepted(client, users, make_session):
    assert _get_me(client, _token(users["sales"].id, make_session(users["sales"]))).status_code == 200


def test_token_without_a_live_session_is_rejected(client, users, make_session, db):
    from app.models import UserSession

    sid = make_session(users["sales"])
    db.get(UserSession, sid).revoked_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    response = _get_me(client, _token(users["sales"].id, sid))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_REVOKED"
    # a session id belonging to someone else doesn't work either
    assert _get_me(client, _token(users["sales"].id, make_session(users["manager"]))).status_code == 401


@pytest.mark.parametrize(
    "claims",
    [{"aud": "another-app"}, {"iss": "someone-else"}, {"type": "refresh"}],
    ids=["wrong-audience", "wrong-issuer", "not-an-access-token"],
)
def test_tokens_for_other_purposes_are_rejected(client, users, claims, make_session):
    response = _get_me(client, _token(users["sales"].id, make_session(users["sales"]), **claims))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def _get_me(client, token: str):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_token_with_tampered_signature_is_rejected(client, auth):
    token = auth("sales")["Authorization"].split()[1]
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    response = _get_me(client, tampered)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_token_signed_with_another_key_is_rejected(client, users, make_session):
    sid = make_session(users["admin"])
    assert (
        _get_me(client, _token(users["admin"].id, sid, secret="attacker-secret-attacker-secret-1234")).status_code
        == 401
    )


def test_unsigned_alg_none_token_is_rejected(client, users):
    unsigned = jwt.encode({"sub": str(users["admin"].id)}, key=None, algorithm="none")
    assert _get_me(client, unsigned).status_code == 401


def test_expired_token_is_rejected(client, users, make_session):
    expired = _token(users["sales"].id, make_session(users["sales"]), exp=datetime.now(UTC) - timedelta(seconds=5))
    response = _get_me(client, expired)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_role_claim_in_token_is_not_trusted(client, users, make_session):
    """The role comes from the database, so forging the role claim gains nothing."""
    forged = _token(users["sales"].id, make_session(users["sales"]), role="ADMIN")
    assert client.get("/api/v1/users", headers={"Authorization": f"Bearer {forged}"}).status_code == 403


def test_deactivated_user_is_locked_out_immediately(client, auth, users, db):
    headers = auth("sales")
    users["sales"].is_active = False
    db.commit()
    assert client.get("/api/v1/products", headers=headers).status_code == 401


def test_role_change_takes_effect_immediately(client, auth, users, db, customer, make_product):
    product = make_product(price="6000.00", stock=10)
    order = client.post(
        "/api/v1/orders",
        json={"customer_id": customer.id, "items": [{"product_id": product.id, "quantity": 2}]},
        headers=auth("sales"),
    ).json()
    manager_headers = auth("manager")
    db.get(User, users["manager"].id).role = UserRole.SALES
    db.commit()
    assert client.post(f"/api/v1/orders/{order['id']}/approve", headers=manager_headers).status_code == 403


# ------------------------------------------------------------------ input handling


def test_unknown_fields_are_rejected(client, auth):
    """No mass assignment: clients cannot set fields the API does not expose."""
    product = {"sku": "MA-1", "name": "Thing", "unit_price": 1, "stock_qty": 999}
    assert client.post("/api/v1/products", json=product, headers=auth("manager")).status_code == 422
    customer = {"name": "Evil", "email": "evil@example.com", "is_active": False, "id": 1}
    assert client.post("/api/v1/customers", json=customer, headers=auth("sales")).status_code == 422


@pytest.mark.parametrize("term", ["' OR 1=1 -- ", '"; DROP TABLE customers; --', "%' UNION SELECT 1 --"])
def test_search_terms_are_treated_as_data(client, auth, customer, term):
    response = client.get("/api/v1/customers", params={"search": term}, headers=auth("sales"))
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert client.get("/api/v1/customers", headers=auth("sales")).json()["total"] == 1  # table intact


def test_html_in_user_data_is_escaped_in_emails(client, auth, db, make_product, sent_emails, run_jobs):
    evil = Customer(name='<script>alert("x")</script>', email="xss@example.com")
    db.add(evil)
    db.commit()
    product = make_product(price="6000.00", stock=10)
    client.post(
        "/api/v1/orders",
        json={"customer_id": evil.id, "items": [{"product_id": product.id, "quantity": 2}], "notes": "<img src=x>"},
        headers=auth("sales"),
    )
    run_jobs()
    html = sent_emails[0].get_body(preferencelist=("html",)).get_content()
    assert "<script>" not in html and "<img src=x>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    "password",
    ["short1", "onlyletters", "1234567890", "a1" + "x" * 130, "Password123", "Qwerty123"],  # too long; common
)
def test_weak_or_oversized_passwords_are_rejected(client, auth, password):
    payload = {"name": "New User", "email": "new@example.com", "password": password, "role": "SALES"}
    response = client.post("/api/v1/users", json=payload, headers=auth("admin"))
    assert response.status_code == 422, response.text


def test_page_size_is_capped(client, auth):
    assert client.get("/api/v1/orders?page_size=1000", headers=auth("sales")).status_code == 422
    assert client.get("/api/v1/orders?page=0", headers=auth("sales")).status_code == 422


def test_approval_threshold_cannot_be_negative(client, auth, db):
    response = client.put("/api/v1/settings", json={"approval_threshold": -1}, headers=auth("admin"))
    assert response.status_code == 422
    assert db.get(AppSetting, "approval_threshold").value == "10000.00"


# ------------------------------------------------------------------ transport & configuration


def test_api_responses_carry_security_headers(client, auth):
    response = client.get("/api/v1/products", headers=auth("sales"))
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]


def test_cors_only_allows_configured_origins(client):
    def preflight(origin):
        return client.options(
            "/api/v1/auth/login",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )

    allowed = preflight("http://localhost:5173")
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-credentials" not in allowed.headers
    assert "access-control-allow-origin" not in preflight("https://evil.example.com").headers


def test_production_refuses_weak_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="change-me-in-production")
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="too-short")


PROD = {
    "ENVIRONMENT": "production",
    "JWT_SECRET_KEY": "x" * 48,
    "DATA_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
    "DATABASE_TLS": "required",
    "COOKIE_SECURE": True,
}


def test_production_defaults_hide_api_docs():
    prod = Settings(**PROD)
    assert prod.api_docs_enabled is False
    assert Settings(**PROD, ENABLE_API_DOCS=True).api_docs_enabled
    assert Settings(ENVIRONMENT="development").api_docs_enabled


@pytest.mark.parametrize("mode", ["preferred", "disabled"])
def test_deployed_config_requires_database_encryption(mode):
    with pytest.raises(ValidationError, match="DATABASE_TLS"):
        Settings(**{**PROD, "DATABASE_TLS": mode})


def test_deployed_config_requires_secure_session_cookies():
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(**{**PROD, "COOKIE_SECURE": False})


def test_invalid_email_transport_configuration_is_rejected():
    with pytest.raises(ValidationError, match="cannot both"):
        Settings(SMTP_SSL=True, SMTP_STARTTLS=True)
    with pytest.raises(ValidationError, match="EMAIL_ENABLED"):
        Settings(OTP_DELIVERY="email", EMAIL_ENABLED=False)


@pytest.mark.parametrize(
    "field",
    [
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "SESSION_IDLE_TIMEOUT_MINUTES",
        "SESSION_ABSOLUTE_TIMEOUT_HOURS",
        "OTP_TTL_SECONDS",
        "OTP_MAX_ATTEMPTS",
        "OTP_RESEND_COOLDOWN_SECONDS",
        "OTP_MAX_SENDS",
        "LOGIN_FAILURE_WINDOW_SECONDS",
        "JOB_LOCK_SECONDS",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_security_lifetimes_and_budgets_must_be_positive(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_unexpected_errors_do_not_leak_details(auth, monkeypatch):
    def boom(_db):
        raise RuntimeError("secret internal detail: db password is hunter2")

    monkeypatch.setattr(dashboard_service, "get_summary", boom)
    # By default TestClient re-raises server errors; we want the real 500 response instead.
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/dashboard/summary", headers=auth("sales"))
    assert response.status_code == 500
    error = response.json()["error"]
    assert (error["code"], error["message"], error["details"]) == (
        "INTERNAL_ERROR",
        "An unexpected error occurred",
        None,
    )
    # support can find the logged traceback by the request id; the client learns nothing else
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "hunter2" not in response.text


def test_database_outage_returns_503_without_details(auth, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def db_down(_db):
        raise OperationalError("SELECT ...", {}, Exception("(2003) Can't connect to MySQL server on 'mysql'"))

    monkeypatch.setattr(dashboard_service, "get_summary", db_down)
    response = TestClient(app).get("/api/v1/dashboard/summary", headers=auth("sales"))
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "mysql" not in response.text.lower()
