from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import transaction
from app.models import AppSetting, User
from app.schemas.dashboard import AppSettingsUpdate
from app.services import audit_service

APPROVAL_THRESHOLD = "approval_threshold"
TAX_RATE = "tax_rate"

DEFAULTS = {
    APPROVAL_THRESHOLD: settings.DEFAULT_APPROVAL_THRESHOLD,
    TAX_RATE: settings.DEFAULT_TAX_RATE,
}


def get_decimal(db: Session, key: str) -> Decimal:
    value = db.scalar(select(AppSetting.value).where(AppSetting.key == key))
    return Decimal(value if value is not None else DEFAULTS[key])


def get_app_settings(db: Session) -> dict[str, Decimal]:
    return {
        "approval_threshold": get_decimal(db, APPROVAL_THRESHOLD),
        "tax_rate": get_decimal(db, TAX_RATE),
    }


def update_app_settings(db: Session, data: AppSettingsUpdate, user: User) -> dict[str, Decimal]:
    changes = data.model_dump(exclude_none=True)
    with transaction(db):
        before = get_app_settings(db)
        for key, value in changes.items():
            row = db.get(AppSetting, key)
            if row is None:
                db.add(AppSetting(key=key, value=str(value), updated_by_id=user.id))
            else:
                row.value = str(value)
                row.updated_by_id = user.id
        db.flush()
        diff = audit_service.diff(before, get_app_settings(db))
        if diff:
            audit_service.record(db, "settings.updated", actor=user, entity_type="settings", changes=diff)
    return get_app_settings(db)


def ensure_defaults(db: Session) -> None:
    with transaction(db):
        for key, value in DEFAULTS.items():
            if db.get(AppSetting, key) is None:
                db.add(AppSetting(key=key, value=value))
