"""Idempotency-Key support for POST endpoints that create things (orders, stock movements).

A client sends a unique Idempotency-Key header per logical operation and reuses it when retrying
(timeout, lost connection, double click). The key is stored in the SAME transaction as the
resource it created, under a unique (user, scope, key) index, so even two concurrent retries
can't both succeed: the second one hits the index, rolls back, and is answered with the original
resource (header Idempotent-Replayed: true). Reusing a key with a different body is refused (422).
Keys are kept for 24 hours.
"""

import re
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import clock, metrics
from app.core.exceptions import BusinessRuleError, UnprocessableError
from app.core.security import request_fingerprint
from app.models import IdempotencyKey

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
TTL = timedelta(hours=24)
_VALID_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,255}$")


@dataclass(frozen=True)
class IdempotencyClaim:
    user_id: int
    scope: str
    key: str
    request_hash: str


def claim_from(request: Request, user_id: int, scope: str, body: BaseModel | None) -> IdempotencyClaim | None:
    key = request.headers.get(HEADER)
    if key is None:
        return None
    if not _VALID_KEY.match(key):
        raise BusinessRuleError(
            f"{HEADER} must be 8-255 characters of letters, digits and . _ : -", code="IDEMPOTENCY_KEY_INVALID"
        )
    canonical = body.model_dump_json().encode() if body is not None else b""
    return IdempotencyClaim(user_id, scope, key, request_fingerprint(canonical))


def lookup(db: Session, claim: IdempotencyClaim) -> IdempotencyKey | None:
    row = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.user_id == claim.user_id,
            IdempotencyKey.scope == claim.scope,
            IdempotencyKey.idem_key == claim.key,
        )
    )
    if row is None:
        return None
    if row.expires_at <= clock.utcnow():
        db.execute(delete(IdempotencyKey).where(IdempotencyKey.id == row.id))
        db.commit()
        return None
    if row.request_hash != claim.request_hash:
        raise UnprocessableError(
            f"This {HEADER} was already used for a different request", code="IDEMPOTENCY_KEY_REUSED"
        )
    metrics.IDEMPOTENT_REPLAYS.inc()
    return row


def reserve(db: Session, claim: IdempotencyClaim | None) -> IdempotencyKey | None:
    """Acquire the unique key before checking mutable business state or taking stock locks.

    Concurrent retries wait here for the first transaction, then hit the unique index so the
    route can replay its result. The placeholder is never committed: failures roll it back,
    and successful operations fill in their resource before committing.
    """
    if claim is None:
        return None
    row = IdempotencyKey(
        user_id=claim.user_id,
        scope=claim.scope,
        idem_key=claim.key,
        request_hash=claim.request_hash,
        resource_type="pending",
        resource_id=0,
        expires_at=clock.utcnow() + TTL,
    )
    db.add(row)
    db.flush()
    return row


def remember(reservation: IdempotencyKey | None, resource_type: str, resource_id: int) -> None:
    """Finish a reservation inside the same transaction that created the resource."""
    if reservation is not None:
        reservation.resource_type = resource_type
        reservation.resource_id = resource_id
