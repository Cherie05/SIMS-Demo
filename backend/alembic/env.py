from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.database import connect_args, database_url
from app.models import Base

config = context.config

# Keep the application's loggers working when migrations run in-process (tests, tools).
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url():
    # Tests and tools can point a run at another database: config.attributes["database_url"].
    return config.attributes.get("database_url") or database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=str(_url()),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Same password source and TLS settings as the application (DATABASE_PASSWORD, DATABASE_TLS).
    connectable = create_engine(_url(), poolclass=pool.NullPool, connect_args=connect_args())
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
