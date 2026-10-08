"""Fail closed before tests create, truncate, drop, or downgrade a database."""

import re

from sqlalchemy.engine import URL, make_url


def validate_test_database_url(value: str | URL, *, migrations: bool = False) -> URL:
    url = make_url(value)
    prefix = "sims_migrations" if migrations else "sims_test"
    if url.get_backend_name() != "mysql" or not re.fullmatch(rf"{prefix}(?:_[A-Za-z0-9_]+)?", url.database or ""):
        raise RuntimeError(
            f"Refusing destructive tests: database must be {prefix!r} or start with {prefix + '_'!r}, using MySQL."
        )
    return url
