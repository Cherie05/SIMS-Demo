from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import InputModel, OutputModel, UtcDateTime


class AuditLogOut(OutputModel):
    id: int
    occurred_at: UtcDateTime
    actor_id: int | None
    actor_email: str | None
    actor_role: str | None
    action: str
    outcome: str
    entity_type: str | None
    entity_id: str | None
    changes: dict[str, Any] | None
    details: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    request_id: str | None


class JobOut(OutputModel):
    id: int
    job_type: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    available_at: UtcDateTime
    created_at: UtcDateTime
    completed_at: UtcDateTime | None
    expires_at: UtcDateTime | None
    last_error: str | None
    request_id: str | None
    # Only identifiers (order, recipient, kind) - never codes or other secrets from the payload
    reference: dict[str, Any] = Field(default_factory=dict)


class WorkerOut(OutputModel):
    worker_id: str
    hostname: str
    version: str
    started_at: UtcDateTime
    last_seen_at: UtcDateTime
    jobs_processed: int
    alive: bool = False


class ScheduledTaskOut(OutputModel):
    name: str
    last_started_at: UtcDateTime | None
    last_finished_at: UtcDateTime | None
    last_status: str | None
    last_error: str | None
    last_result: dict[str, Any] | None
    run_count: int


class DependencyStatus(BaseModel):
    status: Literal["ok", "degraded", "down", "not_configured", "unknown"]
    detail: str | None = None


class SystemStatusOut(BaseModel):
    version: str
    environment: str
    uptime_seconds: int
    database: DependencyStatus
    redis: DependencyStatus
    migrations: DependencyStatus
    workers: list[WorkerOut]
    jobs: dict[str, int]
    oldest_due_job_age_seconds: int
    scheduled_tasks: list[ScheduledTaskOut]


class FeatureFlagOut(BaseModel):
    name: str
    enabled: bool
    default: bool
    description: str


class FeatureFlagUpdate(InputModel):
    enabled: bool


class ClientErrorIn(InputModel):
    kind: Literal["error", "unhandledrejection", "boundary"]
    message: str = Field(max_length=500)
    stack: str | None = Field(default=None, max_length=4000)
    component_stack: str | None = Field(default=None, max_length=2000)
    path: str = Field(max_length=300, description="Page path (no query string)")
    release: str | None = Field(default=None, max_length=40)


class WebVitalIn(InputModel):
    name: Literal["LCP", "INP", "CLS", "FCP", "TTFB"]
    value: float = Field(ge=0, le=600_000)
    rating: Literal["good", "needs-improvement", "poor"] | None = None
    path: str = Field(max_length=300)
