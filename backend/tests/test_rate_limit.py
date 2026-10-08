"""Rate limits: shared through Redis/Valkey across replicas, degrading to process memory if Redis fails."""

import threading
from concurrent.futures import ThreadPoolExecutor

import fakeredis
import pytest
import redis

from app.core import metrics, rate_limit
from app.core.config import settings
from app.core.rate_limit import MemoryStore, RedisStore


@pytest.fixture
def redis_store():
    return RedisStore(fakeredis.FakeRedis(decode_responses=True), MemoryStore())


def test_sliding_windows_are_kept_in_redis(redis_store):
    for _ in range(3):
        redis_store.window_add("sims:rl:test:a", 60)
    count, oldest = redis_store.window_count("sims:rl:test:a", 60)
    assert count == 3 and oldest is not None
    assert redis_store.client.zcard("sims:rl:test:a") == 3  # shared state, visible to every replica
    redis_store.clear("sims:rl:test:")
    assert redis_store.window_count("sims:rl:test:a", 60)[0] == 0


def test_fixed_window_counters_in_redis(redis_store):
    counts = [redis_store.counter_incr("sims:rl:api:user:1", 60)[0] for _ in range(3)]
    assert counts == [1, 2, 3]
    assert 0 < redis_store.counter_incr("sims:rl:api:user:1", 60)[1] <= 61


class _BrokenRedis:
    def __getattr__(self, _name):
        def fail(*_args, **_kwargs):
            raise redis.ConnectionError("connection refused")

        return fail


def test_limits_keep_working_from_memory_when_redis_is_down():
    store = RedisStore(_BrokenRedis(), MemoryStore())
    before = metrics.DEPENDENCY_ERRORS.labels("redis")._value.get()
    store.window_add("sims:rl:test:b", 60)
    store.window_add("sims:rl:test:b", 60)
    assert store.window_count("sims:rl:test:b", 60)[0] == 2
    assert store.counter_incr("sims:rl:api:x", 60)[0] == 1
    assert metrics.DEPENDENCY_ERRORS.labels("redis")._value.get() > before
    assert store.window_hit("sims:rl:test:c", 60, 1)[0]
    assert not store.window_hit("sims:rl:test:c", 60, 1)[0]


@pytest.mark.parametrize("backend", ["memory", "redis"])
def test_parallel_sliding_window_requests_share_an_atomic_budget(backend, redis_store):
    store = MemoryStore() if backend == "memory" else redis_store
    barrier = threading.Barrier(12)

    def hit(_index):
        barrier.wait()
        return store.window_hit("sims:rl:test:parallel", 60, 3)[0]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(hit, range(12)))
    assert results.count(True) == 3
    assert store.window_count("sims:rl:test:parallel", 60)[0] == 3


def test_api_requests_are_limited_per_user(client, auth, monkeypatch):
    headers = auth("sales")
    rate_limit.api_limiter.clear()
    monkeypatch.setattr(settings, "API_RATE_LIMIT_PER_USER_PER_MINUTE", 3)
    statuses = [client.get("/api/v1/products", headers=headers).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]
    refused = client.get("/api/v1/products", headers=headers)
    assert refused.json()["error"]["code"] == "RATE_LIMITED" and int(refused.headers["Retry-After"]) > 0


def test_api_requests_are_limited_per_client_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "API_RATE_LIMIT_PER_IP_PER_MINUTE", 2)
    statuses = [client.get("/api/v1/auth/config").status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


def test_password_reset_requests_are_limited(client, users, monkeypatch):
    monkeypatch.setattr(rate_limit.reset_limiter, "limit", 2)
    statuses = [
        client.post("/api/v1/auth/password/forgot", json={"email": "sales@example.com"}).status_code for _ in range(3)
    ]
    assert statuses == [202, 202, 429]


def test_browser_telemetry_is_accepted_validated_and_limited(client, monkeypatch):
    error = {"kind": "error", "message": "TypeError: x is undefined", "path": "/orders/new?draft=1", "stack": "at f"}
    assert client.post("/api/v1/telemetry/client-errors", json=error).status_code == 204
    assert client.post("/api/v1/telemetry/client-errors", json={**error, "kind": "other"}).status_code == 422
    assert client.post("/api/v1/telemetry/client-errors", json={**error, "user": "x"}).status_code == 422  # extra field
    vital = {"name": "LCP", "value": 1234.5, "rating": "good", "path": "/"}
    assert client.post("/api/v1/telemetry/web-vitals", json=vital).status_code == 204
    assert 'sims_web_vitals_count{name="LCP"}' in client.get("/metrics").text

    from app.api.v1.routes import telemetry

    monkeypatch.setattr(telemetry.telemetry_limiter, "limit", 1)
    telemetry.telemetry_limiter.clear()
    dropped = metrics.RATE_LIMITED.labels("telemetry")._value.get()
    observed = metrics.WEB_VITALS.labels("LCP")._sum.get()
    assert client.post("/api/v1/telemetry/web-vitals", json=vital).status_code == 204
    # over budget: silently dropped (no error for the browser), but counted
    assert client.post("/api/v1/telemetry/web-vitals", json=vital).status_code == 204
    assert metrics.RATE_LIMITED.labels("telemetry")._value.get() == dropped + 1
    assert metrics.WEB_VITALS.labels("LCP")._sum.get() == observed + 1234.5
