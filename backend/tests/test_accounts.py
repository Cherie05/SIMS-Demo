"""Account security: sessions and devices, timeouts, password change and reset, authenticator apps,
Argon2id hashing, new-device alerts and signing-key rotation."""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pyotp
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.models import RefreshToken, User, UserRole, UserSession
from tests.conftest import CSRF, PASSWORD, sign_in

AUTH = "/api/v1/auth"


def _bearer(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}


def _device(user_agent: str) -> TestClient:
    return TestClient(app, headers={"User-Agent": user_agent})


# ------------------------------------------------------------------ sessions & devices


def test_sessions_list_shows_each_device_and_marks_this_one(client, users, otp_codes):
    laptop = sign_in(_device("Laptop/1.0"), otp_codes, "sales@example.com")
    sign_in(_device("Phone/2.0"), otp_codes, "sales@example.com")
    sessions = client.get(f"{AUTH}/sessions", headers=_bearer(laptop)).json()
    assert {s["user_agent"] for s in sessions} == {"Laptop/1.0", "Phone/2.0"}
    assert [s["user_agent"] for s in sessions if s["current"]] == ["Laptop/1.0"]
    assert all(s["mfa_method"] == "code" for s in sessions)


def test_signing_out_another_device_stops_its_token_immediately(client, users, otp_codes):
    laptop = sign_in(_device("Laptop/1.0"), otp_codes, "sales@example.com")
    phone_client = _device("Phone/2.0")
    phone = sign_in(phone_client, otp_codes, "sales@example.com")
    assert client.get(f"{AUTH}/me", headers=_bearer(phone)).status_code == 200

    sessions = client.get(f"{AUTH}/sessions", headers=_bearer(laptop)).json()
    phone_id = next(s["id"] for s in sessions if s["user_agent"] == "Phone/2.0")
    assert client.delete(f"{AUTH}/sessions/{phone_id}", headers=_bearer(laptop)).status_code == 204

    # no 15-minute window: the access token is dead now, and so is the refresh cookie
    revoked = client.get(f"{AUTH}/me", headers=_bearer(phone))
    assert revoked.status_code == 401 and revoked.json()["error"]["code"] == "SESSION_REVOKED"
    assert phone_client.post(f"{AUTH}/refresh", headers=CSRF).status_code == 401
    assert client.get(f"{AUTH}/me", headers=_bearer(laptop)).status_code == 200


def test_users_cannot_revoke_someone_elses_session(client, users, otp_codes):
    mine = sign_in(_device("A"), otp_codes, "sales@example.com")
    theirs = sign_in(_device("B"), otp_codes, "sales2@example.com")
    their_id = client.get(f"{AUTH}/sessions", headers=_bearer(theirs)).json()[0]["id"]
    assert client.delete(f"{AUTH}/sessions/{their_id}", headers=_bearer(mine)).status_code == 404


def test_sign_out_everywhere(client, users, otp_codes):
    here = sign_in(client, otp_codes, "sales@example.com")
    elsewhere = sign_in(_device("Other/1.0"), otp_codes, "sales@example.com")
    result = client.post(f"{AUTH}/sessions/revoke-all", headers=_bearer(here)).json()
    assert result == {"revoked": 1}
    assert client.get(f"{AUTH}/me", headers=_bearer(elsewhere)).status_code == 401
    assert client.get(f"{AUTH}/me", headers=_bearer(here)).status_code == 200  # kept by default

    client.post(f"{AUTH}/sessions/revoke-all", params={"keep_current": "false"}, headers=_bearer(here))
    assert client.get(f"{AUTH}/me", headers=_bearer(here)).status_code == 401


def test_idle_sessions_expire(client, users, otp_codes, later):
    sign_in(client, otp_codes, "sales@example.com")
    later(settings.session_idle_timeout_seconds + 60)
    assert client.post(f"{AUTH}/refresh", headers=CSRF).status_code == 401


def test_active_sessions_still_end_at_their_absolute_lifetime(client, users, otp_codes, later):
    sign_in(client, otp_codes, "sales@example.com")
    step = settings.session_idle_timeout_seconds - 300  # keep refreshing before the idle timeout
    elapsed = 0
    while elapsed + step < settings.session_absolute_timeout_seconds:
        elapsed += step
        later(elapsed)
        assert client.post(f"{AUTH}/refresh", headers=CSRF).status_code == 200, elapsed
    later(settings.session_absolute_timeout_seconds + 1)
    assert client.post(f"{AUTH}/refresh", headers=CSRF).status_code == 401


def test_admin_can_sign_a_user_out_everywhere(client, auth, users, otp_codes):
    device = sign_in(_device("Victim/1.0"), otp_codes, "sales@example.com")
    result = client.post(f"/api/v1/users/{users['sales'].id}/sessions/revoke", headers=auth("admin"))
    assert result.json()["revoked"] >= 1
    assert client.get(f"{AUTH}/me", headers=_bearer(device)).status_code == 401


# ------------------------------------------------------------------ passwords


def test_change_password_needs_the_current_one_and_signs_out_other_devices(client, users, otp_codes):
    here = sign_in(client, otp_codes, "sales@example.com")
    other = sign_in(_device("Other/1.0"), otp_codes, "sales@example.com")
    wrong = client.post(
        f"{AUTH}/password/change",
        json={"current_password": "not-it-123", "new_password": "Brand-New-Pass-9"},
        headers=_bearer(here),
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "PASSWORD_INCORRECT"
    same = client.post(
        f"{AUTH}/password/change",
        json={"current_password": PASSWORD, "new_password": PASSWORD},
        headers=_bearer(here),
    )
    assert same.json()["error"]["code"] == "PASSWORD_REUSED"
    done = client.post(
        f"{AUTH}/password/change",
        json={"current_password": PASSWORD, "new_password": "Brand-New-Pass-9"},
        headers=_bearer(here),
    )
    assert done.status_code == 204
    assert client.get(f"{AUTH}/me", headers=_bearer(other)).status_code == 401
    assert client.get(f"{AUTH}/me", headers=_bearer(here)).status_code == 200
    sign_in(_device("Fresh/1.0"), otp_codes, "sales@example.com", password="Brand-New-Pass-9")


def test_passwords_containing_the_users_name_or_email_are_refused(client, auth):
    response = client.post(
        "/api/v1/users",
        json={"name": "Kiran Kumar", "email": "kiran@example.com", "password": "kiran2026x", "role": "SALES"},
        headers=auth("admin"),
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "PASSWORD_POLICY"


def test_forgot_password_reply_does_not_reveal_whether_the_account_exists(client, users, otp_codes):
    known = client.post(f"{AUTH}/password/forgot", json={"email": "sales@example.com"})
    unknown = client.post(f"{AUTH}/password/forgot", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert len(otp_codes["sales@example.com"]) == 1 and not otp_codes["ghost@example.com"]


def test_password_reset_with_the_emailed_code(client, users, otp_codes):
    old_device = sign_in(_device("Old/1.0"), otp_codes, "sales@example.com")
    client.post(f"{AUTH}/password/forgot", json={"email": "sales@example.com"})
    code = otp_codes["sales@example.com"][-1]

    wrong = client.post(
        f"{AUTH}/password/reset",
        json={
            "email": "sales@example.com",
            "code": "000000" if code != "000000" else "111111",
            "new_password": "Reset-Pass-123",
        },
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "RESET_CODE_INVALID"
    ok = client.post(
        f"{AUTH}/password/reset", json={"email": "sales@example.com", "code": code, "new_password": "Reset-Pass-123"}
    )
    assert ok.status_code == 204
    # every session ends, the code is spent, and the new password works
    assert client.get(f"{AUTH}/me", headers=_bearer(old_device)).status_code == 401
    again = client.post(
        f"{AUTH}/password/reset", json={"email": "sales@example.com", "code": code, "new_password": "Other-Pass-456"}
    )
    assert again.status_code == 400
    sign_in(client, otp_codes, "sales@example.com", password="Reset-Pass-123")


def test_reset_codes_never_open_a_session(client, users, otp_codes, db):
    from app.models import OtpChallenge, OtpPurpose

    client.post(f"{AUTH}/password/forgot", json={"email": "sales@example.com"})
    challenge = db.scalar(select(OtpChallenge).where(OtpChallenge.purpose == OtpPurpose.PASSWORD_RESET))
    response = client.post(
        f"{AUTH}/otp/verify", json={"challenge_id": challenge.id, "code": otp_codes["sales@example.com"][-1]}
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == "OTP_INVALID_CHALLENGE"


def test_passwords_are_stored_as_argon2id_and_legacy_bcrypt_is_upgraded(client, db, users, otp_codes):
    assert users["sales"].password_hash.startswith("$argon2id$")
    legacy = User(
        name="Legacy",
        email="legacy@example.com",
        password_hash=bcrypt.hashpw(b"Legacy-Pass-1", bcrypt.gensalt(rounds=4)).decode(),
        role=UserRole.SALES,
        email_verified_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(legacy)
    db.commit()
    sign_in(client, otp_codes, "legacy@example.com", password="Legacy-Pass-1")
    db.refresh(legacy)
    assert legacy.password_hash.startswith("$argon2id$")
    sign_in(_device("Again/1.0"), otp_codes, "legacy@example.com", password="Legacy-Pass-1")


# ------------------------------------------------------------------ alerts


def test_a_sign_in_from_a_new_browser_sends_a_security_email(client, users, otp_codes, run_jobs, sent_emails):
    sign_in(_device("Laptop/1.0"), otp_codes, "sales@example.com")  # first ever: nothing to compare with
    sign_in(_device("Laptop/1.0"), otp_codes, "sales@example.com")  # known browser
    run_jobs()
    assert sent_emails == []
    sign_in(_device("Unknown/9.9"), otp_codes, "sales@example.com")
    run_jobs()
    assert [(m["To"], m["Subject"]) for m in sent_emails] == [("sales@example.com", "New sign-in to your account")]


# ------------------------------------------------------------------ authenticator app (TOTP)


def _enable_totp(client, headers) -> tuple[pyotp.TOTP, list[str]]:
    wrong = client.post(f"{AUTH}/mfa/totp/setup", json={"password": "not-mine-1"}, headers=headers)
    assert wrong.json()["error"]["code"] == "PASSWORD_INCORRECT"
    setup = client.post(f"{AUTH}/mfa/totp/setup", json={"password": PASSWORD}, headers=headers).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/SIMS:") and setup["qr_svg_data_uri"].startswith(
        "data:image/svg+xml"
    )
    totp = pyotp.TOTP(setup["secret"])
    bad = client.post(f"{AUTH}/mfa/totp/enable", json={"code": "000000"}, headers=headers)
    assert bad.status_code == 400
    codes = client.post(f"{AUTH}/mfa/totp/enable", json={"code": totp.now()}, headers=headers).json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    return totp, codes


def _next_code(totp: pyotp.TOTP) -> str:
    """The code of the next 30-second window (the current one was just used to enable the app)."""
    return totp.at(datetime.now(UTC) + timedelta(seconds=30))


def test_authenticator_app_replaces_emailed_codes(client, auth, users, otp_codes, db):
    totp, _ = _enable_totp(client, auth("sales"))
    status = client.get(f"{AUTH}/mfa", headers=auth("sales")).json()
    assert status == {**status, "totp_enabled": True, "method": "totp", "recovery_codes_remaining": 10}
    stored = db.scalar(select(User).where(User.email == "sales@example.com"))
    assert totp.secret not in (stored.totp_secret_encrypted or "")  # encrypted at rest

    sent_before = len(otp_codes["sales@example.com"])
    challenge = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
    assert (challenge["method"], challenge["delivery"], challenge["destination"]) == ("totp", "authenticator", None)
    assert len(otp_codes["sales@example.com"]) == sent_before  # nothing was sent

    code = _next_code(totp)
    session = client.post(f"{AUTH}/otp/verify", json={"challenge_id": challenge["challenge_id"], "code": code})
    assert session.status_code == 200
    assert db.scalar(select(UserSession.mfa_method).where(UserSession.id == session.json()["session_id"])) == "totp"

    # the same code can't be replayed, even on a fresh challenge
    replay = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
    refused = client.post(f"{AUTH}/otp/verify", json={"challenge_id": replay["challenge_id"], "code": code})
    assert refused.json()["error"]["code"] == "OTP_INCORRECT"
    assert client.post(f"{AUTH}/otp/resend", json={"challenge_id": replay["challenge_id"]}).status_code == 400


def test_recovery_codes_work_once(client, auth, users, run_jobs, sent_emails):
    _, codes = _enable_totp(client, auth("sales"))
    for attempt, expected in ((1, 200), (2, 400)):
        challenge = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
        response = client.post(
            f"{AUTH}/otp/verify", json={"challenge_id": challenge["challenge_id"], "recovery_code": codes[0].upper()}
        )
        assert response.status_code == expected, attempt
    run_jobs()
    assert "A recovery code was used" in [m["Subject"] for m in sent_emails]
    assert client.get(f"{AUTH}/mfa", headers=auth("sales")).json()["recovery_codes_remaining"] == 9


def test_turning_the_authenticator_off_needs_the_password(client, auth, users, otp_codes):
    _enable_totp(client, auth("sales"))
    assert (
        client.post(f"{AUTH}/mfa/totp/disable", json={"password": "nope-123"}, headers=auth("sales")).status_code == 400
    )
    assert (
        client.post(f"{AUTH}/mfa/totp/disable", json={"password": PASSWORD}, headers=auth("sales")).status_code == 204
    )
    challenge = client.post(f"{AUTH}/login", json={"email": "sales@example.com", "password": PASSWORD}).json()
    assert challenge["method"] == "code"  # back to emailed/logged codes


def test_admin_can_reset_a_lost_authenticator(client, auth, users):
    _enable_totp(client, auth("sales"))
    reset = client.post(f"/api/v1/users/{users['sales'].id}/mfa/reset", headers=auth("admin"))
    assert reset.status_code == 200 and reset.json()["totp_enabled"] is False
    assert client.post(f"/api/v1/users/{users['sales'].id}/mfa/reset", headers=auth("admin")).status_code == 409
    assert client.post(f"/api/v1/users/{users['sales'].id}/mfa/reset", headers=auth("manager")).status_code == 403


# ------------------------------------------------------------------ signing-key rotation


def test_tokens_signed_with_the_previous_key_keep_working_during_rotation(client, users, make_session, monkeypatch):
    sid = make_session(users["sales"])
    old_token, _ = create_access_token(users["sales"].id, "SALES", sid)
    new_key = "n" * 48
    monkeypatch.setattr(settings, "JWT_PREVIOUS_SECRET_KEYS", settings.JWT_SECRET_KEY)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", new_key)
    assert client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 200
    new_token, _ = create_access_token(users["sales"].id, "SALES", sid)
    assert jwt.get_unverified_header(new_token)["kid"] != jwt.get_unverified_header(old_token)["kid"]
    assert client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    # once the old key is retired, its tokens stop working
    monkeypatch.setattr(settings, "JWT_PREVIOUS_SECRET_KEYS", "")
    assert client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401


def test_refresh_tokens_belong_to_sessions(client, users, otp_codes, db):
    sign_in(client, otp_codes, "sales@example.com")
    token = db.scalar(select(RefreshToken))
    assert token.session_id and len(token.token_hash) == 64
