"""Rate limiting and brute-force protection.

State lives in Redis/Valkey when REDIS_URL is set, so limits hold across every API replica; without
it, in process memory (fine for a single instance). If Redis becomes unreachable the limiters fall
back to process memory instead of switching protection off (graceful degradation), and each
failure is counted in sims_dependency_errors_total{dependency="redis"}.

  login_limiter   failed sign-ins per account and per client IP (sliding window)
  signup_limiter  sign-ups per client IP
  reset_limiter   password-reset requests per account and per client IP
  api_limiter     all API requests per user and per client IP (fixed one-minute windows)
"""

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from math import ceil

import redis

from app.core import metrics
from app.core.config import settings
from app.core.exceptions import TooManyRequestsError
from app.core.redis_client import get_redis

logger = logging.getLogger(__name__)

PREFIX = "sims:rl"


class MemoryStore:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._counters: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, window: int, now: float) -> deque[float]:
        events = self._events[key]
        while events and events[0] <= now - window:
            events.popleft()
        return events

    def window_count(self, key: str, window: int) -> tuple[int, float | None]:
        now = time.time()
        with self._lock:
            events = self._recent(key, window, now)
            return len(events), (events[0] if events else None)

    def window_add(self, key: str, window: int) -> None:
        with self._lock:
            now = time.time()
            self._recent(key, window, now).append(now)

    def window_hit(self, key: str, window: int, limit: int) -> tuple[bool, float | None]:
        """Check the sliding budget and record an accepted event under one lock."""
        with self._lock:
            now = time.time()
            events = self._recent(key, window, now)
            oldest = events[0] if events else None
            if len(events) >= limit:
                return False, oldest
            events.append(now)
            return True, oldest

    def counter_incr(self, key: str, window: int) -> tuple[int, int]:
        now = time.time()
        bucket = int(now // window)
        full_key = f"{key}:{bucket}"
        with self._lock:
            count, _ = self._counters.get(full_key, (0, now))
            self._counters[full_key] = (count + 1, now)
            if len(self._counters) > 50_000:  # drop stale windows
                current = {k: v for k, v in self._counters.items() if k.endswith(f":{bucket}")}
                self._counters = current
        return count + 1, int((bucket + 1) * window - now) + 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self, prefix: str) -> None:
        with self._lock:
            for store in (self._events, self._counters):
                for key in [k for k in store if k.startswith(prefix)]:
                    store.pop(key, None)


class RedisStore:
    """Sliding windows as sorted sets of timestamps; fixed windows as INCR counters with a TTL."""

    def __init__(self, client: redis.Redis, fallback: MemoryStore):
        self.client = client
        self.fallback = fallback
        self._last_warning = 0.0

    def _degraded(self, exc: Exception) -> None:
        metrics.DEPENDENCY_ERRORS.labels("redis").inc()
        now = time.monotonic()
        if now - self._last_warning > 60:  # one warning a minute, not one per request
            self._last_warning = now
            logger.warning("Redis unavailable, rate limits fall back to process memory: %s", exc)

    def window_count(self, key: str, window: int) -> tuple[int, float | None]:
        now = time.time()
        try:
            pipe = self.client.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zcard(key)
            pipe.zrange(key, 0, 0, withscores=True)
            _, count, oldest = pipe.execute()
            return int(count), (oldest[0][1] if oldest else None)
        except redis.RedisError as exc:
            self._degraded(exc)
            return self.fallback.window_count(key, window)

    def window_add(self, key: str, window: int) -> None:
        now = time.time()
        try:
            pipe = self.client.pipeline()
            pipe.zadd(key, {f"{now}:{uuid.uuid4().hex[:8]}": now})
            pipe.expire(key, window + 1)
            pipe.execute()
        except redis.RedisError as exc:
            self._degraded(exc)
            self.fallback.window_add(key, window)

    def window_hit(self, key: str, window: int, limit: int) -> tuple[bool, float | None]:
        """Optimistic Redis transaction: parallel requests cannot all pass the same budget."""
        try:
            while True:
                with self.client.pipeline() as pipe:
                    try:
                        pipe.watch(key)
                        now = time.time()
                        cutoff = now - window
                        count = pipe.zcount(key, f"({cutoff}", "+inf")
                        first = pipe.zrangebyscore(key, f"({cutoff}", "+inf", start=0, num=1, withscores=True)
                        oldest = float(first[0][1]) if first else None
                        if count >= limit:
                            return False, oldest
                        pipe.multi()
                        pipe.zremrangebyscore(key, 0, cutoff)
                        pipe.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
                        pipe.expire(key, window + 1)
                        pipe.execute()
                        return True, oldest
                    except redis.WatchError:
                        # Another replica accepted an event; reevaluate its updated budget.
                        continue
        except redis.RedisError as exc:
            self._degraded(exc)
            return self.fallback.window_hit(key, window, limit)

    def counter_incr(self, key: str, window: int) -> tuple[int, int]:
        now = time.time()
        bucket = int(now // window)
        full_key = f"{key}:{bucket}"
        try:
            pipe = self.client.pipeline()
            pipe.incr(full_key)
            pipe.expire(full_key, window + 1)
            count, _ = pipe.execute()
            return int(count), int((bucket + 1) * window - now) + 1
        except redis.RedisError as exc:
            self._degraded(exc)
            return self.fallback.counter_incr(key, window)

    def delete(self, key: str) -> None:
        try:
            self.client.delete(key)
        except redis.RedisError as exc:
            self._degraded(exc)
        self.fallback.delete(key)

    def clear(self, prefix: str) -> None:
        try:
            keys = list(self.client.scan_iter(match=f"{prefix}*", count=500))
            if keys:
                self.client.delete(*keys)
        except redis.RedisError as exc:
            self._degraded(exc)
        self.fallback.clear(prefix)


def _make_store() -> MemoryStore | RedisStore:
    memory = MemoryStore()
    client = get_redis()
    return RedisStore(client, memory) if client is not None else memory


store = _make_store()


def _retry_after(oldest: float | None, window: int) -> int:
    if oldest is None:
        return window
    return max(1, ceil(oldest + window - time.time()))


class LoginRateLimiter:
    """Failed sign-ins per account (stops password guessing) and per client IP (stops spraying)."""

    name = "login"

    def __init__(self, max_per_email: int, max_per_ip: int, window_seconds: int):
        self.max_per_email = max_per_email
        self.max_per_ip = max_per_ip
        self.window = window_seconds

    def _keys(self, email: str, ip: str) -> list[tuple[str, int]]:
        return [
            (f"{PREFIX}:{self.name}:email:{email.lower()}", self.max_per_email),
            (f"{PREFIX}:{self.name}:ip:{ip}", self.max_per_ip),
        ]

    def check(self, email: str, ip: str) -> None:
        """Raise TooManyRequestsError if either the account or the client is over its limit."""
        for key, limit in self._keys(email, ip):
            count, oldest = store.window_count(key, self.window)
            if count >= limit:
                metrics.RATE_LIMITED.labels(self.name).inc()
                raise TooManyRequestsError(
                    "Too many failed sign-in attempts. Please wait before trying again.",
                    retry_after=_retry_after(oldest, self.window),
                )

    def is_locked(self, email: str) -> bool:
        count, _ = store.window_count(f"{PREFIX}:{self.name}:email:{email.lower()}", self.window)
        return count >= self.max_per_email

    def record_failure(self, email: str, ip: str) -> None:
        for key, _ in self._keys(email, ip):
            store.window_add(key, self.window)

    def reset(self, email: str) -> None:
        store.delete(f"{PREFIX}:{self.name}:email:{email.lower()}")

    def clear(self) -> None:
        store.clear(f"{PREFIX}:{self.name}:")


class SlidingWindowLimiter:
    """At most `limit` events per key within the window (e.g. sign-ups per client IP)."""

    def __init__(self, name: str, limit: int, window_seconds: int):
        self.name = name
        self.limit = limit
        self.window = window_seconds

    def hit(self, key: str, message: str) -> None:
        full_key = f"{PREFIX}:{self.name}:{key}"
        accepted, oldest = store.window_hit(full_key, self.window, self.limit)
        if not accepted:
            metrics.RATE_LIMITED.labels(self.name).inc()
            raise TooManyRequestsError(message, retry_after=_retry_after(oldest, self.window))

    def clear(self) -> None:
        store.clear(f"{PREFIX}:{self.name}:")


class FixedWindowLimiter:
    """Cheap per-minute request budget, checked on every API call."""

    def __init__(self, name: str, window_seconds: int = 60):
        self.name = name
        self.window = window_seconds

    def hit(self, key: str, limit: int) -> None:
        if limit <= 0:
            return
        count, reset_in = store.counter_incr(f"{PREFIX}:{self.name}:{key}", self.window)
        if count > limit:
            metrics.RATE_LIMITED.labels(self.name).inc()
            raise TooManyRequestsError(
                "Too many requests. Please slow down.", retry_after=reset_in, code="RATE_LIMITED"
            )

    def clear(self) -> None:
        store.clear(f"{PREFIX}:{self.name}:")


login_limiter = LoginRateLimiter(
    settings.LOGIN_MAX_FAILURES_PER_EMAIL,
    settings.LOGIN_MAX_FAILURES_PER_IP,
    settings.LOGIN_FAILURE_WINDOW_SECONDS,
)
signup_limiter = SlidingWindowLimiter("signup", settings.SIGNUP_MAX_PER_IP_PER_HOUR, 3600)
reset_limiter = SlidingWindowLimiter("password_reset", settings.PASSWORD_RESET_MAX_PER_HOUR, 3600)
api_limiter = FixedWindowLimiter("api")


def clear_all() -> None:
    """Forget every counter (tests and the ops runbook's 'unlock everyone' step)."""
    store.clear(f"{PREFIX}:")
