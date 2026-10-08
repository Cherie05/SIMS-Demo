"""Authenticator-app (TOTP, RFC 6238) enrolment and recovery codes.

Enrolment is two-step: setup() stores a pending secret and returns it with a QR code; enable()
activates it only once the user proves the app produces valid codes. Secrets are encrypted at rest.
Each sign-in code is accepted once (its time step is remembered), and 10 single-use recovery codes
cover a lost phone. Changes need the current password and trigger a security email.
"""

import segno
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.database import transaction
from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.core.rate_limit import login_limiter
from app.models import MfaRecoveryCode, OtpPurpose, User
from app.services import audit_service, notification_service

RECOVERY_CODE_COUNT = 10


def _lock_user(db: Session, user: User) -> User:
    return db.scalars(
        select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True)
    ).one()


def _invalidate_sign_ins(db: Session, user: User) -> None:
    from app.services import otp_service

    otp_service.invalidate(db, user.id, purpose=OtpPurpose.LOGIN)


def check_password(user: User, password: str, ip: str) -> None:
    """Re-authentication for sensitive changes; wrong guesses count towards the sign-in lockout."""
    login_limiter.check(user.email, ip)
    if not security.verify_password(password, user.password_hash):
        login_limiter.record_failure(user.email, ip)
        audit_service.record_now("auth.reauth.failed", actor=user, outcome="failure")
        raise BusinessRuleError("Your current password is incorrect", code="PASSWORD_INCORRECT")


def recovery_codes_remaining(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(func.count(MfaRecoveryCode.id)).where(
                MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None)
            )
        )
        or 0
    )


def _new_recovery_codes(db: Session, user: User) -> list[str]:
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    codes = [security.generate_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    db.add_all(MfaRecoveryCode(user_id=user.id, code_hash=security.hash_recovery_code(user.id, c)) for c in codes)
    return codes


def setup(db: Session, user: User, password: str, ip: str) -> tuple[str, str, str]:
    """Start enrolment: returns (secret, otpauth URI, QR code as an SVG data URI)."""
    check_password(user, password, ip)
    secret = security.new_totp_secret()
    with transaction(db):
        user = _lock_user(db, user)
        user.totp_pending_secret_encrypted = security.encrypt(secret)
        audit_service.record(db, "auth.mfa.setup_started", actor=user, entity_type="user", entity_id=user.id)
    uri = security.totp_uri(secret, user.email)
    qr = segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#1c2625")
    return secret, uri, qr


def enable(db: Session, user: User, code: str) -> list[str]:
    """Activate the pending secret once the app's code checks out. Returns the recovery codes."""
    with transaction(db):
        user = _lock_user(db, user)
        if not user.totp_pending_secret_encrypted:
            raise ConflictError("Start the authenticator setup first", code="MFA_SETUP_NOT_STARTED")
        secret = security.decrypt(user.totp_pending_secret_encrypted)
        step = security.totp_match_step(secret, code, None)
        if step is None:
            raise BusinessRuleError(
                "That code doesn't match. Check the time on your phone and try again.", code="OTP_INCORRECT"
            )
        user.totp_secret_encrypted = user.totp_pending_secret_encrypted
        user.totp_pending_secret_encrypted = None
        user.totp_enabled_at = clock.utcnow()
        user.totp_last_used_step = step
        _invalidate_sign_ins(db, user)
        codes = _new_recovery_codes(db, user)
        audit_service.record(db, "auth.mfa.enabled", actor=user, entity_type="user", entity_id=user.id)
        notification_service.enqueue_security_notice(db, user, "totp_enabled")
    return codes


def disable(db: Session, user: User, password: str, ip: str) -> None:
    check_password(user, password, ip)
    with transaction(db):
        user = _lock_user(db, user)
        _clear(db, user)
        audit_service.record(db, "auth.mfa.disabled", actor=user, entity_type="user", entity_id=user.id)
        notification_service.enqueue_security_notice(db, user, "totp_disabled")


def regenerate_recovery_codes(db: Session, user: User, password: str, ip: str) -> list[str]:
    check_password(user, password, ip)
    with transaction(db):
        user = _lock_user(db, user)
        if not user.totp_enabled:
            raise ConflictError("Turn on the authenticator app first", code="MFA_NOT_ENABLED")
        codes = _new_recovery_codes(db, user)
        audit_service.record(
            db, "auth.mfa.recovery_codes_regenerated", actor=user, entity_type="user", entity_id=user.id
        )
    return codes


def admin_reset(db: Session, admin: User, user_id: int) -> User:
    """For a user who lost their phone and their recovery codes."""
    with transaction(db):
        user = db.scalar(
            select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
        )
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        if not user.totp_enabled:
            raise ConflictError("This user has no authenticator app to reset", code="MFA_NOT_ENABLED")
        _clear(db, user)
        audit_service.record(db, "user.mfa_reset", actor=admin, entity_type="user", entity_id=user.id)
        notification_service.enqueue_security_notice(db, user, "totp_disabled")
    db.refresh(user)
    return user


def _clear(db: Session, user: User) -> None:
    _invalidate_sign_ins(db, user)
    user.totp_secret_encrypted = None
    user.totp_pending_secret_encrypted = None
    user.totp_enabled_at = None
    user.totp_last_used_step = None
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))


# ----------------------------------------------------------------------------- sign-in checks


def verify_totp(user: User, code: str) -> bool:
    """Accept the app's current code once; the caller commits the remembered time step."""
    if not user.totp_enabled or user.totp_secret_encrypted is None:
        return False
    step = security.totp_match_step(security.decrypt(user.totp_secret_encrypted), code, user.totp_last_used_step)
    if step is None:
        return False
    user.totp_last_used_step = step
    return True


def use_recovery_code(db: Session, user: User, code: str) -> bool:
    row = db.scalar(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user.id,
            MfaRecoveryCode.code_hash == security.hash_recovery_code(user.id, code),
            MfaRecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        return False
    row.used_at = clock.utcnow()
    audit_service.record(db, "auth.mfa.recovery_code_used", actor=user, entity_type="user", entity_id=user.id)
    return True
