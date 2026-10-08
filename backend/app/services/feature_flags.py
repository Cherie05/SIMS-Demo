"""Runtime feature flags / kill switches, stored in app_settings and changed by admins (audited).

They let operators switch a capability off during an incident without a deploy, for example:
stop order intake while stock data is being corrected, or hold notification emails while the mail
provider is misbehaving (they stay queued and go out when switched back on).
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import transaction
from app.core.exceptions import FeatureDisabledError, NotFoundError
from app.models import AppSetting, User
from app.services import audit_service

PREFIX = "feature."


@dataclass(frozen=True)
class FlagDefinition:
    default: bool
    description: str


FLAGS: dict[str, FlagDefinition] = {
    "orders.create": FlagDefinition(True, "Sales staff can create new orders"),
    "auth.signup": FlagDefinition(True, "Self-service sign-up (also needs SIGNUP_ENABLED)"),
    "notifications.email": FlagDefinition(
        True, "Send workflow and security emails (while off, they wait in the queue; sign-in codes still go out)"
    ),
}


def _definition(name: str) -> FlagDefinition:
    if name not in FLAGS:
        raise NotFoundError(f"Unknown feature flag '{name}'", code="FLAG_NOT_FOUND")
    return FLAGS[name]


def is_enabled(db: Session, name: str) -> bool:
    definition = _definition(name)
    value = db.scalar(select(AppSetting.value).where(AppSetting.key == PREFIX + name))
    return definition.default if value is None else value == "true"


def all_flags(db: Session) -> list[dict]:
    stored = dict(db.execute(select(AppSetting.key, AppSetting.value).where(AppSetting.key.startswith(PREFIX))).all())
    return [
        {
            "name": name,
            "enabled": definition.default if PREFIX + name not in stored else stored[PREFIX + name] == "true",
            "default": definition.default,
            "description": definition.description,
        }
        for name, definition in FLAGS.items()
    ]


def set_flag(db: Session, name: str, enabled: bool, user: User) -> dict:
    _definition(name)
    with transaction(db):
        before = is_enabled(db, name)
        row = db.get(AppSetting, PREFIX + name)
        if row is None:
            db.add(AppSetting(key=PREFIX + name, value="true" if enabled else "false", updated_by_id=user.id))
        else:
            row.value = "true" if enabled else "false"
            row.updated_by_id = user.id
        if before != enabled:
            audit_service.record(
                db,
                "feature_flag.updated",
                actor=user,
                entity_type="feature_flag",
                entity_id=name,
                changes={"enabled": {"old": before, "new": enabled}},
            )
    return next(flag for flag in all_flags(db) if flag["name"] == name)


def require(db: Session, name: str, message: str) -> None:
    if not is_enabled(db, name):
        raise FeatureDisabledError(message)
