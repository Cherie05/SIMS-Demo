import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.deps import DbSession
from app.api.v1.router import api_router
from app.core import health
from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import error_body, register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.services import audit_service

configure_logging("sims-api")
logger = logging.getLogger("sims")


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Starting %s %s in %s",
        settings.SERVICE_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
        extra={"event": "service.start"},
    )
    if settings.is_deployed and settings.OTP_DELIVERY == "log":
        logger.warning(
            "OTP_DELIVERY=log: one-time sign-in codes are written to the server log. "
            "Set OTP_DELIVERY=email for real users."
        )
    if settings.is_deployed and not settings.REDIS_URL:
        logger.warning("REDIS_URL is not set: rate limits are per process, so they don't hold across replicas.")
    yield
    # uvicorn has stopped accepting connections and drained in-flight requests (SIGTERM).
    logger.info("Shutting down: closing database connections", extra={"event": "service.stop"})
    engine.dispose()


def create_app() -> FastAPI:
    docs = settings.api_docs_enabled
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Products, customers, sales orders, inventory and a manager approval workflow.",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        lifespan=lifespan,
        # No automatic /path/ -> /path redirects: they would build absolute URLs from the Host header.
        redirect_slashes=False,
    )
    # Bearer tokens, not cookies, for the API, so credentialed CORS is not needed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Idempotency-Key", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Idempotent-Replayed", "Retry-After"],
        max_age=600,
    )
    # Outermost: every response (errors included) gets a request id, security headers and metrics.
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app, on_denied=audit_service.record_denied)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health/live", tags=["Health"], summary="Liveness: the process is running")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"], summary="Readiness: dependencies are reachable")
    def ready(db: DbSession):
        checks = {
            "database": health.check_database(db),
            "redis": health.check_redis(),
            "migrations": health.check_migrations(db),
        }
        down = [name for name, check in checks.items() if check.status == "down"]
        body = {
            "status": "unavailable" if down else "ok",
            "version": settings.APP_VERSION,
            "checks": {name: check.model_dump(exclude_none=True) for name, check in checks.items()},
        }
        return JSONResponse(body, status_code=503 if down else 200)

    @app.get("/health", tags=["Health"], summary="Readiness (short form, for load balancers)")
    def health_short(db: DbSession):
        if health.check_database(db).status != "ok" or health.check_migrations(db).status == "down":
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ok"}

    if settings.METRICS_ENABLED:

        @app.get("/metrics", include_in_schema=False)
        def metrics_endpoint(request: Request):
            # Served on the internal port only (the web proxy routes /api/* alone); a token adds a second lock.
            if settings.METRICS_TOKEN:
                supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                if not hmac.compare_digest(supplied, settings.METRICS_TOKEN):
                    return JSONResponse(error_body("NOT_AUTHENTICATED", "Metrics token required"), status_code=401)
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
