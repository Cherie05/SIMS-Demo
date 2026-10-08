"""ASGI middleware for every request: correlation id, access log, metrics, request guards and
security headers.

Pure ASGI (not BaseHTTPMiddleware) so streaming bodies aren't buffered and the context variables
set here are visible to the endpoint and to everything it calls.
"""

import logging
import re
import time
import uuid

from fastapi import HTTPException
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import context, metrics
from app.core.config import settings
from app.core.exceptions import error_body

access_logger = logging.getLogger("sims.access")
logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
# Accept a caller's id only if it is short and plain, so it can't be used to inject into logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_BODY_METHODS = {"POST", "PUT", "PATCH"}
# Probes and scrapes would drown the access log
_QUIET_PATHS = {"/health", "/health/live", "/health/ready", "/metrics"}


def _request_id(headers: Headers) -> str:
    supplied = headers.get(REQUEST_ID_HEADER)
    if supplied and _VALID_REQUEST_ID.match(supplied):
        return supplied
    return uuid.uuid4().hex


def _route_template(scope: Scope) -> str | None:
    """The matched route's full path template (/api/v1/orders/{order_id}), never the raw path."""
    # FastAPI keeps routers included with a prefix in an "effective route context" with the full path.
    effective = (scope.get("fastapi") or {}).get("effective_route_context")
    return getattr(effective, "path", None) or getattr(scope.get("route"), "path", None)


def _security_headers(path: str) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
    }
    if path.startswith(settings.API_V1_PREFIX):
        # JSON only: nothing may execute or be framed, and personal data must not be cached.
        headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        headers["Cache-Control"] = "no-store"
    if settings.cookie_secure:
        # Deployed behind HTTPS: browsers must never fall back to plain HTTP.
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        method = scope["method"]
        path = scope["path"]
        request_id = _request_id(headers)
        client = scope.get("client")
        ctx = context.RequestContext(
            request_id=request_id,
            client_ip=client[0] if client else None,
            user_agent=(headers.get("user-agent") or "")[:255] or None,
            method=method,
            path=path,
        )
        token = context.bind(ctx)
        started = time.perf_counter()
        status_holder = {"status": 500, "started": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                status_holder["started"] = True
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
                for name, value in _security_headers(path).items():
                    if name not in response_headers:
                        response_headers[name] = value
            await send(message)

        received = 0

        async def receive_wrapper() -> Message:
            # Bodies without Content-Length (chunked) are counted as they stream in.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > settings.MAX_REQUEST_BODY_BYTES:
                    raise HTTPException(status_code=413, detail="Request body too large")
            return message

        metrics.HTTP_IN_FLIGHT.inc()
        try:
            rejection = self._guard(method, path, headers)
            if rejection is not None:
                await rejection(scope, receive, send_wrapper)
            else:
                await self.app(scope, receive_wrapper, send_wrapper)
        except Exception:
            # Unhandled error: answer here, while the request context (id, user) is still bound, so the
            # 500 carries the request id and security headers like every other response.
            if status_holder["started"]:
                raise
            logger.exception("Unhandled error", extra={"event": "http.unhandled_error"})
            response = JSONResponse(error_body("INTERNAL_ERROR", "An unexpected error occurred"), status_code=500)
            await response(scope, receive, send_wrapper)
        finally:
            metrics.HTTP_IN_FLIGHT.dec()
            duration = time.perf_counter() - started
            status = status_holder["status"]
            route_template = _route_template(scope) or ("unmatched" if status == 404 else path)
            metrics.HTTP_REQUESTS.labels(method, route_template, f"{status // 100}xx", str(status)).inc()
            metrics.HTTP_LATENCY.labels(method, route_template).observe(duration)
            if path not in _QUIET_PATHS:
                access_logger.info(
                    "%s %s %s %.1fms",
                    method,
                    path,
                    status,
                    duration * 1000,
                    extra={
                        "event": "http.request",
                        "http_method": method,
                        "http_path": path,  # never the query string: it can carry search terms / PII
                        "http_route": route_template,
                        "http_status": status,
                        "duration_ms": round(duration * 1000, 1),
                        "user_agent": ctx.user_agent,
                    },
                )
            context.reset(token)

    @staticmethod
    def _guard(method: str, path: str, headers: Headers) -> JSONResponse | None:
        """Cheap checks before any parsing: body size and content type."""
        if method not in _BODY_METHODS or not path.startswith(settings.API_V1_PREFIX):
            return None
        length = headers.get("content-length")
        if length is not None:
            try:
                too_big = int(length) > settings.MAX_REQUEST_BODY_BYTES
            except ValueError:
                return JSONResponse(error_body("BAD_REQUEST", "Invalid Content-Length header"), status_code=400)
            if too_big:
                return JSONResponse(
                    error_body("PAYLOAD_TOO_LARGE", f"Request body exceeds {settings.MAX_REQUEST_BODY_BYTES} bytes"),
                    status_code=413,
                )
        has_body = (length is not None and length != "0") or "transfer-encoding" in headers
        content_type = headers.get("content-type", "")
        if has_body and content_type.split(";")[0].strip().lower() != "application/json":
            return JSONResponse(
                error_body("UNSUPPORTED_MEDIA_TYPE", "Request bodies must be application/json"), status_code=415
            )
        return None
