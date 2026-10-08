from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Set once the user proves they own the address (sign-up code), or when an admin creates the account.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Authenticator app (TOTP, RFC 6238). Secrets are encrypted at rest (DATA_ENCRYPTION_KEYS).
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Time step of the last accepted code: the same code can't be replayed within its window.
    totp_last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    # Set during enrolment, until the user proves the app works by entering a code
    totp_pending_secret_encrypted: Mapped[str | None] = mapped_column(Text)

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def totp_enabled(self) -> bool:
        return self.totp_enabled_at is not None and self.totp_secret_encrypted is not None
