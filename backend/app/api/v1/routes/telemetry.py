"""Real-user monitoring: browsers report JavaScript errors and Core Web Vitals here.

Open to anonymous visitors (errors happen on the sign-in page too), so each client IP gets a small
budget, payloads are size-limited and strictly typed, and nothing is stored in the database: errors
become structured log lines (picked up by the log pipeline) and vitals become Prometheus histograms.
Reports over the budget are dropped silently (still 204): telemetry is fire-and-forget, and an error
response would only add noise to the browser console of users behind a shared office IP.
"""

import logging

from fastapi import APIRouter, Request, Response, status

from app.core import metrics
from app.core.exceptions import TooManyRequestsError
from app.core.rate_limit import SlidingWindowLimiter
from app.schemas.system import ClientErrorIn, WebVitalIn

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])
logger = logging.getLogger("sims.client")

telemetry_limiter = SlidingWindowLimiter("telemetry", 60, 60)
TOO_MANY = "Too many telemetry reports"


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _within_budget(request: Request) -> bool:
    try:
        telemetry_limiter.hit(f"ip:{_ip(request)}", TOO_MANY)
        return True
    except TooManyRequestsError:
        return False  # counted in sims_rate_limited_total{limiter="telemetry"}


def _path_only(path: str) -> str:
    return path.split("?", 1)[0].split("#", 1)[0]


@router.post("/client-errors", status_code=status.HTTP_204_NO_CONTENT, summary="Report a browser error")
def client_error(data: ClientErrorIn, request: Request):
    if not _within_budget(request):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    metrics.CLIENT_ERRORS.labels(data.kind).inc()
    logger.warning(
        "Browser %s on %s: %s",
        data.kind,
        _path_only(data.path),
        data.message,
        extra={
            "event": "client.error",
            "client_error_kind": data.kind,
            "page_path": _path_only(data.path),
            "stack": data.stack,
            "component_stack": data.component_stack,
            "release": data.release,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/web-vitals", status_code=status.HTTP_204_NO_CONTENT, summary="Report a Core Web Vitals measurement")
def web_vital(data: WebVitalIn, request: Request):
    if not _within_budget(request):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # CLS is unitless (typically 0-1): scale it so the shared millisecond buckets still apply.
    metrics.WEB_VITALS.labels(data.name).observe(data.value * 1000 if data.name == "CLS" else data.value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
