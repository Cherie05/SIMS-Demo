"""Second-factor checks: one-time codes and authenticator apps.

Emailed/logged codes (method "code") are 6 random digits, valid for OTP_TTL_SECONDS and usable
once, with a limited number of wrong attempts and resends; only a keyed hash is stored. Delivery is
configurable: OTP_DELIVERY=log writes the code to the server log (terminal /
`docker compose logs backend`), OTP_DELIVERY=email queues an email for the worker.

Accounts with an authenticator app get a "totp" challenge instead: nothing is sent, and the user
enters the app's current code or one of their single-use recovery codes.

Codes are used for: email verification at sign-up, the second step of sign-in, password reset.
"""

import logging
from datetime import timedelta
from math import ceil

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import clock, metrics
from app.core.config import settings
from app.core.database import SessionLocal, transaction
from app.core.exceptions import AuthenticationError, BusinessRuleError, TooManyRequestsError
from app.core.security import generate_otp, hash_otp, new_opaque_token, otp_matches
from app.models import OtpChallenge, OtpPurpose, User
from app.services import audit_service, mfa_service, notification_service

logger = logging.getLogger("sims.otp")

PURPOSE_LABELS = notification_service.OTP_PURPOSE_LABELS
METHOD_CODE = "code"
METHOD_TOTP = "totp"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2] if len(local) > 2 else local[:1]}***@{domain}"


def resend_available_in(challenge: OtpChallenge) -> int:
    if challenge.method != METHOD_CODE:
        return 0
    ready_at = challenge.last_sent_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    return max(0, ceil((ready_at - clock.utcnow()).total_seconds()))


def expires_in(challenge: OtpChallenge) -> int:
    return max(0, ceil((challenge.expires_at - clock.utcnow()).total_seconds()))


def start(
    db: Session, user: User, purpose: OtpPurpose, *, method: str = METHOD_CODE
) -> tuple[OtpChallenge, str | None]:
    """Create a new challenge (replacing any open one for the same purpose). Returns the code to deliver,
    or None for authenticator-app challenges."""
    now = clock.utcnow()
    code = generate_otp() if method == METHOD_CODE else None
    challenge_id = new_opaque_token()
    with transaction(db):
        # Serialise challenge replacement with password changes and second-factor redemption.
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        # Housekeeping keeps the table small: long-expired challenges are useless.
        db.execute(delete(OtpChallenge).where(OtpChallenge.expires_at < now - timedelta(days=1)))
        # Only the newest challenge for this user and purpose works.
        db.execute(
            update(OtpChallenge)
            .where(
                OtpChallenge.user_id == user.id,
                OtpChallenge.purpose == purpose,
                OtpChallenge.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        challenge = OtpChallenge(
            id=challenge_id,
            user_id=user.id,
            purpose=purpose,
            method=method,
            # authenticator challenges have no code: store an unmatchable hash
            code_hash=hash_otp(challenge_id, code or new_opaque_token()),
            expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
            attempts=0,
            send_count=1 if code else 0,
            last_sent_at=now,
        )
        db.add(challenge)
        if code is not None and settings.OTP_DELIVERY == "email":
            notification_service.enqueue_otp(
                db,
                email=user.email,
                name=user.name,
                purpose=purpose,
                code=code,
                expires_at=challenge.expires_at,
                challenge_id=challenge.id,
                send_count=challenge.send_count,
            )
    return challenge, code


def _open_challenge(db: Session, challenge_id: str) -> OtpChallenge:
    """Lock the challenge row so parallel guesses are counted one at a time."""
    user_id = db.scalar(select(OtpChallenge.user_id).where(OtpChallenge.id == challenge_id))
    if user_id is not None:
        # Always lock user before challenge, matching password resets and challenge creation.
        # Refresh the identity map so a TOTP time step used by another request cannot be replayed.
        db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    challenge = db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.id == challenge_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    # Password-reset codes are only redeemable through /auth/password/reset, never for a session.
    if challenge is None or challenge.consumed_at is not None or challenge.purpose == OtpPurpose.PASSWORD_RESET:
        raise BusinessRuleError("This code is no longer valid. Please start again.", code="OTP_INVALID_CHALLENGE")
    if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise BusinessRuleError("Too many incorrect codes. Please start again.", code="OTP_LOCKED")
    return challenge


def _wrong_code(db: Session, challenge: OtpChallenge) -> None:
    challenge.attempts += 1
    remaining = settings.OTP_MAX_ATTEMPTS - challenge.attempts
    audit_service.record(
        db,
        "auth.otp.failed",
        actor=challenge.user,
        outcome="failure",
        entity_type="otp_challenge",
        details={"purpose": challenge.purpose.value, "method": challenge.method, "remaining_attempts": remaining},
    )
    db.commit()  # a wrong guess must count even though this request fails
    metrics.AUTH_EVENTS.labels("otp", "failure").inc()
    if remaining <= 0:
        raise BusinessRuleError("Too many incorrect codes. Please start again.", code="OTP_LOCKED")
    raise BusinessRuleError(
        f"Incorrect code. {remaining} attempt{'s' if remaining != 1 else ''} left.",
        code="OTP_INCORRECT",
        details={"remaining_attempts": remaining},
    )


def verify(
    db: Session,
    challenge_id: str,
    code: str | None,
    recovery_code: str | None = None,
    *,
    commit: bool = True,
) -> tuple[User, OtpPurpose, str]:
    """Check the second factor. Returns the user, the challenge purpose and the method used."""
    try:
        challenge = _open_challenge(db, challenge_id)
        now = clock.utcnow()
        if now >= challenge.expires_at:
            raise BusinessRuleError("This code has expired. Request a new one.", code="OTP_EXPIRED")
        user = challenge.user
        if challenge.method == METHOD_TOTP:
            if recovery_code is not None:
                matched, method = mfa_service.use_recovery_code(db, user, recovery_code), "recovery_code"
            else:
                matched, method = code is not None and mfa_service.verify_totp(user, code), METHOD_TOTP
        else:
            if recovery_code is not None:
                raise BusinessRuleError("Recovery codes are only for accounts with an authenticator app")
            matched, method = code is not None and otp_matches(challenge.id, code, challenge.code_hash), METHOD_CODE
        if not matched:
            _wrong_code(db, challenge)
        if not user.is_active:
            raise AuthenticationError("This account is disabled", code="ACCOUNT_DISABLED")
        challenge.consumed_at = now
        if challenge.purpose == OtpPurpose.SIGNUP and user.email_verified_at is None:
            user.email_verified_at = now
            audit_service.record(db, "auth.signup.verified", actor=user, entity_type="user", entity_id=user.id)
        if method == "recovery_code":
            notification_service.enqueue_security_notice(db, user, "recovery_code_used")
        purpose = challenge.purpose
        if commit:
            db.commit()
        else:
            # The route commits redemption and session creation together, retaining the user lock.
            db.flush()
        metrics.AUTH_EVENTS.labels("otp", "success").inc()
        return user, purpose, method
    except Exception:
        db.rollback()
        raise


def invalidate(db: Session, user_id: int, *, purpose: OtpPurpose | None = None) -> None:
    """Cancel outstanding proofs after credentials change, inside the caller's transaction."""
    stmt = update(OtpChallenge).where(OtpChallenge.user_id == user_id, OtpChallenge.consumed_at.is_(None))
    if purpose is not None:
        stmt = stmt.where(OtpChallenge.purpose == purpose)
    db.execute(stmt.values(consumed_at=clock.utcnow()))


def resend(db: Session, challenge_id: str) -> tuple[OtpChallenge, str, User]:
    """Issue a fresh code on the same challenge (the previous code stops working)."""
    try:
        challenge = _open_challenge(db, challenge_id)
        if challenge.method != METHOD_CODE:
            raise BusinessRuleError("Open your authenticator app for the current code", code="OTP_NOT_RESENDABLE")
        wait = resend_available_in(challenge)
        if wait > 0:
            raise TooManyRequestsError(f"Please wait {wait} seconds before requesting another code.", retry_after=wait)
        if challenge.send_count >= settings.OTP_MAX_SENDS:
            raise BusinessRuleError("Too many codes requested. Please start again.", code="OTP_RESEND_LIMIT")
        now = clock.utcnow()
        code = generate_otp()
        challenge.code_hash = hash_otp(challenge.id, code)
        challenge.expires_at = now + timedelta(seconds=settings.OTP_TTL_SECONDS)
        challenge.attempts = 0
        challenge.send_count += 1
        challenge.last_sent_at = now
        user = challenge.user
        if settings.OTP_DELIVERY == "email":
            notification_service.enqueue_otp(
                db,
                email=user.email,
                name=user.name,
                purpose=challenge.purpose,
                code=code,
                expires_at=challenge.expires_at,
                challenge_id=challenge.id,
                send_count=challenge.send_count,
            )
        db.commit()
        return challenge, code, user
    except Exception:
        db.rollback()
        raise


def deliver(email: str, name: str, purpose: OtpPurpose, code: str) -> None:
    """Hand the code to its owner. Runs as a background task once the response has been sent."""
    minutes = max(1, settings.OTP_TTL_SECONDS // 60)
    label = PURPOSE_LABELS[purpose]
    if settings.OTP_DELIVERY == "email":
        with SessionLocal() as db:
            notification_service.enqueue_otp(
                db,
                email=email,
                name=name,
                purpose=purpose,
                code=code,
                expires_at=clock.utcnow() + timedelta(seconds=settings.OTP_TTL_SECONDS),
            )
            db.commit()
        return
    # OTP_DELIVERY=log: the code goes to the server terminal / container log for the user to read.
    logger.warning("OTP for %s (%s): %s - valid for %d minutes", email, label, code, minutes)


# ----------------------------------------------------------------------------- password reset


def find_reset_challenge(db: Session, user: User) -> OtpChallenge | None:
    return db.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.user_id == user.id,
            OtpChallenge.purpose == OtpPurpose.PASSWORD_RESET,
            OtpChallenge.consumed_at.is_(None),
        )
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
        .with_for_update()
    )


def verify_reset_code(db: Session, user: User, code: str) -> bool:
    """Check a password-reset code without saying why it failed (the reply must not reveal whether
    the account exists). The caller commits."""
    challenge = find_reset_challenge(db, user)
    if challenge is None or challenge.attempts >= settings.OTP_MAX_ATTEMPTS or clock.utcnow() >= challenge.expires_at:
        return False
    if not otp_matches(challenge.id, code, challenge.code_hash):
        challenge.attempts += 1
        return False
    challenge.consumed_at = clock.utcnow()
    return True
