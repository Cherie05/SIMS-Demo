"""Sign-up with email verification, one-time codes, and rotating refresh-token sessions."""

import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import clock
from app.core.config import settings
from app.core.rate_limit import signup_limiter
from app.main import app
from app.models import OtpChallenge, OtpPurpose, RefreshToken, User, UserRole
from tests.conftest import PASSWORD, REAL_OTP_DELIVER, sign_in

LOGIN = "/api/v1/auth/login"
SIGNUP = "/api/v1/auth/signup"
VERIFY = "/api/v1/auth/otp/verify"
RESEND = "/api/v1/auth/otp/resend"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
CSRF = {"X-Requested-With": "sims-web"}
NEW_USER = {"name": "Nisha Rao", "email": "Nisha@Example.com", "password": "Str0ngPass!"}


@pytest.fixture
def later(monkeypatch):
    """later(seconds) moves the server clock forward."""
    real_utcnow = clock.utcnow

    def move(seconds: float) -> None:
        monkeypatch.setattr(clock, "utcnow", lambda: real_utcnow() + timedelta(seconds=seconds))

    return move


def _verify(client, challenge_id: str, code: str):
    return client.post(VERIFY, json={"challenge_id": challenge_id, "code": code})


def _login_challenge(client, email: str = "sales@example.com") -> dict:
    response = client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _refresh_cookie(client) -> str:
    return client.cookies.get(settings.REFRESH_COOKIE_NAME)


# ------------------------------------------------------------------ sign-up


def test_sign_up_verifies_the_email_and_then_signs_in(client, db, otp_codes):
    started = client.post(SIGNUP, json=NEW_USER)
    assert started.status_code == 202
    challenge = started.json()
    assert (challenge["purpose"], challenge["destination"], challenge["otp_required"]) == (
        "SIGNUP",
        "ni***@example.com",
        True,
    )
    user = db.scalar(select(User).where(User.email == "nisha@example.com"))
    assert user.role == UserRole.SALES and not user.is_verified  # can't sign in yet

    session = _verify(client, challenge["challenge_id"], otp_codes["nisha@example.com"][-1])
    assert session.status_code == 200
    body = session.json()
    assert (body["user"]["role"], body["user"]["is_verified"]) == ("SALES", True)
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["email"] == "nisha@example.com"


def test_sign_up_cannot_choose_a_role(client):
    assert client.post(SIGNUP, json={**NEW_USER, "role": "ADMIN"}).status_code == 422


def test_sign_up_enforces_the_password_policy(client):
    assert client.post(SIGNUP, json={**NEW_USER, "password": "password"}).status_code == 422


def test_sign_up_for_an_existing_account_is_refused(client, users):
    response = client.post(SIGNUP, json={**NEW_USER, "email": "sales@example.com"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_unfinished_sign_up_can_restart_and_the_old_code_stops_working(client, otp_codes):
    first = client.post(SIGNUP, json=NEW_USER).json()
    second = client.post(SIGNUP, json={**NEW_USER, "name": "Nisha R"}).json()
    old_code, new_code = otp_codes["nisha@example.com"]
    assert _verify(client, first["challenge_id"], old_code).json()["error"]["code"] == "OTP_INVALID_CHALLENGE"
    assert _verify(client, second["challenge_id"], new_code).json()["user"]["name"] == "Nisha R"


def test_signing_in_before_verifying_asks_for_the_email_code(client, otp_codes):
    client.post(SIGNUP, json=NEW_USER)
    login = client.post(LOGIN, json={"email": NEW_USER["email"], "password": NEW_USER["password"]})
    assert login.json()["purpose"] == "SIGNUP"
    assert _verify(client, login.json()["challenge_id"], otp_codes["nisha@example.com"][-1]).status_code == 200


def test_sign_up_can_be_turned_off_or_limited_to_company_domains(client, monkeypatch):
    monkeypatch.setattr(settings, "SIGNUP_ENABLED", False)
    disabled = client.post(SIGNUP, json=NEW_USER)
    assert disabled.status_code == 403 and disabled.json()["error"]["code"] == "SIGNUP_DISABLED"

    monkeypatch.setattr(settings, "SIGNUP_ENABLED", True)
    monkeypatch.setattr(settings, "SIGNUP_ALLOWED_DOMAINS", "company.com")
    outsider = client.post(SIGNUP, json=NEW_USER)
    assert outsider.status_code == 400 and outsider.json()["error"]["code"] == "EMAIL_DOMAIN_NOT_ALLOWED"
    assert client.post(SIGNUP, json={**NEW_USER, "email": "nisha@company.com"}).status_code == 202


def test_sign_ups_are_rate_limited_per_network(client, monkeypatch):
    monkeypatch.setattr(signup_limiter, "limit", 2)
    for i in range(2):
        assert client.post(SIGNUP, json={**NEW_USER, "email": f"user{i}@example.com"}).status_code == 202
    blocked = client.post(SIGNUP, json={**NEW_USER, "email": "user9@example.com"})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0


# ------------------------------------------------------------------ one-time codes


def test_wrong_codes_are_counted_and_then_lock_the_challenge(client, users, otp_codes):
    challenge = _login_challenge(client)
    right = otp_codes["sales@example.com"][-1]
    wrong = "000000" if right != "000000" else "111111"

    first = _verify(client, challenge["challenge_id"], wrong)
    assert first.status_code == 400
    assert first.json()["error"]["code"] == "OTP_INCORRECT"
    assert first.json()["error"]["details"]["remaining_attempts"] == settings.OTP_MAX_ATTEMPTS - 1
    for _ in range(settings.OTP_MAX_ATTEMPTS - 1):
        _verify(client, challenge["challenge_id"], wrong)
    assert _verify(client, challenge["challenge_id"], right).json()["error"]["code"] == "OTP_LOCKED"


def test_codes_expire(client, users, otp_codes, later):
    challenge = _login_challenge(client)
    later(settings.OTP_TTL_SECONDS + 1)
    expired = _verify(client, challenge["challenge_id"], otp_codes["sales@example.com"][-1])
    assert expired.json()["error"]["code"] == "OTP_EXPIRED"


def test_codes_work_only_once(client, users, otp_codes):
    challenge = _login_challenge(client)
    code = otp_codes["sales@example.com"][-1]
    assert _verify(client, challenge["challenge_id"], code).status_code == 200
    assert _verify(client, challenge["challenge_id"], code).json()["error"]["code"] == "OTP_INVALID_CHALLENGE"


@pytest.mark.parametrize("code", ["12ab56", "12345", "1234567", ""])
def test_malformed_codes_are_rejected(client, users, code):
    assert _verify(client, _login_challenge(client)["challenge_id"], code).status_code == 422


def test_resend_has_a_cooldown_and_replaces_the_code(client, users, otp_codes, later):
    challenge = _login_challenge(client)
    too_soon = client.post(RESEND, json={"challenge_id": challenge["challenge_id"]})
    assert too_soon.status_code == 429 and int(too_soon.headers["Retry-After"]) > 0

    later(settings.OTP_RESEND_COOLDOWN_SECONDS + 1)
    resent = client.post(RESEND, json={"challenge_id": challenge["challenge_id"]})
    assert resent.status_code == 200
    assert resent.json()["resend_available_in"] == settings.OTP_RESEND_COOLDOWN_SECONDS
    old_code, new_code = otp_codes["sales@example.com"]
    assert _verify(client, challenge["challenge_id"], old_code).json()["error"]["code"] == "OTP_INCORRECT"
    assert _verify(client, challenge["challenge_id"], new_code).status_code == 200


def test_the_number_of_resends_is_limited(client, users, later, monkeypatch):
    monkeypatch.setattr(settings, "OTP_MAX_SENDS", 2)
    challenge_id = _login_challenge(client)["challenge_id"]
    later(31)
    assert client.post(RESEND, json={"challenge_id": challenge_id}).status_code == 200
    later(62)
    limited = client.post(RESEND, json={"challenge_id": challenge_id})
    assert limited.json()["error"]["code"] == "OTP_RESEND_LIMIT"


def test_codes_are_stored_only_as_keyed_hashes(client, users, otp_codes, db):
    _login_challenge(client)
    stored = db.scalars(select(OtpChallenge)).one()
    assert otp_codes["sales@example.com"][-1] not in stored.code_hash
    assert len(stored.code_hash) == 64


def test_codes_are_written_to_the_server_log_by_default(caplog):
    with caplog.at_level(logging.WARNING, logger="sims.otp"):
        REAL_OTP_DELIVER("sales@example.com", "Sales", OtpPurpose.LOGIN, "123456")
    assert "OTP for sales@example.com (sign-in): 123456 - valid for 5 minutes" in caplog.text


def test_codes_can_be_emailed_instead(users, sent_emails, monkeypatch, run_jobs):
    monkeypatch.setattr(settings, "OTP_DELIVERY", "email")
    REAL_OTP_DELIVER("sales@example.com", "Sales", OtpPurpose.SIGNUP, "654321")
    run_jobs()
    assert sent_emails[0]["To"] == "sales@example.com"
    assert sent_emails[0]["Subject"] == "654321 is your SIMS verification code"


def test_sign_in_without_a_code_when_the_second_step_is_turned_off(client, users, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_OTP_REQUIRED", False)
    body = client.post(LOGIN, json={"email": "sales@example.com", "password": PASSWORD}).json()
    assert body["otp_required"] is False and body["access_token"]


# ------------------------------------------------------------------ sessions


def test_the_refresh_cookie_is_http_only_strict_and_scoped(client, users, otp_codes):
    challenge = _login_challenge(client)
    verified = _verify(client, challenge["challenge_id"], otp_codes["sales@example.com"][-1])
    cookie = verified.headers["set-cookie"].lower()
    assert f"{settings.REFRESH_COOKIE_NAME}=" in cookie
    for flag in ("httponly", "samesite=strict", "path=/api/v1/auth"):
        assert flag in cookie
    # lives as long as the idle timeout: an unused session dies with its cookie
    max_age = int(cookie.split("max-age=")[1].split(";")[0])
    assert abs(max_age - settings.session_idle_timeout_seconds) <= 1
    assert verified.json()["access_token"].lower() not in cookie


def test_refresh_rotates_the_session(client, users, otp_codes):
    sign_in(client, otp_codes, "sales@example.com")
    first = _refresh_cookie(client)
    refreshed = client.post(REFRESH, headers=CSRF)
    assert refreshed.status_code == 200
    assert refreshed.json()["user"]["email"] == "sales@example.com"
    assert _refresh_cookie(client) not in (None, first)
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"})
    assert me.status_code == 200


def test_reusing_a_rotated_refresh_token_ends_every_session(client, users, otp_codes, later):
    sign_in(client, otp_codes, "sales@example.com")
    stolen = _refresh_cookie(client)
    client.post(REFRESH, headers=CSRF)  # the real user refreshes, rotating `stolen` out
    later(60)  # well past the grace window for parallel tabs
    thief = TestClient(app, cookies={settings.REFRESH_COOKIE_NAME: stolen})
    assert thief.post(REFRESH, headers=CSRF).status_code == 401
    assert client.post(REFRESH, headers=CSRF).status_code == 401  # the victim's session was ended too


def test_two_tabs_refreshing_at_once_do_not_sign_the_user_out(client, users, otp_codes):
    sign_in(client, otp_codes, "sales@example.com")
    old = _refresh_cookie(client)
    client.post(REFRESH, headers=CSRF)  # tab 1 rotates the token
    racing_tab = TestClient(app, cookies={settings.REFRESH_COOKIE_NAME: old})
    assert racing_tab.post(REFRESH, headers=CSRF).status_code == 401  # tab 2 loses the race...
    assert client.post(REFRESH, headers=CSRF).status_code == 200  # ...but the session survives


def test_losing_refresh_response_preserves_the_winning_cookie_in_a_shared_browser_jar(client, users, otp_codes):
    sign_in(client, otp_codes, "sales@example.com")
    old = _refresh_cookie(client)
    winner = client.post(REFRESH, headers=CSRF)
    assert winner.status_code == 200
    new = _refresh_cookie(client)
    assert new != old

    # Another tab's request began with the old cookie but its response arrives after the winner.
    loser = client.post(REFRESH, headers={**CSRF, "Cookie": f"{settings.REFRESH_COOKIE_NAME}={old}"})
    assert loser.status_code == 401 and loser.json()["error"]["code"] == "SESSION_REFRESH_RACE"
    assert "set-cookie" not in loser.headers
    assert _refresh_cookie(client) == new
    assert client.post(REFRESH, headers=CSRF).status_code == 200


def test_refresh_needs_the_csrf_header(client, users, otp_codes):
    sign_in(client, otp_codes, "sales@example.com")
    blocked = client.post(REFRESH)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CSRF_CHECK_FAILED"


def test_refresh_without_a_session_cookie_is_not_an_error(client):
    response = client.post(REFRESH, headers=CSRF)
    assert response.status_code == 204  # an anonymous visitor, not a failure
    assert response.content == b""


def test_logout_ends_the_session(client, users, otp_codes):
    sign_in(client, otp_codes, "sales@example.com")
    cookie = _refresh_cookie(client)
    assert client.post(LOGOUT, headers=CSRF).status_code == 204
    assert (
        TestClient(app, cookies={settings.REFRESH_COOKIE_NAME: cookie}).post(REFRESH, headers=CSRF).status_code == 401
    )


def test_a_refresh_token_is_useless_as_a_bearer_token(client, users, otp_codes):
    sign_in(client, otp_codes, "sales@example.com")
    bearer = {"Authorization": f"Bearer {_refresh_cookie(client)}"}
    assert client.get("/api/v1/auth/me", headers=bearer).status_code == 401


def test_new_password_or_deactivation_ends_existing_sessions(client, auth, users, otp_codes):
    device = TestClient(app)
    sign_in(device, otp_codes, "sales@example.com")
    client.patch(f"/api/v1/users/{users['sales'].id}", json={"password": "N3wPassword!"}, headers=auth("admin"))
    assert device.post(REFRESH, headers=CSRF).status_code == 401

    sign_in(device, otp_codes, "sales@example.com", password="N3wPassword!")
    client.patch(f"/api/v1/users/{users['sales'].id}", json={"is_active": False}, headers=auth("admin"))
    assert device.post(REFRESH, headers=CSRF).status_code == 401


def test_refresh_tokens_are_stored_only_as_hashes(client, users, otp_codes, db):
    sign_in(client, otp_codes, "sales@example.com")
    cookie = _refresh_cookie(client)
    stored = db.scalars(select(RefreshToken)).all()
    assert stored and all(t.token_hash != cookie and len(t.token_hash) == 64 for t in stored)


def test_auth_config_is_public(client):
    assert client.get("/api/v1/auth/config").json() == {
        "signup_enabled": True,
        "signup_allowed_domains": [],
        "login_otp_required": True,
        "otp_delivery": "log",
        "demo_accounts": True,
        "session_idle_timeout_seconds": settings.session_idle_timeout_seconds,
        "password_min_length": 8,
        "password_max_length": 128,
    }
