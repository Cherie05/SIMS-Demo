from fastapi import APIRouter, status

from app.api.deps import AdminUser, DbSession, PageParams
from app.core.database import transaction
from app.models import UserRole
from app.schemas.auth import RevokedCountOut
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services import audit_service, mfa_service, session_service, user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("", response_model=Page[UserOut])
def list_users(db: DbSession, _: AdminUser, pagination: PageParams, role: UserRole | None = None):
    return user_service.list_users(db, role=role, page=pagination.page, page_size=pagination.page_size)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: DbSession, admin: AdminUser):
    return user_service.create_user(db, data, admin)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: DbSession, admin: AdminUser):
    return user_service.update_user(db, user_id, data, admin)


@router.post(
    "/{user_id}/sessions/revoke",
    response_model=RevokedCountOut,
    summary="Sign a user out of every device (incident response)",
)
def revoke_user_sessions(user_id: int, db: DbSession, admin: AdminUser):
    user = user_service.get_user(db, user_id)
    with transaction(db):
        count = session_service.revoke_all(db, user.id, reason="admin")
        audit_service.record(
            db,
            "user.sessions_revoked",
            actor=admin,
            entity_type="user",
            entity_id=user.id,
            details={"sessions_ended": count},
        )
    return RevokedCountOut(revoked=count)


@router.post(
    "/{user_id}/mfa/reset",
    response_model=UserOut,
    summary="Remove a user's authenticator app (lost phone and recovery codes)",
)
def reset_user_mfa(user_id: int, db: DbSession, admin: AdminUser):
    return mfa_service.admin_reset(db, admin, user_id)
