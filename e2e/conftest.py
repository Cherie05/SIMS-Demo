"""Fixtures for the end-to-end acceptance suite: a real browser, the real API and real email (Mailpit).

The suite runs against an already running stack, configured with environment variables:

    E2E_BASE_URL         the web app                          (default http://localhost:3000)
    E2E_MAILPIT_URL      Mailpit, which receives the emails   (default http://127.0.0.1:8025)
    E2E_ADMIN_EMAIL      an existing admin account            (default the demo admin)
    E2E_ADMIN_PASSWORD
    E2E_OTP_LOG_COMMAND  prints the backend log, where sign-in codes are written
                         (default "docker compose logs --no-color --since 30m backend", run from the repo root)
    E2E_OTP_LOG_FILE     instead of the command: a file the backend's output is saved to, when it
                         runs without Docker (uvicorn app.main:app > backend.log 2>&1)
    E2E_OTP_SOURCE       log (default) or email (reads one-time codes from Mailpit)
    E2E_HEADED=1         watch the browser while it runs
    E2E_BROWSER          chromium (default), firefox or webkit
    E2E_TLS_VERIFY=0     accept a self-signed / local-CA certificate (production stack on https://localhost)

Each run creates its own manager, sales user, customer and product, so it only relies on the
admin account and works the same against the demo stack and a production stack.
"""

import contextlib
import os
import re
import shlex
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:3000").rstrip("/")
MAILPIT_URL = os.getenv("E2E_MAILPIT_URL", "http://127.0.0.1:8025").rstrip("/")


def _loopback_url(url: str) -> str:
    """Address "localhost" by the loopback address that actually answers.

    Python tries ::1 before 127.0.0.1 and, on Windows, waits about two seconds for every refused
    attempt. Docker publishes the stack on 127.0.0.1 only, while Vite's dev server may listen on
    ::1 only. Plain HTTP only: over HTTPS the certificate and the edge's site address are for the
    configured host name.
    """
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != "localhost":
        return url
    port = parts.port or 80
    for address, netloc in (("127.0.0.1", f"127.0.0.1:{port}"), ("::1", f"[::1]:{port}")):
        with contextlib.suppress(OSError), socket.create_connection((address, port), timeout=1):
            return urlunsplit(parts._replace(netloc=netloc))
    return url


# API calls from Python (bearer tokens, no cookies); the browser keeps BASE_URL for its cookies.
API_BASE_URL = _loopback_url(BASE_URL)
ADMIN_EMAIL = os.getenv("E2E_ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("E2E_ADMIN_PASSWORD", "Admin@123")
USER_PASSWORD = "E2e-Passw0rd"
REPO_ROOT = Path(__file__).resolve().parent.parent
OTP_LOG_COMMAND = os.getenv("E2E_OTP_LOG_COMMAND", "docker compose logs --no-color --since 30m backend")
OTP_LOG_FILE = os.getenv("E2E_OTP_LOG_FILE")
OTP_SOURCE = os.getenv("E2E_OTP_SOURCE", "log")
if OTP_SOURCE not in {"log", "email"}:
    raise ValueError("E2E_OTP_SOURCE must be log or email")
BROWSER = os.getenv("E2E_BROWSER", "chromium")
TLS_VERIFY = os.getenv("E2E_TLS_VERIFY", "1") != "0"

expect.set_options(timeout=15_000)


# ----------------------------------------------------------------------------- one-time codes


def _backend_log() -> str:
    if OTP_LOG_FILE:
        data = Path(OTP_LOG_FILE).read_bytes()
        # Windows PowerShell 5.1 saves redirected output as UTF-16.
        return data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig", errors="replace")
    # Test tooling: the command comes from the developer's own environment, never from user input.
    result = subprocess.run(
        shlex.split(OTP_LOG_COMMAND),  # nosemgrep: dangerous-subprocess-use-tainted-env-args
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout + result.stderr


def _codes_in_log(email: str) -> list[str]:
    return re.findall(rf"OTP for {re.escape(email)} \([^)]*\): (\d{{6}})", _backend_log())


def codes_so_far(email: str) -> int | frozenset[str]:
    return len(_codes_in_log(email)) if OTP_SOURCE == "log" else frozenset(_codes_in_mail(email))


def _codes_in_mail(email: str) -> dict[str, str]:
    response = httpx.get(f"{MAILPIT_URL}/api/v1/messages", params={"limit": 500}, timeout=15)
    response.raise_for_status()
    messages = response.json()["messages"]
    codes = {}
    # Mailpit lists newest first; keep the same oldest-to-newest order as the log helper.
    for message in reversed(messages):
        if email.lower() not in {recipient["Address"].lower() for recipient in message["To"]}:
            continue
        match = re.fullmatch(r"(\d{6}) is your SIMS verification code", message["Subject"])
        if match:
            codes[message["ID"]] = match.group(1)
    return codes


def read_new_code(email: str, seen: int | frozenset[str], timeout: float = 20) -> str:
    """Wait for the next code delivered to this address, via the configured test-only source."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if isinstance(seen, int):
            codes = _codes_in_log(email)
            if len(codes) > seen:
                return codes[-1]
        else:
            new_codes = [code for message_id, code in _codes_in_mail(email).items() if message_id not in seen]
            if new_codes:
                return new_codes[-1]
        time.sleep(0.4)
    raise AssertionError(f"No one-time code for {email} appeared via {OTP_SOURCE} within {timeout}s")


# ----------------------------------------------------------------------------- API & email helpers


class Api:
    """Thin JSON client for the REST API, used to set up data and to check results."""

    def __init__(self, token: str):
        self.token = token
        self._client = httpx.Client(
            base_url=f"{API_BASE_URL}/api/v1",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
            verify=TLS_VERIFY,
        )

    @classmethod
    def login(cls, email: str, password: str) -> "Api":
        """Two-step sign-in: password, then the one-time code from the backend log."""
        seen = codes_so_far(email)
        response = httpx.post(
            f"{API_BASE_URL}/api/v1/auth/login",
            json={"email": email, "password": password},
            timeout=30,
            verify=TLS_VERIFY,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("otp_required"):
            verified = httpx.post(
                f"{API_BASE_URL}/api/v1/auth/otp/verify",
                json={"challenge_id": body["challenge_id"], "code": read_new_code(email, seen)},
                timeout=30,
                verify=TLS_VERIFY,
            )
            verified.raise_for_status()
            body = verified.json()
        return cls(body["access_token"])

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        return self._client.request(method, path, **kwargs)

    def get(self, path: str, **params):
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: dict):
        response = self._client.post(path, json=body)
        response.raise_for_status()
        return response.json()


class Mailbox:
    """Reads the messages the system sent, through Mailpit's API."""

    def messages(self) -> list[dict]:
        return httpx.get(f"{MAILPIT_URL}/api/v1/messages", params={"limit": 200}, timeout=30).json()["messages"]

    def wait_for(self, to: str, subject_contains: str, timeout: float = 30) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for message in self.messages():
                recipients = {r["Address"].lower() for r in message["To"]}
                if to.lower() in recipients and subject_contains in message["Subject"]:
                    return message
            time.sleep(0.5)
        raise AssertionError(f"No email to {to} with subject containing {subject_contains!r} within {timeout}s")

    def html(self, message: dict) -> str:
        return httpx.get(f"{MAILPIT_URL}/api/v1/message/{message['ID']}", timeout=30).json()["HTML"]

    def subjects_mentioning(self, text: str) -> list[str]:
        return [m["Subject"] for m in self.messages() if text in m["Subject"]]


# ----------------------------------------------------------------------------- shared state


@dataclass
class World:
    """Data created by this run, shared by the ordered acceptance steps."""

    run: str
    threshold: Decimal
    tax_rate: Decimal
    unit_price: Decimal
    manager_email: str
    sales_email: str
    sku: str
    product_name: str
    customer_name: str
    customer_email: str
    dashboard_before: dict
    product_id: int | None = None
    customer_id: int | None = None
    orders: dict[str, dict] = field(default_factory=dict)
    approval_link: str | None = None

    def order_total(self, quantity: int) -> Decimal:
        subtotal = self.unit_price * quantity
        tax = (subtotal * self.tax_rate / 100).quantize(Decimal("0.01"))
        return subtotal + tax


@pytest.fixture(scope="session")
def admin_api() -> Api:
    return Api.login(ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture(scope="session")
def mailbox() -> Mailbox:
    return Mailbox()


@pytest.fixture(scope="session")
def world(admin_api: Api) -> World:
    run = uuid.uuid4().hex[:6]
    settings = admin_api.get("/settings")
    threshold, tax_rate = Decimal(str(settings["approval_threshold"])), Decimal(str(settings["tax_rate"]))
    # One unit stays within the threshold, two units exceed it - whatever the configured values are.
    unit_price = (threshold * Decimal("0.8") / (1 + tax_rate / 100)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    manager_email, sales_email = f"e2e-manager-{run}@example.com", f"e2e-sales-{run}@example.com"
    for name, email, role in [
        (f"E2E Manager {run}", manager_email, "MANAGER"),
        (f"E2E Sales {run}", sales_email, "SALES"),
    ]:
        admin_api.post("/users", {"name": name, "email": email, "password": USER_PASSWORD, "role": role})

    return World(
        run=run,
        threshold=threshold,
        tax_rate=tax_rate,
        unit_price=unit_price,
        manager_email=manager_email,
        sales_email=sales_email,
        sku=f"E2E-{run}".upper(),
        product_name=f"E2E Workstation {run}",
        customer_name=f"E2E Customer {run}",
        customer_email=f"e2e-customer-{run}@example.com",
        dashboard_before=admin_api.get("/dashboard/summary"),
    )


@pytest.fixture(scope="session")
def sales_api(world: World) -> Api:
    return Api.login(world.sales_email, USER_PASSWORD)


# ----------------------------------------------------------------------------- browser


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        instance = getattr(playwright, BROWSER).launch(headless=not os.getenv("E2E_HEADED"))
        yield instance
        instance.close()


@pytest.fixture(scope="session")
def browser_errors() -> list[str]:
    """Console errors and uncaught exceptions from every page the suite opens."""
    return []


def new_page(browser, browser_errors: list[str], **context_options) -> Page:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900}, ignore_https_errors=not TLS_VERIFY, **context_options
    )
    page = context.new_page()
    page.on("console", lambda m: m.type == "error" and browser_errors.append(f"{page.url}: {m.text}"))
    page.on("pageerror", lambda e: browser_errors.append(f"{page.url}: {e}"))
    return page


def sign_in(page: Page, email: str, password: str, on_challenge=None) -> None:
    page.goto(f"{BASE_URL}/login")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    seen = codes_so_far(email)
    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_role("heading", name="Two-step verification")).to_be_visible()
    if on_challenge:
        on_challenge(page)
    # Filling the first box with the whole code is what a phone's one-time-code autofill does.
    page.get_by_label("Digit 1 of 6").fill(read_new_code(email, seen))
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()


@pytest.fixture(scope="session")
def sales_page(browser, browser_errors, world) -> Page:
    page = new_page(browser, browser_errors)
    sign_in(page, world.sales_email, USER_PASSWORD)
    return page


@pytest.fixture(scope="session")
def manager_page(browser, browser_errors, world) -> Page:
    page = new_page(browser, browser_errors)
    sign_in(page, world.manager_email, USER_PASSWORD)
    return page


@pytest.fixture
def anonymous_page(browser, browser_errors) -> Page:
    page = new_page(browser, browser_errors)
    yield page
    page.context.close()
