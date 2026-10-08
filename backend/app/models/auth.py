from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import OtpPurpose
from app.models.user import User


class OtpChallenge(Base):
    """A pending second-factor check. For emailed/logged codes only a keyed hash of the code is stored;
    for authenticator-app challenges there is no code at all (method = "totp")."""

    __tablename__ = "otp_challenges"

    # Random, unguessable id handed to the client; the code itself never leaves the server except
    # through the delivery channel (server log or email).
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose: Mapped[OtpPurpose] = mapped_column(Enum(OtpPurpose, name="otp_purpose"), nullable=False)
    # code: 6 digits sent by log/email;  totp: authenticator app (or a recovery code)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="code", server_default="code")
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    send_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship()


class UserSession(Base):
    """One signed-in device. Access tokens carry its id (sid), so revoking it takes effect at once."""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_revoked", "user_id", "revoked_at"),)

    # Random id; also the JWT "sid" claim
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # When the user proved who they are (password + second factor)
    authenticated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Absolute lifetime: the session ends at this time however active it is
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    # logout | logout_all | revoked | password_changed | password_reset | reuse | admin | mfa_changed
    revoked_reason: Mapped[str | None] = mapped_column(String(20))
    # code (log/email one-time code) | totp | recovery_code | none
    mfa_method: Mapped[str | None] = mapped_column(String(20))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship()

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at


class RefreshToken(Base):
    """A rotating credential for one session. Rotated on every use; stored as a SHA-256 hash."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("user_sessions.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Idle timeout: a token not used before this time is dead
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    # rotated | logout | reuse | admin | ...
    revoked_reason: Mapped[str | None] = mapped_column(String(20))
    replaced_by_id: Mapped[int | None] = mapped_column(ForeignKey("refresh_tokens.id", ondelete="SET NULL"))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    session: Mapped[UserSession | None] = relationship()


class MfaRecoveryCode(Base):
    """Single-use backup codes for when the authenticator app is unavailable. Stored as keyed hashes."""

    __tablename__ = "mfa_recovery_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
