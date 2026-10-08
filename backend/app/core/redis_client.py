"""Shared Redis/Valkey client (rate limits across API replicas). Optional: without REDIS_URL the
app runs with per-process state, which is correct for a single instance."""

import logging

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _client
    if not settings.REDIS_URL:
        return None
    if _client is None:
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            password=settings.REDIS_PASSWORD or None,
            socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
            health_check_interval=30,
            decode_responses=True,
        )
    return _client


def ping() -> bool | None:
    """True/False when Redis is configured, None when it isn't used."""
    client = get_redis()
    if client is None:
        return None
    try:
        return bool(client.ping())
    except redis.RedisError as exc:
        logger.warning("Redis ping failed: %s", exc)
        return False
