"""Email notifications.

enqueue_*  called inside the business transaction: the job commits together with the change.
handle_*   run by the background worker; each is safe to repeat (at-least-once delivery).

Workflow emails (the PDF brief):
  approval_request  order above the threshold -> every manager (admins if there is no manager)
  order_decision    approved / rejected -> the order's creator
Account security emails: new-device sign-in, password changed/reset, authenticator changes,
role changes, session revoked after token reuse. Sign-in codes are emailed when OTP_DELIVERY=email.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core import clock, security
from app.core.config import settings
from app.models import OrderStatus, OtpChallenge, OtpPurpose, User
from app.services import email_service, outbox_service

logger = logging.getLogger(__name__)

APPROVAL_REQUEST = "email.approval_request"
ORDER_DECISION = "email.order_decision"
OTP_CODE = "email.otp_code"
SECURITY_NOTICE = "email.security_notice"

OTP_PURPOSE_LABELS = {
    OtpPurpose.SIGNUP: "email verification",
    OtpPurpose.LOGIN: "sign-in",
    OtpPurpose.PASSWORD_RESET: "password reset",
}

SECURITY_NOTICES: dict[str, tuple[str, str]] = {
    # kind: (subject, first paragraph)
    "new_sign_in": ("New sign-in to your account", "Your account was just signed in to from a new browser or device."),
    "password_changed": ("Your password was changed", "The password for your account was just changed."),
    "password_reset": ("Your password was reset", "The password for your account was just reset with a one-time code."),
    "totp_enabled": (
        "Authenticator app turned on",
        "Signing in now needs a code from your authenticator app.",
    ),
    "totp_disabled": (
        "Authenticator app turned off",
        "Your authenticator app is no longer used to sign in; one-time codes are used instead.",
    ),
    "recovery_code_used": (
        "A recovery code was used",
        "One of your recovery codes was just used to sign in. Each code works only once.",
    ),
    "role_changed": ("Your access level changed", "An administrator changed your role."),
    "session_revoked_reuse": (
        "We signed out a session for your safety",
        "A sign-in token for your account was used twice, which can mean it was copied. That session has been ended.",
    ),
    "signed_out_everywhere": ("You were signed out everywhere", "All sessions of your account were ended."),
}

SECURITY_FOOTER = "If this wasn't you, change your password now and contact your administrator."


def _links(order_id: int | None = None) -> dict[str, str]:
    base = settings.FRONTEND_URL.rstrip("/")
    links = {"approvals_url": f"{base}/approvals", "account_url": f"{base}/account"}
    if order_id is not None:
        links["order_url"] = f"{base}/orders/{order_id}"
    return links


# ----------------------------------------------------------------------------- enqueue


def enqueue_approval_requests(db: Session, order_id: int, approvers: list[User]) -> None:
    if not approvers:
        logger.error("Order %s needs approval but no active, verified manager or admin exists", order_id)
        return
    for approver in approvers:
        outbox_service.enqueue(
            db,
            APPROVAL_REQUEST,
            {"order_id": order_id, "recipient_id": approver.id},
            dedupe_key=f"approval_request:{order_id}:{approver.id}",
            order_id=order_id,
        )


def enqueue_decision(db: Session, order_id: int) -> None:
    outbox_service.enqueue(
        db, ORDER_DECISION, {"order_id": order_id}, dedupe_key=f"order_decision:{order_id}", order_id=order_id
    )


def enqueue_otp(
    db: Session,
    *,
    email: str,
    name: str,
    purpose: OtpPurpose,
    code: str,
    expires_at: datetime,
    challenge_id: str | None = None,
    send_count: int | None = None,
) -> None:
    payload = {"email": email, "name": name, "purpose": purpose.value, "code_encrypted": security.encrypt(code)}
    if challenge_id is not None:
        payload["challenge_id"] = challenge_id
    outbox_service.enqueue(
        db,
        OTP_CODE,
        # The code is encrypted while it waits, and scrubbed once it has been sent.
        payload,
        priority=outbox_service.PRIORITY_URGENT,
        expires_at=expires_at,
        max_attempts=3,
        dedupe_key=f"otp:{challenge_id}:{send_count}" if challenge_id is not None else None,
    )


def enqueue_security_notice(db: Session, user: User, kind: str, details: dict[str, Any] | None = None) -> None:
    if kind not in SECURITY_NOTICES:
        raise ValueError(f"Unknown security notice {kind}")
    outbox_service.enqueue(
        db,
        SECURITY_NOTICE,
        {"user_id": user.id, "kind": kind, "details": {k: str(v) for k, v in (details or {}).items() if v}},
        priority=outbox_service.PRIORITY_HIGH,
    )


# ----------------------------------------------------------------------------- handlers (worker)


class SkipJob(Exception):
    """Nothing to do any more (e.g. the order was already decided); the job completes quietly."""


def _send(
    db: Session, *, to: str, subject: str, template: str, context: dict[str, Any], order_id=None, log_subject=None
):
    message = email_service.build_message(to=to, subject=subject, template=template, context=context)
    status = email_service.send(message)
    email_service.log_outcome(
        db, to=to, subject=log_subject or subject, template=template, status=status, order_id=order_id
    )
    # The worker commits the delivery log together with the fenced job outcome.


def handle_approval_request(db: Session, payload: dict[str, Any]) -> None:
    from app.services import order_service  # avoid an import cycle at module load

    order = order_service.get_order(db, payload["order_id"])
    if order.status != OrderStatus.PENDING_APPROVAL:
        raise SkipJob(f"order {order.order_number} is {order.status.value}")
    recipient = db.get(User, payload["recipient_id"])
    if recipient is None or not recipient.is_active:
        raise SkipJob("recipient no longer active")
    _send(
        db,
        to=recipient.email,
        subject=f"Approval required: {order.order_number} ({order.total_amount:,.2f})",
        template="approval_request",
        context={"order": order, "recipient": recipient, **_links(order.id)},
        order_id=order.id,
    )


def handle_order_decision(db: Session, payload: dict[str, Any]) -> None:
    from app.services import order_service

    order = order_service.get_order(db, payload["order_id"])
    if order.approval is None:
        raise SkipJob("order has no approval")
    decision = order.approval.status.value.lower()
    _send(
        db,
        to=order.created_by.email,
        subject=f"Order {order.order_number} {decision}",
        template="order_decision",
        context={"order": order, "recipient": order.created_by, "decision": decision, **_links(order.id)},
        order_id=order.id,
    )


def handle_otp_code(db: Session, payload: dict[str, Any]) -> None:
    purpose = OtpPurpose(payload["purpose"])
    code = security.decrypt(payload["code_encrypted"])
    if challenge_id := payload.get("challenge_id"):
        challenge = db.get(OtpChallenge, challenge_id)
        if (
            challenge is None
            or challenge.consumed_at is not None
            or challenge.expires_at <= clock.utcnow()
            or not security.otp_matches(challenge_id, code, challenge.code_hash)
        ):
            raise SkipJob("one-time code was consumed, replaced, or expired")
    minutes = max(1, settings.OTP_TTL_SECONDS // 60)
    _send(
        db,
        to=payload["email"],
        subject=f"{code} is your SIMS verification code",
        log_subject="****** is your SIMS verification code",  # the delivery log never holds the code
        template="otp_code",
        context={
            "recipient_name": payload["name"],
            "code": code,
            "minutes": minutes,
            "purpose": OTP_PURPOSE_LABELS[purpose],
        },
    )


def handle_security_notice(db: Session, payload: dict[str, Any]) -> None:
    user = db.get(User, payload["user_id"])
    if user is None:
        raise SkipJob("user no longer exists")
    subject, intro = SECURITY_NOTICES[payload["kind"]]
    _send(
        db,
        to=user.email,
        subject=subject,
        template="security_notice",
        context={
            "recipient": user,
            "intro": intro,
            "details": payload.get("details") or {},
            "footer": SECURITY_FOOTER,
            **_links(),
        },
    )


HANDLERS = {
    APPROVAL_REQUEST: handle_approval_request,
    ORDER_DECISION: handle_order_decision,
    OTP_CODE: handle_otp_code,
    SECURITY_NOTICE: handle_security_notice,
}
# Payloads holding secrets are wiped once the job is done.
SCRUB_ON_COMPLETE = {OTP_CODE}
