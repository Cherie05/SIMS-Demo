"""Test fixtures. Tests run against a real MySQL database (default: sims_test from docker-compose)
so row locks, CHECK constraints and transactions behave exactly as in production."""

import os

from tests.database_safety import validate_test_database_url

_test_database_url = os.getenv("TEST_DATABASE_URL", "mysql+pymysql://sims:sims_password@127.0.0.1:3306/sims_test")
validate_test_database_url(_test_database_url)
os.environ["DATABASE_URL"] = _test_database_url
# Isolate tests from inherited production credentials, authentication policy and external services.
os.environ.update(
    ENVIRONMENT="test",
    DATABASE_PASSWORD="",
    DATABASE_TLS="preferred",
    JWT_SECRET_KEY="isolated-tests-signing-key-at-least-32-characters",
    JWT_PREVIOUS_SECRET_KEYS="",
    DATA_ENCRYPTION_KEYS="",
    COOKIE_SECURE="false",
    LOGIN_OTP_REQUIRED="true",
    OTP_DELIVERY="log",
    SIGNUP_ENABLED="true",
    SIGNUP_ALLOWED_DOMAINS="",
    CORS_ORIGINS="http://localhost:5173,http://localhost:3000",
    METRICS_ENABLED="true",
    METRICS_TOKEN="",
)
os.environ["EMAIL_ENABLED"] = "true"
os.environ["REDIS_URL"] = ""  # in-memory rate limits; tests that need Redis use fakeredis
os.environ["LOG_FORMAT"] = "text"
# Cheap Argon2 parameters keep the suite fast; production uses the OWASP parameters from config.
os.environ["PASSWORD_HASH_MEMORY_KIB"] = "1024"
os.environ["PASSWORD_HASH_ITERATIONS"] = "1"

from collections import defaultdict  # noqa: E402
from datetime import UTC, datetime, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import clock, rate_limit  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password, new_session_id  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AppSetting, Base, Customer, User, UserRole, UserSession  # noqa: E402
from app.schemas.product import ProductCreate  # noqa: E402
from app.services import email_service, otp_service, product_service  # noqa: E402
from app.worker.runner import drain  # noqa: E402

PASSWORD = "Password@123"
PASSWORD_HASH = hash_password(PASSWORD)
THRESHOLD = Decimal("10000.00")
CSRF = {"X-Requested-With": "sims-web"}
# The real delivery function, for tests that check what reaches the log or the mailbox.
REAL_OTP_DELIVER = otp_service.deliver


@pytest.fixture(scope="session", autouse=True)
def _schema():
    validate_test_database_url(engine.url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    validate_test_database_url(engine.url)
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    validate_test_database_url(engine.url)
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())
        finally:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    rate_limit.clear_all()
    yield
    rate_limit.clear_all()


@pytest.fixture(autouse=True)
def otp_codes(monkeypatch):
    """One-time codes by email address, captured instead of being written to the log."""
    codes: dict[str, list[str]] = defaultdict(list)
    monkeypatch.setattr(otp_service, "deliver", lambda email, _name, _purpose, code: codes[email].append(code))
    return codes


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    """Capture outgoing mail instead of talking to an SMTP server (the worker sends it: see run_jobs)."""
    outbox = []
    monkeypatch.setattr(email_service, "_deliver", lambda message: outbox.append(message))
    return outbox


@pytest.fixture
def run_jobs():
    """run_jobs() runs every due background job now, like the worker would. Returns how many ran."""
    return drain


@pytest.fixture
def later(monkeypatch):
    """later(seconds) moves the server clock forward."""
    real_utcnow = clock.utcnow

    def move(seconds: float) -> None:
        monkeypatch.setattr(clock, "utcnow", lambda: real_utcnow() + timedelta(seconds=seconds))

    return move


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def users(db):
    """admin, manager, sales, sales2 - plus business settings: threshold 10,000 and 0% tax."""
    db.add_all(
        [
            AppSetting(key="approval_threshold", value=str(THRESHOLD)),
            AppSetting(key="tax_rate", value="0"),
        ]
    )
    created = {}
    for key, role in [
        ("admin", UserRole.ADMIN),
        ("manager", UserRole.MANAGER),
        ("sales", UserRole.SALES),
        ("sales2", UserRole.SALES),
    ]:
        user = User(
            name=key.title(),
            email=f"{key}@example.com",
            password_hash=PASSWORD_HASH,
            role=role,
            email_verified_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(user)
        created[key] = user
    db.commit()
    return created


@pytest.fixture
def make_session(db):
    """make_session(user) -> id of a fresh, active session (for hand-made access tokens)."""

    def _make(user: User) -> str:
        now = clock.utcnow()
        session = UserSession(
            id=new_session_id(),
            user_id=user.id,
            authenticated_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add(session)
        db.commit()
        return session.id

    return _make


def sign_in(client, otp_codes, email: str, password: str = PASSWORD) -> dict:
    """Full two-step sign-in (password, then the one-time code). Returns the session JSON."""
    challenge = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert challenge.status_code == 200, challenge.text
    assert challenge.json()["otp_required"] is True
    verified = client.post(
        "/api/v1/auth/otp/verify",
        json={"challenge_id": challenge.json()["challenge_id"], "code": otp_codes[email][-1]},
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


@pytest.fixture
def auth(client, users, otp_codes):
    """auth('manager') -> Authorization headers for that seeded user."""
    cache = {}

    def headers(key: str) -> dict[str, str]:
        if key not in cache:
            session = sign_in(client, otp_codes, users[key].email)
            cache[key] = {"Authorization": f"Bearer {session['access_token']}"}
        return cache[key]

    return headers


@pytest.fixture
def customer(db, users):
    customer = Customer(name="Acme Corp", email="buyer@acme.example.com", phone="+91 99999 00000")
    db.add(customer)
    db.commit()
    return customer


@pytest.fixture
def make_product(db, users):
    def _make(sku: str = "P-1", price: str = "1000.00", stock: int = 10, reorder: int = 2):
        data = ProductCreate(
            sku=sku, name=f"Product {sku}", unit_price=Decimal(price), opening_stock=stock, reorder_level=reorder
        )
        return product_service.create_product(db, data, users["admin"])

    return _make
