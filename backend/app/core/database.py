from collections.abc import Generator, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def database_url() -> URL:
    url = make_url(settings.DATABASE_URL)
    if settings.DATABASE_PASSWORD:
        url = url.set(password=settings.DATABASE_PASSWORD)
    return url


def _tls_args() -> dict[str, Any]:
    """PyMySQL TLS options for DATABASE_TLS (PyMySQL already encrypts opportunistically by default)."""
    mode = settings.DATABASE_TLS
    if mode == "disabled":
        return {"ssl_disabled": True}
    if mode == "required":
        return {"ssl": {"check_hostname": False}}  # encrypted, server certificate not verified
    if mode in ("verify_ca", "verify_identity"):
        if not settings.DATABASE_TLS_CA:
            raise RuntimeError(f"DATABASE_TLS={mode} needs DATABASE_TLS_CA (path to the CA certificate)")
        return {
            "ssl_ca": settings.DATABASE_TLS_CA,
            "ssl_verify_cert": True,
            "ssl_verify_identity": mode == "verify_identity",
        }
    return {}


def connect_args() -> dict[str, Any]:
    return {
        "connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
        "read_timeout": settings.DB_READ_TIMEOUT_SECONDS,
        "write_timeout": settings.DB_WRITE_TIMEOUT_SECONDS,
        **_tls_args(),
    }


# READ COMMITTED keeps plain reads fresh inside long requests; stock-changing code paths
# additionally take row locks (SELECT ... FOR UPDATE) so concurrent orders cannot oversell.
engine = create_engine(
    database_url(),
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    isolation_level="READ COMMITTED",
    connect_args=connect_args(),
)


@event.listens_for(engine, "connect")
def _configure_session(dbapi_connection, _record) -> None:
    """UTC timestamps everywhere, plus server-side limits so one bad query can't hold the database."""
    with dbapi_connection.cursor() as cursor:
        cursor.execute("SET time_zone = '+00:00'")
        # DATETIME columns have whole seconds: truncate fractions like Python comparisons expect. (MySQL's
        # default is to round, which can store a "due now" job half a second in the future.)
        cursor.execute("SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',TIME_TRUNCATE_FRACTIONAL')")
        cursor.execute("SET SESSION max_execution_time = %s", (int(settings.DB_STATEMENT_TIMEOUT_MS),))
        cursor.execute("SET SESSION innodb_lock_wait_timeout = %s", (int(settings.DB_LOCK_WAIT_TIMEOUT_SECONDS),))


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction(db: Session) -> Iterator[Session]:
    """Unit of work: commit when the block succeeds, roll back on any error."""
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


@contextmanager
def named_lock(name: str, timeout_seconds: int = 0) -> Iterator[bool]:
    """Cluster-wide mutex using MySQL GET_LOCK: yields True if this process holds the lock.

    Used so a scheduled job runs on one worker at a time, however many replicas are running.
    The lock lives on a dedicated connection and is released when the block ends (or the
    connection dies), so a crashed worker never leaves it held.
    """
    with engine.connect() as connection:
        acquired = bool(
            connection.scalar(text("SELECT GET_LOCK(:name, :timeout)"), {"name": name, "timeout": timeout_seconds})
        )
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
