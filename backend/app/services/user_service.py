from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import settings
from app.core.database import transaction
from app.core.exceptions import (
    AuthenticationError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableError,
)
from app.core.password_policy import contextual_problems
from app.core.security import hash_password, password_needs_rehash, verify_password
from app.models import OtpPurpose, User, UserRole
from app.schemas.auth import SignupRequest
from app.schemas.user import UserCreate, UserUpdate
from app.services import audit_service, notification_service, otp_service, session_service
from app.services.pagination import paginate

# Compared against when the email is unknown, so response time doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("timing-attack-guard-1")
AUDITED_FIELDS = ["name", "email", "role", "is_active"]


def _check_password_context(password: str, email: str, name: str | None) -> None:
    problems = contextual_problems(password, email, name)
    if problems:
        raise UnprocessableError(
            f"Password {problems[0]}", code="PASSWORD_POLICY", details=[{"field": "password", "message": problems[0]}]
        )


def authenticate(db: Session, email: str, password: str) -> User:
    """Check the password. Email verification and the second factor are handled by the caller."""
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthenticationError("Invalid email or password", code="INVALID_CREDENTIALS")
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid email or password", code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise AuthenticationError("This account is disabled", code="ACCOUNT_DISABLED")
    if password_needs_rehash(user.password_hash):
        # Transparent upgrade: legacy bcrypt (or weaker Argon2) hashes become today's Argon2id.
        with transaction(db):
            user.password_hash = hash_password(password)
        db.refresh(user)
    return user


def register(db: Session, data: SignupRequest) -> User:
    """Self-service sign-up. The account can't sign in until its email is verified with a code."""
    if not settings.SIGNUP_ENABLED:
        raise PermissionDeniedError(
            "Self sign-up is turned off. Ask an administrator for an account.", code="SIGNUP_DISABLED"
        )
    email = data.email.lower()
    allowed = settings.signup_allowed_domains
    if allowed and email.rsplit("@", 1)[-1] not in allowed:
        raise BusinessRuleError(
            f"Sign-up is limited to {', '.join('@' + d for d in allowed)} addresses",
            code="EMAIL_DOMAIN_NOT_ALLOWED",
        )
    _check_password_context(data.password, email, data.name)
    with transaction(db):
        user = db.scalar(select(User).where(User.email == email).with_for_update())
        if user is not None and user.is_verified:
            raise ConflictError("An account with this email already exists. Sign in instead.", code="EMAIL_TAKEN")
        if user is None:
            user = User(name=data.name, email=email, password_hash=hash_password(data.password), role=UserRole.SALES)
            db.add(user)
            db.flush()
            audit_service.record(
                db, "auth.signup.started", actor_id=user.id, actor_email=email, entity_type="user", entity_id=user.id
            )
        else:
            # An unfinished sign-up for this address: start over with the new details.
            user.name = data.name
            user.password_hash = hash_password(data.password)
    db.refresh(user)
    return user


def list_users(db: Session, *, role: UserRole | None, page: int, page_size: int):
    stmt = select(User).order_by(User.name)
    if role:
        stmt = stmt.where(User.role == role)
    return paginate(db, stmt, page, page_size)


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user


def create_user(db: Session, data: UserCreate, acting_user: User) -> User:
    _check_password_context(data.password, data.email, data.name)
    with transaction(db):
        email = data.email.lower()
        if db.scalar(select(User.id).where(User.email == email)):
            raise ConflictError(f"A user with email '{email}' already exists", code="DUPLICATE_EMAIL")
        user = User(
            name=data.name,
            email=email,
            role=data.role,
            password_hash=hash_password(data.password),
            email_verified_at=clock.utcnow(),  # created by an admin, who vouches for the address
        )
        db.add(user)
        db.flush()
        audit_service.record(
            db,
            "user.created",
            actor=acting_user,
            entity_type="user",
            entity_id=user.id,
            changes={field: {"old": None, "new": getattr(user, field)} for field in AUDITED_FIELDS},
        )
    db.refresh(user)
    return user


def _ensure_another_active_admin(db: Session, user: User) -> None:
    others = db.scalar(
        select(func.count(User.id)).where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id)
    )
    if not others:
        raise BusinessRuleError(
            "This is the last active administrator. Make someone else an admin first.", code="LAST_ADMIN"
        )


def update_user(db: Session, user_id: int, data: UserUpdate, acting_user: User) -> User:
    with transaction(db):
        # Lock the administrator roster before any target row. Two admins editing each other
        # must not both count the other as active and remove the final administrator.
        db.scalars(select(User.id).where(User.role == UserRole.ADMIN).order_by(User.id).with_for_update()).all()
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise NotFoundError(f"User {user_id} not found")
        changes = data.model_dump(exclude_unset=True)
        if user.id == acting_user.id and (
            changes.get("is_active") is False or changes.get("role", user.role) != user.role
        ):
            raise BusinessRuleError("You cannot deactivate yourself or change your own role", code="SELF_MODIFICATION")
        losing_admin = user.role == UserRole.ADMIN and (
            changes.get("is_active") is False or changes.get("role", UserRole.ADMIN) != UserRole.ADMIN
        )
        if losing_admin and user.is_active:
            _ensure_another_active_admin(db, user)

        before = audit_service.snapshot(user, AUDITED_FIELDS)
        end_sessions = False
        password_changed = False
        if "password" in changes:
            password = changes.pop("password")
            if password:
                _check_password_context(password, user.email, user.name)
                user.password_hash = hash_password(password)
                user.password_changed_at = clock.utcnow()
                end_sessions = password_changed = True
        if changes.get("is_active") is False:
            end_sessions = True
        for field, value in changes.items():
            setattr(user, field, value)
        if end_sessions:
            # New password or deactivated: sessions on other devices must not keep working.
            session_service.revoke_all(db, user.id, reason="admin")
            otp_service.invalidate(db, user.id)
        diff = audit_service.diff(before, audit_service.snapshot(user, AUDITED_FIELDS))
        if diff or password_changed:
            audit_service.record(
                db,
                "user.updated",
                actor=acting_user,
                entity_type="user",
                entity_id=user.id,
                changes=diff,
                details={"password_reset_by_admin": password_changed, "sessions_ended": end_sessions},
            )
        if "role" in diff:
            notification_service.enqueue_security_notice(
                db, user, "role_changed", {"old_role": diff["role"]["old"], "new_role": diff["role"]["new"]}
            )
        if password_changed:
            notification_service.enqueue_security_notice(db, user, "password_changed")
    db.refresh(user)
    return user


def get_approvers(db: Session) -> list[User]:
    """Managers receive approval requests; admins are the fallback if no manager exists."""
    active = (User.is_active.is_(True), User.email_verified_at.is_not(None))
    managers = db.scalars(select(User).where(User.role == UserRole.MANAGER, *active)).all()
    if managers:
        return list(managers)
    return list(db.scalars(select(User).where(User.role == UserRole.ADMIN, *active)).all())


# ----------------------------------------------------------------------------- passwords


def change_password(
    db: Session, user: User, current_password: str, new_password: str, *, session_id: str | None, ip: str
):
    """Signed-in change. Other devices are signed out; this one stays signed in."""
    from app.services import mfa_service

    mfa_service.check_password(user, current_password, ip)
    if verify_password(new_password, user.password_hash):
        raise BusinessRuleError("Choose a password different from the current one", code="PASSWORD_REUSED")
    _check_password_context(new_password, user.email, user.name)
    with transaction(db):
        locked_user = db.scalar(
            select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True)
        )
        if locked_user is None or not verify_password(current_password, locked_user.password_hash):
            raise BusinessRuleError("Your current password is incorrect", code="PASSWORD_INCORRECT")
        user = locked_user
        user.password_hash = hash_password(new_password)
        user.password_changed_at = clock.utcnow()
        otp_service.invalidate(db, user.id)
        ended = session_service.revoke_all(db, user.id, reason="password_changed", except_session_id=session_id)
        audit_service.record(
            db,
            "auth.password.changed",
            actor=user,
            entity_type="user",
            entity_id=user.id,
            details={"other_sessions_ended": ended},
        )
        notification_service.enqueue_security_notice(db, user, "password_changed")


def start_password_reset(db: Session, email: str) -> tuple[User, str] | None:
    """Returns (user, code) to deliver, or None when nothing should be sent: unknown, unverified or
    disabled account, or a code was sent moments ago. The caller replies identically either way."""
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None or not user.is_active or not user.is_verified:
        audit_service.record_now(
            "auth.password_reset.requested",
            outcome="failure",
            actor_email=email.lower(),
            details={"reason": "no account"},
        )
        return None
    challenge = otp_service.find_reset_challenge(db, user)
    db.rollback()  # release the row lock taken by the lookup
    if challenge is not None and clock.utcnow() < challenge.last_sent_at + timedelta(
        seconds=settings.OTP_RESEND_COOLDOWN_SECONDS
    ):
        return None
    _, code = otp_service.start(db, user, OtpPurpose.PASSWORD_RESET)
    audit_service.record_now("auth.password_reset.requested", actor=user, entity_type="user", entity_id=user.id)
    assert code is not None  # nosec B101 - reset challenges always use a code
    return user, code


def reset_password(db: Session, email: str, code: str, new_password: str) -> None:
    invalid = BusinessRuleError("That code is incorrect or has expired.", code="RESET_CODE_INVALID")
    user = db.scalar(select(User).where(User.email == email.lower()).with_for_update())
    if user is None or not user.is_active:
        db.rollback()
        raise invalid
    try:
        if not otp_service.verify_reset_code(db, user, code):
            audit_service.record(db, "auth.password_reset.failed", actor=user, outcome="failure")
            db.commit()  # the failed attempt counts
            raise invalid
        _check_password_context(new_password, user.email, user.name)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = clock.utcnow()
        otp_service.invalidate(db, user.id)
        session_service.revoke_all(db, user.id, reason="password_reset")
        audit_service.record(db, "auth.password_reset.completed", actor=user, entity_type="user", entity_id=user.id)
        notification_service.enqueue_security_notice(db, user, "password_reset")
        db.commit()
    except Exception:
        db.rollback()
        raise
