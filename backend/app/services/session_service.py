"""Signed-in sessions.

A session (user_sessions row) is created when someone completes the full sign-in (password and
second factor). It ends when:
  - it has been idle for SESSION_IDLE_TIMEOUT_MINUTES (its refresh token is not used in time),
  - it reaches SESSION_ABSOLUTE_TIMEOUT_HOURS after sign-in, however active it is,
  - the user signs out (this device or every device), changes or resets their password, or an
    admin deactivates them or changes their password,
  - a refresh token of the session is replayed after rotation (likely theft).

Access tokens carry the session id (sid) and every API request checks the session is still active,
so revocation takes effect immediately rather than when the 15-minute token expires.

The refresh token is an opaque random string, sent in an httpOnly cookie and stored only as a
SHA-256 hash. Every refresh revokes the presented token and issues a new one.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.orm import Session

from app.core import clock, metrics
from app.core.config import settings
from app.core.database import transaction
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.security import create_access_token, hash_token, new_opaque_token, new_session_id
from app.models import RefreshToken, User, UserSession
from app.services import audit_service, notification_service

logger = logging.getLogger(__name__)

ROTATION_GRACE = timedelta(seconds=15)
SESSION_ENDED = "Your session has ended. Please sign in again."


@dataclass
class IssuedSession:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime
    session: UserSession
    user: User

    @property
    def session_expires_in(self) -> int:
        return max(0, int((self.session.expires_at - clock.utcnow()).total_seconds()))


def _refresh_expiry(session: UserSession, now: datetime) -> datetime:
    """Idle timeout, but never beyond the session's absolute end."""
    return min(now + timedelta(seconds=settings.session_idle_timeout_seconds), session.expires_at)


def _new_refresh_token(
    db: Session, session: UserSession, now: datetime, user_agent: str | None, ip: str | None
) -> tuple[RefreshToken, str]:
    plain = new_opaque_token()
    token = RefreshToken(
        user_id=session.user_id,
        session_id=session.id,
        token_hash=hash_token(plain),
        expires_at=_refresh_expiry(session, now),
        user_agent=(user_agent or "")[:255] or None,
        ip_address=(ip or "")[:45] or None,
    )
    db.add(token)
    db.flush()
    return token, plain


def _issued(user: User, session: UserSession, plain: str, token: RefreshToken) -> IssuedSession:
    access_token, expires_in = create_access_token(user.id, user.role.value, session.id)
    return IssuedSession(access_token, expires_in, plain, token.expires_at, session, user)


def _is_known_device(db: Session, user: User, user_agent: str | None, now: datetime) -> tuple[bool, bool]:
    """(has signed in before, has signed in before from this browser) over the last 90 days."""
    since = now - timedelta(days=90)
    previous = db.scalar(
        select(func.count(UserSession.id)).where(UserSession.user_id == user.id, UserSession.created_at >= since)
    )
    if not previous:
        return False, False
    same_browser = db.scalar(
        select(func.count(UserSession.id)).where(
            UserSession.user_id == user.id,
            UserSession.created_at >= since,
            UserSession.user_agent == ((user_agent or "")[:255] or None),
        )
    )
    return True, bool(same_browser)


def start(db: Session, user: User, *, user_agent: str | None, ip: str | None, mfa_method: str) -> IssuedSession:
    """Open a session after a complete sign-in."""
    now = clock.utcnow()
    with transaction(db):
        # Housekeeping keeps the table small: long-dead tokens are useless.
        db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now - timedelta(days=1)))
        signed_in_before, known_browser = _is_known_device(db, user, user_agent, now)
        session = UserSession(
            id=new_session_id(),
            user_id=user.id,
            authenticated_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.session_absolute_timeout_seconds),
            mfa_method=mfa_method,
            user_agent=(user_agent or "")[:255] or None,
            ip_address=(ip or "")[:45] or None,
        )
        db.add(session)
        db.flush()
        token, plain = _new_refresh_token(db, session, now, user_agent, ip)
        user.last_login_at = now
        new_device = signed_in_before and not known_browser
        audit_service.record(
            db,
            "auth.login.succeeded",
            actor=user,
            entity_type="session",
            entity_id=session.id,
            details={"mfa_method": mfa_method, "new_device": new_device},
        )
        if new_device:
            notification_service.enqueue_security_notice(
                db, user, "new_sign_in", {"ip_address": ip, "user_agent": user_agent, "at": now}
            )
    metrics.AUTH_EVENTS.labels("login", "success").inc()
    return _issued(user, session, plain, token)


def refresh(db: Session, plain: str, *, user_agent: str | None, ip: str | None) -> IssuedSession:
    try:
        token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(plain)).with_for_update())
        now = clock.utcnow()
        if token is None:
            raise AuthenticationError(SESSION_ENDED, code="SESSION_EXPIRED")
        session = (
            db.scalar(select(UserSession).where(UserSession.id == token.session_id).with_for_update())
            if token.session_id
            else None
        )
        if token.revoked_at is not None:
            benign_race = token.revoked_reason == "rotated" and now - token.revoked_at <= ROTATION_GRACE
            if benign_race:
                # A late response from the losing tab must not clear the winning tab's new cookie.
                raise AuthenticationError(
                    "Another tab refreshed this session. Please try again.", code="SESSION_REFRESH_RACE"
                )
            if not benign_race and session is not None and session.revoked_at is None:
                _revoke_sessions(db, [session.id], reason="reuse", now=now)
                user = db.get(User, token.user_id)
                audit_service.record(
                    db,
                    "auth.session.token_reuse",
                    actor=user,
                    outcome="failure",
                    entity_type="session",
                    entity_id=session.id,
                    details={"ip_address": ip},
                )
                if user is not None:
                    notification_service.enqueue_security_notice(db, user, "session_revoked_reuse", {"ip_address": ip})
                db.commit()
                # Logs ids only - never the token itself.
                logger.warning(  # nosemgrep: python-logger-credential-disclosure
                    "Refresh token reuse for user %s: session %s was revoked",
                    token.user_id,
                    session.id,
                    extra={"event": "auth.token_reuse"},
                )
            raise AuthenticationError(SESSION_ENDED, code="SESSION_EXPIRED")
        user = db.get(User, token.user_id)
        if (
            session is None
            or not session.is_active(now)
            or token.expires_at <= now
            or user is None
            or not user.is_active
        ):
            raise AuthenticationError(SESSION_ENDED, code="SESSION_EXPIRED")

        new_token, new_plain = _new_refresh_token(db, session, now, user_agent, ip)
        token.revoked_at, token.revoked_reason, token.replaced_by_id = now, "rotated", new_token.id
        session.last_seen_at = now
        session.ip_address = (ip or "")[:45] or session.ip_address
        db.commit()
        return _issued(user, session, new_plain, new_token)
    except Exception:
        db.rollback()
        raise


def get_active(db: Session, session_id: str, user_id: int) -> UserSession | None:
    """The session behind an access token, if it is still active (checked on every request)."""
    session = db.get(UserSession, session_id)
    now = clock.utcnow()
    if (
        session is None
        or session.user_id != user_id
        or not session.is_active(now)
        or session.last_seen_at + timedelta(seconds=settings.session_idle_timeout_seconds) <= now
    ):
        return None
    return session


def _revoke_sessions(db: Session, session_ids: list[str], *, reason: str, now: datetime | None = None) -> int:
    if not session_ids:
        return 0
    now = now or clock.utcnow()
    result = cast(
        CursorResult,
        db.execute(
            update(UserSession)
            .where(UserSession.id.in_(session_ids), UserSession.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason)
        ),
    )
    count = result.rowcount
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id.in_(session_ids), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason=reason)
    )
    return count or 0


def revoke(db: Session, plain: str) -> UserSession | None:
    """Sign out this device: the session behind the presented refresh token ends."""
    with transaction(db):
        token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(plain)))
        if token is None or token.session_id is None:
            return None
        _revoke_sessions(db, [token.session_id], reason="logout")
        session = db.get(UserSession, token.session_id)
        user = db.get(User, token.user_id)
        audit_service.record(db, "auth.logout", actor=user, entity_type="session", entity_id=token.session_id)
    return session


def revoke_all(db: Session, user_id: int, *, reason: str, except_session_id: str | None = None) -> int:
    """End every session of a user (optionally keeping one). Runs inside the caller's transaction."""
    stmt = select(UserSession.id).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session_id:
        stmt = stmt.where(UserSession.id != except_session_id)
    count = _revoke_sessions(db, list(db.scalars(stmt).all()), reason=reason)
    # Tokens from before sessions existed
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.session_id.is_(None), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.utcnow(), revoked_reason=reason)
    )
    return count


def list_active(db: Session, user_id: int) -> list[UserSession]:
    now = clock.utcnow()
    return list(
        db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                UserSession.last_seen_at > now - timedelta(seconds=settings.session_idle_timeout_seconds),
            )
            .order_by(UserSession.last_seen_at.desc())
        ).all()
    )


def revoke_one(db: Session, user: User, session_id: str) -> None:
    """Sign out one of the user's own devices."""
    with transaction(db):
        session = db.get(UserSession, session_id)
        if session is None or session.user_id != user.id:
            raise NotFoundError("Session not found")
        _revoke_sessions(db, [session.id], reason="revoked")
        audit_service.record(db, "auth.session.revoked", actor=user, entity_type="session", entity_id=session_id)


def revoke_everywhere(db: Session, user: User, *, keep_session_id: str | None) -> int:
    """Sign out every device (or every other device, when keep_session_id is given)."""
    with transaction(db):
        count = revoke_all(db, user.id, reason="logout_all", except_session_id=keep_session_id)
        audit_service.record(
            db,
            "auth.session.revoked_all",
            actor=user,
            details={"sessions_ended": count, "kept_current": keep_session_id is not None},
        )
    return count
