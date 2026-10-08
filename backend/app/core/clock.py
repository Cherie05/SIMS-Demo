from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC 'now', matching how timestamps are stored. Tests replace this to move time forward."""
    return datetime.now(UTC).replace(tzinfo=None)
