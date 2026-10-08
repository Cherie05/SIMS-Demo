from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_JWT_SECRETS = {"change-me-in-production", "docker-dev-secret-change-me", "replace-with-a-long-random-string"}
# Docker/Kubernetes secrets: a file named after the setting (e.g. /run/secrets/JWT_SECRET_KEY) wins over defaults.
SECRETS_DIR = "/run/secrets"


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables, .env and /run/secrets."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        secrets_dir=SECRETS_DIR if Path(SECRETS_DIR).is_dir() else None,
    )

    APP_NAME: str = "Sales & Inventory Management System"
    APP_VERSION: str = "1.1.0"
    SERVICE_NAME: str = "sims-api"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: Literal["development", "test", "staging", "production"] = "development"
    # Swagger/ReDoc. Defaults to on, except in staging/production.
    ENABLE_API_DOCS: bool | None = None

    # ------------------------------------------------------------------ logging & observability
    LOG_LEVEL: str = "INFO"
    # json: one JSON object per line (log shippers, Loki/ELK); text: human-readable, for local development
    LOG_FORMAT: Literal["json", "text"] | None = None
    # Prometheus metrics at /metrics (internal port only; not routed by the web proxy).
    METRICS_ENABLED: bool = True
    # Optional bearer token required to scrape /metrics.
    METRICS_TOKEN: str | None = None

    # ------------------------------------------------------------------ database
    DATABASE_URL: str = "mysql+pymysql://sims:sims_password@127.0.0.1:3306/sims"
    # Overrides the password inside DATABASE_URL (lets the password come from a secret file).
    DATABASE_PASSWORD: str | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_CONNECT_TIMEOUT_SECONDS: int = 5
    DB_READ_TIMEOUT_SECONDS: int = 30
    DB_WRITE_TIMEOUT_SECONDS: int = 30
    # Server-side limits per session: SELECTs running longer are aborted; row-lock waits fail fast.
    DB_STATEMENT_TIMEOUT_MS: int = 15000
    DB_LOCK_WAIT_TIMEOUT_SECONDS: int = 10
    # TLS to MySQL. preferred: encrypt when the server offers it; required: refuse plain connections;
    # verify_ca / verify_identity: also check the server certificate against DATABASE_TLS_CA.
    DATABASE_TLS: Literal["disabled", "preferred", "required", "verify_ca", "verify_identity"] = "preferred"
    DATABASE_TLS_CA: str | None = None

    # ------------------------------------------------------------------ Redis / Valkey
    # Shared state for rate limiting across API replicas. Empty: per-process memory (single instance only).
    REDIS_URL: str | None = None
    REDIS_PASSWORD: str | None = None
    REDIS_TIMEOUT_SECONDS: float = 0.5

    # ------------------------------------------------------------------ tokens & sessions
    JWT_SECRET_KEY: str = "change-me-in-production"
    # Previous signing keys, comma separated: tokens they signed stay valid until they expire (key rotation).
    JWT_PREVIOUS_SECRET_KEYS: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "sims"
    JWT_AUDIENCE: str = "sims-web"
    # Short-lived access token (kept in memory by the web app) + rotating refresh token (httpOnly cookie)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(15, gt=0)
    # A session ends after this long without activity...
    SESSION_IDLE_TIMEOUT_MINUTES: int = Field(60, gt=0)
    # ...and in any case this long after the user signed in.
    SESSION_ABSOLUTE_TIMEOUT_HOURS: int = Field(12, gt=0)
    REFRESH_COOKIE_NAME: str = "sims_refresh"
    # Secure cookies require HTTPS; defaults to on in staging/production.
    COOKIE_SECURE: bool | None = None
    # Encrypts secrets stored in the database (authenticator-app keys). Fernet keys, comma separated,
    # newest first. Empty: derived from JWT_SECRET_KEY (development only).
    DATA_ENCRYPTION_KEYS: str = ""

    # ------------------------------------------------------------------ passwords
    # Argon2id cost (OWASP minimum: 19 MiB memory, 2 iterations, 1 lane). bcrypt hashes from older
    # versions are still accepted and upgraded to Argon2id at the next sign-in.
    PASSWORD_HASH_MEMORY_KIB: int = 19456
    PASSWORD_HASH_ITERATIONS: int = 2
    PASSWORD_HASH_PARALLELISM: int = 1

    # ------------------------------------------------------------------ one-time codes
    # Email verification at sign-up, password reset, and the second step of every sign-in.
    LOGIN_OTP_REQUIRED: bool = True
    # "log": the code is written to the server log (terminal / docker compose logs backend).
    # "email": the code is emailed through the SMTP settings below.
    OTP_DELIVERY: Literal["log", "email"] = "log"
    OTP_TTL_SECONDS: int = Field(300, gt=0)
    OTP_MAX_ATTEMPTS: int = Field(5, gt=0)
    OTP_RESEND_COOLDOWN_SECONDS: int = Field(30, gt=0)
    OTP_MAX_SENDS: int = Field(5, gt=0)

    # ------------------------------------------------------------------ sign-up
    # Self-service sign-up. New accounts always get the Sales role.
    SIGNUP_ENABLED: bool = True
    # Comma separated, e.g. "company.com,company.in". Empty allows any domain.
    SIGNUP_ALLOWED_DOMAINS: str = ""
    SIGNUP_MAX_PER_IP_PER_HOUR: int = 10

    # ------------------------------------------------------------------ abuse protection
    # Brute-force protection for sign-in: failed attempts allowed per window
    LOGIN_MAX_FAILURES_PER_EMAIL: int = Field(5, gt=0)
    LOGIN_MAX_FAILURES_PER_IP: int = Field(20, gt=0)
    LOGIN_FAILURE_WINDOW_SECONDS: int = Field(600, gt=0)
    PASSWORD_RESET_MAX_PER_HOUR: int = 5
    # General API limits per minute (0 disables)
    API_RATE_LIMIT_PER_USER_PER_MINUTE: int = 600
    API_RATE_LIMIT_PER_IP_PER_MINUTE: int = 1200
    # Largest accepted request body
    MAX_REQUEST_BODY_BYTES: int = 1_048_576

    # ------------------------------------------------------------------ web
    # Comma separated list of allowed CORS origins
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    # Used to build links inside emails
    FRONTEND_URL: str = "http://localhost:5173"

    # ------------------------------------------------------------------ email (SMTP)
    # In development, Mailpit catches every message at http://localhost:8025. 127.0.0.1 rather than
    # localhost: Windows tries ::1 first and waits ~2 s when Mailpit listens on IPv4 only.
    EMAIL_ENABLED: bool = True
    SMTP_HOST: str = "127.0.0.1"
    SMTP_PORT: int = 1025
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = False
    SMTP_SSL: bool = False
    SMTP_TIMEOUT_SECONDS: int = 10
    MAIL_FROM: str = "SIMS Notifications <no-reply@example.com>"

    # ------------------------------------------------------------------ background worker
    WORKER_POLL_SECONDS: float = 1.0
    WORKER_BATCH_SIZE: int = 10
    JOB_MAX_ATTEMPTS: int = Field(6, gt=0)
    JOB_LOCK_SECONDS: int = Field(300, gt=0)
    # Prometheus metrics of the worker process. Loopback by default; containers listen on all
    # interfaces (docker-compose.yml) so Prometheus can scrape them over the private network.
    WORKER_METRICS_HOST: str = "127.0.0.1"
    WORKER_METRICS_PORT: int = 9101
    # Housekeeping: how long finished records are kept
    RETENTION_AUDIT_DAYS: int = 400
    RETENTION_JOBS_DAYS: int = 30
    RETENTION_EMAIL_LOG_DAYS: int = 365

    # ------------------------------------------------------------------ business defaults
    # Written to the app_settings table on first run (editable by admins at runtime)
    DEFAULT_APPROVAL_THRESHOLD: str = "50000.00"
    DEFAULT_TAX_RATE: str = "18.00"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_deployed(self) -> bool:
        """Staging and production share the hardened defaults."""
        return self.ENVIRONMENT in ("staging", "production")

    @property
    def api_docs_enabled(self) -> bool:
        return self.ENABLE_API_DOCS if self.ENABLE_API_DOCS is not None else not self.is_deployed

    @property
    def cookie_secure(self) -> bool:
        return self.COOKIE_SECURE if self.COOKIE_SECURE is not None else self.is_deployed

    @property
    def log_format(self) -> str:
        return self.LOG_FORMAT or ("json" if self.is_deployed else "text")

    @property
    def signup_allowed_domains(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.SIGNUP_ALLOWED_DOMAINS.split(",") if d.strip()]

    @property
    def jwt_verification_keys(self) -> list[str]:
        previous = [key.strip() for key in self.JWT_PREVIOUS_SECRET_KEYS.split(",") if key.strip()]
        return [self.JWT_SECRET_KEY, *previous]

    @property
    def data_encryption_keys(self) -> list[str]:
        return [key.strip() for key in self.DATA_ENCRYPTION_KEYS.split(",") if key.strip()]

    @property
    def session_idle_timeout_seconds(self) -> int:
        return self.SESSION_IDLE_TIMEOUT_MINUTES * 60

    @property
    def session_absolute_timeout_seconds(self) -> int:
        return self.SESSION_ABSOLUTE_TIMEOUT_HOURS * 3600

    @model_validator(mode="after")
    def _refuse_insecure_deployed_config(self):
        if self.is_deployed:
            for key in self.jwt_verification_keys:
                if key in INSECURE_JWT_SECRETS or len(key) < 32:
                    raise ValueError(
                        "JWT_SECRET_KEY (and any previous keys) must be random values of at least 32 characters "
                        'in staging/production (e.g. python -c "import secrets; print(secrets.token_urlsafe(48))")'
                    )
            if "*" in self.cors_origins_list:
                raise ValueError("CORS_ORIGINS must list explicit origins in staging/production")
            if self.DATABASE_TLS in ("disabled", "preferred"):
                raise ValueError("DATABASE_TLS must require encryption in staging/production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be enabled in staging/production")
            if not self.data_encryption_keys:
                raise ValueError(
                    "DATA_ENCRYPTION_KEYS is required in staging/production (generate one with "
                    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")'
                )
        for key in self.data_encryption_keys:
            try:
                Fernet(key)
            except (ValueError, TypeError) as exc:
                raise ValueError("DATA_ENCRYPTION_KEYS must contain valid Fernet keys") from exc
        if self.SMTP_SSL and self.SMTP_STARTTLS:
            raise ValueError("SMTP_SSL and SMTP_STARTTLS cannot both be enabled")
        if self.OTP_DELIVERY == "email" and not self.EMAIL_ENABLED:
            raise ValueError("OTP_DELIVERY=email requires EMAIL_ENABLED=true")
        if self.SESSION_ABSOLUTE_TIMEOUT_HOURS * 60 < self.SESSION_IDLE_TIMEOUT_MINUTES:
            raise ValueError("SESSION_ABSOLUTE_TIMEOUT_HOURS must not be shorter than SESSION_IDLE_TIMEOUT_MINUTES")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
