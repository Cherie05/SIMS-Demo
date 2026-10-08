"""Schema migrations: every release must upgrade from scratch, roll back cleanly, and match the models.

Uses a scratch database (sims_migrations by default), so the test schema is untouched.
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.models import Base
from tests.database_safety import validate_test_database_url

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migration_url():
    url = make_url(os.environ["DATABASE_URL"]).set(database=os.getenv("MIGRATION_TEST_DATABASE", "sims_migrations"))
    validate_test_database_url(url, migrations=True)
    engine = create_engine(url)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        pytest.skip(f"scratch database {url.database} is not available: {exc.orig}")
    finally:
        engine.dispose()
    return url


def _alembic(url) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


def test_migrations_upgrade_roll_back_and_match_the_models(migration_url):
    config = _alembic(migration_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()
