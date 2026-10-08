"""Prometheus metrics (scraped from /metrics on the API and from the worker's metrics port).

Labels use route templates (/orders/{order_id}), never raw paths, so cardinality stays bounded.
"""

from prometheus_client import Counter, Gauge, Histogram, Info

from app.core.config import settings

BUILD_INFO = Info("sims_build", "Build and runtime information")
BUILD_INFO.info({"version": settings.APP_VERSION, "environment": settings.ENVIRONMENT})

HTTP_REQUESTS = Counter(
    "sims_http_requests_total", "HTTP requests handled", ["method", "route", "status_class", "status"]
)
HTTP_LATENCY = Histogram(
    "sims_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 2, 5, 10),
)
HTTP_IN_FLIGHT = Gauge("sims_http_requests_in_flight", "HTTP requests currently being handled")

# Business and security events
ORDERS_CREATED = Counter("sims_orders_created_total", "Sales orders created", ["outcome"])
APPROVAL_DECISIONS = Counter("sims_approval_decisions_total", "Approval decisions", ["decision"])
AUTH_EVENTS = Counter("sims_auth_events_total", "Authentication events", ["event", "outcome"])
RATE_LIMITED = Counter("sims_rate_limited_total", "Requests refused by a rate limit", ["limiter"])
IDEMPOTENT_REPLAYS = Counter("sims_idempotent_replays_total", "Requests answered from an idempotency key")
DEPENDENCY_ERRORS = Counter("sims_dependency_errors_total", "Failures talking to a dependency", ["dependency"])

# Background jobs (worker process)
JOBS_PROCESSED = Counter("sims_jobs_processed_total", "Background jobs processed", ["job_type", "outcome"])
JOB_DURATION = Histogram(
    "sims_job_duration_seconds", "Background job run time", ["job_type"], buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30)
)
JOBS_BACKLOG = Gauge("sims_jobs_backlog", "Background jobs by state", ["state"])
EMAILS = Counter("sims_emails_total", "Emails by outcome", ["template", "status"])
WORKER_HEARTBEAT = Gauge("sims_worker_last_heartbeat_timestamp_seconds", "Unix time of the last worker loop")

# Browser telemetry (real-user monitoring)
WEB_VITALS = Histogram(
    "sims_web_vitals",
    "Core Web Vitals reported by browsers (milliseconds; CLS is unitless x1000)",
    ["name"],
    buckets=(50, 100, 200, 500, 1000, 1800, 2500, 4000, 6000, 10000),
)
CLIENT_ERRORS = Counter("sims_client_errors_total", "JavaScript errors reported by browsers", ["kind"])
