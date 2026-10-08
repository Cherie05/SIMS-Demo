"""Dependency checks shared by the readiness probe and the admin System page."""

import logging
import time
from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import redis_client
from app.core.config import settings
from app.schemas.system import DependencyStatus

logger = logging.getLogger(__name__)

STARTED_AT = time.time()
ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"


def uptime_seconds() -> int:
    return int(time.time() - STARTED_AT)


@lru_cache
def migration_head() -> str | None:
    try:
        return ScriptDirectory(str(ALEMBIC_DIR)).get_current_head()
    except Exception:  # packaging problem: report, don't crash the probe
        logger.exception("Could not read the Alembic migration scripts")
        return None


def check_database(db: Session) -> DependencyStatus:
    try:
        db.execute(text("SELECT 1"))
        return DependencyStatus(status="ok")
    except SQLAlchemyError as exc:
        logger.error("Readiness: database check failed: %s", exc)
        return DependencyStatus(status="down", detail="database unreachable")


def check_redis() -> DependencyStatus:
    result = redis_client.ping()
    if result is None:
        return DependencyStatus(status="not_configured", detail="rate limits are per process")
    if result:
        return DependencyStatus(status="ok")
    # The app keeps working (limits fall back to process memory), so this is degraded, not down.
    return DependencyStatus(status="degraded", detail="redis unreachable; rate limits are per process")


def check_migrations(db: Session) -> DependencyStatus:
    head = migration_head()
    try:
        current = db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except SQLAlchemyError:
        db.rollback()
        return DependencyStatus(status="down" if settings.is_deployed else "unknown", detail="no alembic_version table")
    if head is None:
        return DependencyStatus(
            status="down" if settings.is_deployed else "unknown", detail="migration scripts unavailable"
        )
    if current != head:
        return DependencyStatus(status="down", detail=f"database at {current}, code expects {head}")
    return DependencyStatus(status="ok", detail=head)
