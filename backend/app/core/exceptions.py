"""Domain exceptions and the handlers that turn them into a consistent JSON error shape:

{"error": {"code": "INSUFFICIENT_STOCK", "message": "...", "details": [...], "request_id": "..."}}

The request id is also in the X-Request-ID header; support can find every log line of the
request with it.
"""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import context

logger = logging.getLogger(__name__)
security_logger = logging.getLogger("sims.security")


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details


class BusinessRuleError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BUSINESS_RULE_VIOLATION"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "NOT_AUTHENTICATED"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "PERMISSION_DENIED"


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class InsufficientStockError(ConflictError):
    code = "INSUFFICIENT_STOCK"


class UnprocessableError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "UNPROCESSABLE"


class TooManyRequestsError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "TOO_MANY_ATTEMPTS"

    def __init__(self, message: str, *, retry_after: int, code: str | None = None):
        super().__init__(message, code=code, details={"retry_after_seconds": retry_after})
        self.retry_after = retry_after


class FeatureDisabledError(AppError):
    """A kill switch is off (see feature flags): temporary, so clients may retry later."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "FEATURE_DISABLED"


def error_body(code: str, message: str, details: Any = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details),
            "request_id": context.current().request_id,
        }
    }


def register_exception_handlers(app: FastAPI, on_denied: Callable[[str, str], None] | None = None) -> None:
    """on_denied(code, message) is called for every 403, e.g. to write the audit trail."""

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError):
        headers = None
        if exc.status_code == 401:
            headers = {"WWW-Authenticate": "Bearer"}
        elif isinstance(exc, TooManyRequestsError):
            headers = {"Retry-After": str(exc.retry_after)}
        elif isinstance(exc, FeatureDisabledError):
            headers = {"Retry-After": "300"}
        if exc.status_code == 403:
            security_logger.warning(
                "Access denied: %s", exc.message, extra={"event": "access.denied", "error_code": exc.code}
            )
            if on_denied is not None:
                try:
                    on_denied(exc.code, exc.message)
                except Exception:  # auditing must never turn a 403 into a 500
                    logger.exception("Could not record access denial")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        details = [
            {
                "field": ".".join(str(part) for part in err["loc"] if part != "body"),
                "message": err["msg"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_body("VALIDATION_ERROR", "Request validation failed", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(f"HTTP_{exc.status_code}", str(exc.detail)),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(_: Request, exc: IntegrityError):
        logger.warning("Integrity error: %s", exc.orig)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_body("INTEGRITY_ERROR", "The request conflicts with existing data"),
        )

    @app.exception_handler(OperationalError)
    async def database_unavailable_handler(_: Request, exc: OperationalError):
        # Database unreachable, lock wait timeout, statement timeout or deadlock: transient, so tell
        # clients to retry (503 also lets a load balancer take the instance out of rotation).
        logger.error("Database operation failed: %s", exc.orig, extra={"event": "dependency.error"})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_body("SERVICE_UNAVAILABLE", "The service is temporarily unavailable, please try again"),
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception):
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("INTERNAL_ERROR", "An unexpected error occurred"),
        )
