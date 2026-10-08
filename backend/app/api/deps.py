from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import context
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import Permission, has_permission
from app.core.rate_limit import api_limiter
from app.core.security import decode_access_token
from app.models import User
from app.services import session_service

# In Swagger, sign in with /auth/login + /auth/otp/verify, then paste the access_token into "Authorize".
bearer_scheme = HTTPBearer(auto_error=False, description="The access_token returned by /auth/otp/verify")

DbSession = Annotated[Session, Depends(get_db)]


@dataclass
class Principal:
    """The authenticated caller: the user and the session their access token belongs to."""

    user: User
    session_id: str


def get_principal(
    db: DbSession, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
) -> Principal:
    if credentials is None:
        raise AuthenticationError("Authentication required")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
        session_id = str(payload["sid"])
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Session expired, please sign in again", code="TOKEN_EXPIRED") from None
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AuthenticationError("Invalid authentication token", code="INVALID_TOKEN") from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or disabled", code="INVALID_TOKEN")
    # Signed out elsewhere, password changed, or revoked by an admin: the token stops working now.
    if session_service.get_active(db, session_id, user.id) is None:
        raise AuthenticationError("Your session has ended. Please sign in again.", code="SESSION_REVOKED")
    context.set_user(user.id)
    api_limiter.hit(f"user:{user.id}", settings.API_RATE_LIMIT_PER_USER_PER_MINUTE)
    return Principal(user, session_id)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def get_current_user(principal: CurrentPrincipal) -> User:
    return principal.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(permission: Permission) -> Callable[[User], User]:
    """Dependency factory: the caller must hold `permission` (default deny)."""

    def checker(user: CurrentUser) -> User:
        if not has_permission(user.role, permission):
            raise PermissionDeniedError(f"You don't have permission to do this ({permission.value})")
        return user

    checker.__name__ = f"require_{permission.name.lower()}"
    return checker


# Shorthands used by several routers
AdminUser = Annotated[User, Depends(require(Permission.USER_MANAGE))]
ApproverUser = Annotated[User, Depends(require(Permission.ORDER_APPROVE))]


def limit_by_client_ip(request: Request) -> None:
    """Coarse per-IP budget for every API call (per-user limits apply after authentication)."""
    ip = request.client.host if request.client else "unknown"
    api_limiter.hit(f"ip:{ip}", settings.API_RATE_LIMIT_PER_IP_PER_MINUTE)


class Pagination:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=10_000, description="1-based page number")] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        self.page = page
        self.page_size = page_size


PageParams = Annotated[Pagination, Depends()]
