from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.core.password_policy import MAX_LENGTH
from app.core.security import OTP_LENGTH
from app.models.enums import OtpPurpose
from app.schemas.common import InputModel, UtcDateTime
from app.schemas.user import CurrentUserOut, Password

OtpCode = Annotated[str, Field(pattern=rf"^\d{{{OTP_LENGTH}}}$", description=f"The {OTP_LENGTH}-digit code")]


class SignupRequest(InputModel):
    """Self-service sign-up. There is deliberately no role field: new accounts are always Sales."""

    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: Password


class OtpVerifyRequest(InputModel):
    challenge_id: str = Field(min_length=20, max_length=64)
    code: str | None = Field(default=None, pattern=rf"^\d{{{OTP_LENGTH}}}$", description="6-digit code")
    recovery_code: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9]{5}-?[A-Za-z0-9]{5}$",
        description="A single-use recovery code (accounts with an authenticator app)",
    )

    @model_validator(mode="after")
    def _one_factor(self):
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("Provide either code or recovery_code")
        return self


class OtpResendRequest(InputModel):
    challenge_id: str = Field(min_length=20, max_length=64)


class OtpChallengeOut(BaseModel):
    """Returned instead of a session when a second factor is needed to continue."""

    otp_required: Literal[True] = True
    challenge_id: str
    purpose: OtpPurpose
    # code: a 6-digit code delivered by log/email;  totp: from the user's authenticator app
    method: Literal["code", "totp"] = "code"
    delivery: Literal["log", "email", "authenticator"]
    destination: str | None = Field(default=None, description="Masked email address the code was sent to")
    expires_in: int
    resend_available_in: int
    code_length: int = OTP_LENGTH


class SessionOut(BaseModel):
    """A signed-in session. The refresh token travels separately, in an httpOnly cookie."""

    otp_required: Literal[False] = False
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    session_id: str
    # Seconds until the session ends regardless of activity
    session_expires_in: int
    user: CurrentUserOut


class AuthConfigOut(BaseModel):
    """Public settings the sign-in pages need before anyone is signed in."""

    signup_enabled: bool
    signup_allowed_domains: list[str]
    login_otp_required: bool
    otp_delivery: Literal["log", "email"]
    demo_accounts: bool
    session_idle_timeout_seconds: int
    password_min_length: int
    password_max_length: int


# ----------------------------------------------------------------------------- passwords


class PasswordForgotRequest(InputModel):
    email: EmailStr


class PasswordForgotOut(BaseModel):
    """Identical whether or not the account exists, so the form can't be used to discover accounts."""

    message: str
    delivery: Literal["log", "email"]
    expires_in: int
    resend_available_in: int
    code_length: int = OTP_LENGTH


class PasswordResetRequest(InputModel):
    email: EmailStr
    code: OtpCode
    new_password: Password


class PasswordChangeRequest(InputModel):
    current_password: str = Field(min_length=1, max_length=MAX_LENGTH)
    new_password: Password


class PasswordConfirmRequest(InputModel):
    """Re-authentication for sensitive account changes."""

    password: str = Field(min_length=1, max_length=MAX_LENGTH)


# ----------------------------------------------------------------------------- sessions


class SessionInfoOut(BaseModel):
    id: str
    current: bool
    authenticated_at: UtcDateTime
    last_seen_at: UtcDateTime
    expires_at: UtcDateTime
    user_agent: str | None
    ip_address: str | None
    mfa_method: str | None


class RevokedCountOut(BaseModel):
    revoked: int


# ----------------------------------------------------------------------------- authenticator app


class MfaStatusOut(BaseModel):
    totp_enabled: bool
    totp_enabled_at: UtcDateTime | None
    recovery_codes_remaining: int
    # What the second sign-in step uses today
    method: Literal["totp", "code", "none"]


class TotpSetupOut(BaseModel):
    secret: str = Field(description="Base32 secret, for typing into the app by hand")
    otpauth_uri: str
    qr_svg_data_uri: str


class TotpEnableRequest(InputModel):
    code: OtpCode


class TotpDisableRequest(InputModel):
    password: str = Field(min_length=1, max_length=MAX_LENGTH)


class RecoveryCodesOut(BaseModel):
    """Shown once. Each code works a single time."""

    recovery_codes: list[str]
