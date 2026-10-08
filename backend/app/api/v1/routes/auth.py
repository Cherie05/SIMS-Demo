"""Sign-up, two-step sign-in, password recovery, sessions and authenticator apps.

    sign up:   POST /signup  -> code challenge -> POST /otp/verify -> session
    sign in:   POST /login   -> challenge (emailed/logged code, or authenticator app) -> POST /otp/verify
    session:   POST /refresh (rotating httpOnly cookie) -> new access token;  POST /logout
    password:  POST /password/forgot -> code -> POST /password/reset;  POST /password/change
    devices:   GET /sessions;  DELETE /sessions/{id};  POST /sessions/revoke-all
    MFA:       GET /mfa;  POST /mfa/totp/setup -> /mfa/totp/enable;  /mfa/totp/disable;  /mfa/recovery-codes

A session is a short-lived JWT access token (returned in the body, kept in memory by the web app)
plus a refresh token that only ever travels in an httpOnly, SameSite=Strict cookie.
"""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentPrincipal, CurrentUser, DbSession
from app.core import clock, metrics
from app.core.config import settings
from app.core.exceptions import AuthenticationError, BusinessRuleError, PermissionDeniedError, error_body
from app.core.password_policy import MAX_LENGTH, MIN_LENGTH
from app.core.rate_limit import login_limiter, reset_limiter, signup_limiter
from app.models import OtpChallenge, OtpPurpose, User
from app.schemas.auth import (
    AuthConfigOut,
    MfaStatusOut,
    OtpChallengeOut,
    OtpResendRequest,
    OtpVerifyRequest,
    PasswordChangeRequest,
    PasswordConfirmRequest,
    PasswordForgotOut,
    PasswordForgotRequest,
    PasswordResetRequest,
    RecoveryCodesOut,
    RevokedCountOut,
    SessionInfoOut,
    SessionOut,
    SignupRequest,
    TotpDisableRequest,
    TotpEnableRequest,
    TotpSetupOut,
)
from app.schemas.user import CurrentUserOut, LoginRequest
from app.services import (
    audit_service,
    feature_flags,
    mfa_service,
    otp_service,
    session_service,
    user_service,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

COOKIE_PATH = f"{settings.API_V1_PREFIX}/auth"
CSRF_HEADER = "X-Requested-With"
RESET_SENT = "If an account exists for this email, we've sent it a code to reset the password."


def _client(request: Request) -> tuple[str, str | None]:
    return (request.client.host if request.client else "unknown"), request.headers.get("user-agent")


def _require_csrf_header(request: Request) -> None:
    """Cookie-authenticated endpoints also need a custom header, which cross-site pages can't send."""
    if not request.headers.get(CSRF_HEADER):
        raise PermissionDeniedError(f"Missing {CSRF_HEADER} header", code="CSRF_CHECK_FAILED")


def _set_refresh_cookie(response: Response, session: session_service.IssuedSession) -> None:
    max_age = max(1, int((session.refresh_expires_at - clock.utcnow()).total_seconds()))
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        session.refresh_token,
        max_age=max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME, path=COOKIE_PATH, httponly=True, secure=settings.cookie_secure, samesite="strict"
    )


def _session_out(response: Response, session: session_service.IssuedSession) -> SessionOut:
    _set_refresh_cookie(response, session)
    return SessionOut(
        access_token=session.access_token,
        expires_in=session.expires_in,
        session_id=session.session.id,
        session_expires_in=session.session_expires_in,
        user=CurrentUserOut.model_validate(session.user),
    )


def _challenge_out(challenge: OtpChallenge, user: User) -> OtpChallengeOut:
    totp = challenge.method == otp_service.METHOD_TOTP
    return OtpChallengeOut(
        challenge_id=challenge.id,
        purpose=challenge.purpose,
        method="totp" if totp else "code",
        delivery="authenticator" if totp else settings.OTP_DELIVERY,
        destination=None if totp else otp_service.mask_email(user.email),
        expires_in=otp_service.expires_in(challenge),
        resend_available_in=otp_service.resend_available_in(challenge),
    )


def _send_code(background: BackgroundTasks, user: User, purpose: OtpPurpose, code: str) -> None:
    # Emailed codes were queued atomically with their challenge; local log delivery happens here.
    if settings.OTP_DELIVERY == "log":
        background.add_task(otp_service.deliver, user.email, user.name, purpose, code)


def _signup_enabled(db) -> bool:
    return settings.SIGNUP_ENABLED and feature_flags.is_enabled(db, "auth.signup")


# ---------------------------------------------------------------------------------------------- sign-up / sign-in


@router.get("/config", response_model=AuthConfigOut, summary="Public settings for the sign-in pages")
def auth_config(db: DbSession):
    return AuthConfigOut(
        signup_enabled=_signup_enabled(db),
        signup_allowed_domains=settings.signup_allowed_domains,
        login_otp_required=settings.LOGIN_OTP_REQUIRED,
        otp_delivery=settings.OTP_DELIVERY,
        demo_accounts=not settings.is_deployed,
        session_idle_timeout_seconds=settings.session_idle_timeout_seconds,
        password_min_length=MIN_LENGTH,
        password_max_length=MAX_LENGTH,
    )


@router.post(
    "/signup",
    response_model=OtpChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an account (Sales role); continue with the emailed/logged code",
)
def signup(data: SignupRequest, request: Request, db: DbSession, background: BackgroundTasks):
    ip, _ = _client(request)
    if not _signup_enabled(db):
        raise PermissionDeniedError(
            "Self sign-up is turned off. Ask an administrator for an account.", code="SIGNUP_DISABLED"
        )
    signup_limiter.hit(f"ip:{ip}", "Too many sign-ups from this network. Please try again later.")
    user = user_service.register(db, data)
    challenge, code = otp_service.start(db, user, OtpPurpose.SIGNUP)
    if code:
        _send_code(background, user, OtpPurpose.SIGNUP, code)
    return _challenge_out(challenge, user)


@router.post(
    "/login",
    response_model=OtpChallengeOut | SessionOut,
    summary="Check email and password; continue with the second factor",
    responses={429: {"description": "Too many failed attempts; see the Retry-After header"}},
)
def login(data: LoginRequest, request: Request, response: Response, db: DbSession, background: BackgroundTasks):
    ip, user_agent = _client(request)
    login_limiter.check(data.email, ip)
    try:
        user = user_service.authenticate(db, data.email, data.password)
    except AuthenticationError as exc:
        login_limiter.record_failure(data.email, ip)
        metrics.AUTH_EVENTS.labels("password", "failure").inc()
        audit_service.record_now(
            "auth.login.failed", outcome="failure", actor_email=data.email.lower(), details={"reason": exc.code}
        )
        if login_limiter.is_locked(data.email):
            audit_service.record_now(
                "auth.account.locked",
                outcome="failure",
                actor_email=data.email.lower(),
                details={"window_seconds": settings.LOGIN_FAILURE_WINDOW_SECONDS},
            )
        raise
    login_limiter.reset(data.email)
    metrics.AUTH_EVENTS.labels("password", "success").inc()

    if not user.is_verified:
        purpose, method = OtpPurpose.SIGNUP, otp_service.METHOD_CODE  # finish the sign-up started earlier
    elif user.totp_enabled:
        purpose, method = OtpPurpose.LOGIN, otp_service.METHOD_TOTP
    elif settings.LOGIN_OTP_REQUIRED:
        purpose, method = OtpPurpose.LOGIN, otp_service.METHOD_CODE
    else:
        issued = session_service.start(db, user, user_agent=user_agent, ip=ip, mfa_method="none")
        return _session_out(response, issued)

    challenge, code = otp_service.start(db, user, purpose, method=method)
    if code:
        _send_code(background, user, purpose, code)
    return _challenge_out(challenge, user)


@router.post("/otp/verify", response_model=SessionOut, summary="Exchange the second factor for a session")
def verify_otp(data: OtpVerifyRequest, request: Request, response: Response, db: DbSession):
    ip, user_agent = _client(request)
    try:
        user, _purpose, method = otp_service.verify(db, data.challenge_id, data.code, data.recovery_code, commit=False)
        issued = session_service.start(db, user, user_agent=user_agent, ip=ip, mfa_method=method)
    except Exception:
        # Release second-factor locks even if session creation fails before opening its unit of work.
        db.rollback()
        raise
    return _session_out(response, issued)


@router.post("/otp/resend", response_model=OtpChallengeOut, summary="Send a new code for the same challenge")
def resend_otp(data: OtpResendRequest, db: DbSession, background: BackgroundTasks):
    challenge, code, user = otp_service.resend(db, data.challenge_id)
    _send_code(background, user, challenge.purpose, code)
    return _challenge_out(challenge, user)


@router.post(
    "/refresh",
    response_model=SessionOut,
    summary="Rotate the refresh cookie and get a new access token",
    responses={204: {"description": "No session cookie: the visitor is simply not signed in"}},
)
def refresh(request: Request, response: Response, db: DbSession):
    _require_csrf_header(request)
    ip, user_agent = _client(request)
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        # Not signed in is a normal state (every anonymous page load asks), not an error.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        issued = session_service.refresh(db, token, user_agent=user_agent, ip=ip)
    except AuthenticationError as exc:
        failed = JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))
        if exc.code != "SESSION_REFRESH_RACE":
            _clear_refresh_cookie(failed)
        return failed
    return _session_out(response, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
def logout(request: Request, db: DbSession):
    _require_csrf_header(request)
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if token:
        session_service.revoke(db, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=CurrentUserOut, summary="Current user, with their permissions")
def me(user: CurrentUser):
    return user


# ---------------------------------------------------------------------------------------------- passwords


@router.post(
    "/password/forgot",
    response_model=PasswordForgotOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a password-reset code (same reply whether or not the account exists)",
)
def forgot_password(data: PasswordForgotRequest, request: Request, db: DbSession, background: BackgroundTasks):
    ip, _ = _client(request)
    message = "Too many password reset requests. Please try again later."
    reset_limiter.hit(f"ip:{ip}", message)
    reset_limiter.hit(f"email:{data.email.lower()}", message)
    started = user_service.start_password_reset(db, data.email)
    if started is not None:
        user, code = started
        _send_code(background, user, OtpPurpose.PASSWORD_RESET, code)
    return PasswordForgotOut(
        message=RESET_SENT,
        delivery=settings.OTP_DELIVERY,
        expires_in=settings.OTP_TTL_SECONDS,
        resend_available_in=settings.OTP_RESEND_COOLDOWN_SECONDS,
    )


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password with the reset code; every session is signed out",
)
def reset_password(data: PasswordResetRequest, request: Request, db: DbSession):
    ip, _ = _client(request)
    login_limiter.check(data.email, ip)  # guessing reset codes counts like guessing passwords
    try:
        user_service.reset_password(db, data.email, data.code, data.new_password)
    except BusinessRuleError as exc:
        if exc.code == "RESET_CODE_INVALID":
            login_limiter.record_failure(data.email, ip)
        raise
    login_limiter.reset(data.email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password/change",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your password; your other devices are signed out",
)
def change_password(data: PasswordChangeRequest, request: Request, principal: CurrentPrincipal, db: DbSession):
    ip, _ = _client(request)
    user_service.change_password(
        db, principal.user, data.current_password, data.new_password, session_id=principal.session_id, ip=ip
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------------------------- sessions (devices)


@router.get("/sessions", response_model=list[SessionInfoOut], summary="Devices signed in to your account")
def list_sessions(principal: CurrentPrincipal, db: DbSession):
    return [
        SessionInfoOut(
            id=row.id,
            current=row.id == principal.session_id,
            authenticated_at=row.authenticated_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            user_agent=row.user_agent,
            ip_address=row.ip_address,
            mfa_method=row.mfa_method,
        )
        for row in session_service.list_active(db, principal.user.id)
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out one device")
def revoke_session(session_id: str, principal: CurrentPrincipal, db: DbSession):
    session_service.revoke_one(db, principal.user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/revoke-all",
    response_model=RevokedCountOut,
    summary="Sign out everywhere (keep_current=true keeps this device signed in)",
)
def revoke_all_sessions(principal: CurrentPrincipal, response: Response, db: DbSession, keep_current: bool = True):
    count = session_service.revoke_everywhere(
        db, principal.user, keep_session_id=principal.session_id if keep_current else None
    )
    if not keep_current:
        _clear_refresh_cookie(response)
    return RevokedCountOut(revoked=count)


# ---------------------------------------------------------------------------------------------- authenticator app


def _mfa_status(db, user: User) -> MfaStatusOut:
    second_step: Literal["code", "none"] = "code" if settings.LOGIN_OTP_REQUIRED else "none"
    return MfaStatusOut(
        totp_enabled=user.totp_enabled,
        totp_enabled_at=user.totp_enabled_at,
        recovery_codes_remaining=mfa_service.recovery_codes_remaining(db, user),
        method="totp" if user.totp_enabled else second_step,
    )


@router.get("/mfa", response_model=MfaStatusOut, summary="Second-factor status")
def mfa_status(user: CurrentUser, db: DbSession):
    return _mfa_status(db, user)


@router.post(
    "/mfa/totp/setup",
    response_model=TotpSetupOut,
    summary="Start authenticator-app setup (needs your password); confirm with /mfa/totp/enable",
)
def totp_setup(data: PasswordConfirmRequest, request: Request, user: CurrentUser, db: DbSession):
    ip, _ = _client(request)
    secret, uri, qr = mfa_service.setup(db, user, data.password, ip)
    return TotpSetupOut(secret=secret, otpauth_uri=uri, qr_svg_data_uri=qr)


@router.post(
    "/mfa/totp/enable",
    response_model=RecoveryCodesOut,
    summary="Confirm the app's code; returns single-use recovery codes (shown once)",
)
def totp_enable(data: TotpEnableRequest, request: Request, user: CurrentUser, db: DbSession):
    ip, _ = _client(request)
    login_limiter.check(user.email, ip)
    try:
        codes = mfa_service.enable(db, user, data.code)
    except BusinessRuleError as exc:
        if exc.code == "OTP_INCORRECT":
            login_limiter.record_failure(user.email, ip)
        raise
    login_limiter.reset(user.email)
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/mfa/totp/disable", status_code=status.HTTP_204_NO_CONTENT, summary="Turn the authenticator app off")
def totp_disable(data: TotpDisableRequest, request: Request, user: CurrentUser, db: DbSession):
    ip, _ = _client(request)
    mfa_service.disable(db, user, data.password, ip)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/mfa/recovery-codes",
    response_model=RecoveryCodesOut,
    summary="Replace your recovery codes (the old ones stop working)",
)
def regenerate_recovery_codes(data: PasswordConfirmRequest, request: Request, user: CurrentUser, db: DbSession):
    ip, _ = _client(request)
    return RecoveryCodesOut(recovery_codes=mfa_service.regenerate_recovery_codes(db, user, data.password, ip))
