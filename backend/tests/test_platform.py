"""Platform behaviour shared by every endpoint: correlation ids, security headers, request guards,
health probes, Prometheus metrics and structured, redacted logging."""

import json
import logging

from app.core import context, health
from app.core.config import settings
from app.core.logging import ContextFilter, JsonFormatter, redact
from app.schemas.system import DependencyStatus


def test_every_response_carries_a_request_id(client):
    response = client.get("/health/live")
    assert len(response.headers["X-Request-ID"]) == 32


def test_a_callers_request_id_is_kept_when_well_formed(client):
    kept = client.get("/health/live", headers={"X-Request-ID": "lb-7f3a9c1e-0001"})
    assert kept.headers["X-Request-ID"] == "lb-7f3a9c1e-0001"
    # anything that could inject into log lines is replaced
    replaced = client.get("/health/live", headers={"X-Request-ID": "x<script>alert(1)</script>"})
    assert replaced.headers["X-Request-ID"] != "x<script>alert(1)</script>"


def test_error_bodies_quote_the_request_id(client):
    response = client.get("/api/v1/products")
    assert response.status_code == 401
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


def test_api_responses_have_security_headers(client):
    headers = client.get("/api/v1/auth/config").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"
    assert headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "Strict-Transport-Security" not in headers  # plain-HTTP development


def test_hsts_is_sent_when_deployed_behind_https(client, monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    assert client.get("/health/live").headers["Strict-Transport-Security"].startswith("max-age=31536000")


def test_oversized_request_bodies_are_refused(client, auth, monkeypatch):
    headers = auth("sales")
    monkeypatch.setattr(settings, "MAX_REQUEST_BODY_BYTES", 200)
    response = client.post("/api/v1/customers", json={"name": "x" * 300, "email": "big@example.com"}, headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_only_json_bodies_are_accepted(client, auth):
    response = client.post(
        "/api/v1/customers",
        content="name=Evil&email=evil@example.com",
        headers={**auth("sales"), "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_liveness_and_readiness_probes(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ok" and body["version"] == settings.APP_VERSION
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["redis"]["status"] == "not_configured"


def test_readiness_fails_when_the_database_is_down(client, monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda _db: DependencyStatus(status="down", detail="x"))
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health").status_code == 503


def test_readiness_fails_when_migrations_are_behind(client, monkeypatch):
    monkeypatch.setattr(health, "check_migrations", lambda _db: DependencyStatus(status="down", detail="behind"))
    assert client.get("/health/ready").status_code == 503


def test_prometheus_metrics_use_route_templates(client, auth, customer):
    client.get(f"/api/v1/customers/{customer.id}", headers=auth("sales"))
    text = client.get("/metrics").text
    assert 'route="/api/v1/customers/{customer_id}"' in text
    assert f'route="/api/v1/customers/{customer.id}"' not in text  # raw ids would explode cardinality
    assert "sims_http_request_duration_seconds_bucket" in text
    assert 'sims_auth_events_total{event="login",outcome="success"}' in text


def test_metrics_can_require_a_token(client, monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", "scrape-secret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"}).status_code == 200


def test_secrets_are_redacted_from_log_text():
    assert redact("Authorization: Bearer abc.def-ghi") == "Authorization: Bearer [REDACTED]"
    assert "hunter2" not in redact('login failed {"password": "hunter2"}')
    assert "hunter2" not in redact("password=hunter2&next=/")
    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ"
    assert redact(f"token {jwt_like}") == "token [REDACTED_JWT]"


def test_json_logs_carry_request_context_and_redact_extras():
    record = logging.makeLogRecord(
        {"name": "sims.test", "levelname": "INFO", "msg": "user %s did a thing", "args": (7,)}
    )
    record.__dict__.update({"password": "hunter2", "order_id": 42})
    token = context.bind(context.RequestContext(request_id="req-123456789", client_ip="10.0.0.9", user_id=7))
    try:
        ContextFilter().filter(record)
    finally:
        context.reset(token)
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "user 7 did a thing"
    assert (entry["request_id"], entry["user_id"], entry["client_ip"]) == ("req-123456789", 7, "10.0.0.9")
    assert entry["password"] == "[REDACTED]" and entry["order_id"] == 42
    assert entry["service"] and entry["environment"] and entry["timestamp"].endswith("+00:00")


def test_access_log_never_records_query_strings(client, auth, caplog):
    headers = auth("sales")
    with caplog.at_level(logging.INFO, logger="sims.access"):
        client.get("/api/v1/customers?search=very-private-search", headers=headers)
    lines = [r.getMessage() for r in caplog.records if r.name == "sims.access"]
    assert any("/api/v1/customers" in line for line in lines)
    assert not any("very-private-search" in line for line in lines)
