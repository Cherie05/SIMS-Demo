"""Per-request context (request id, client, user) shared by logging, auditing and metrics.

Context variables follow the request through FastAPI's thread pool, so code anywhere in a
request can read them without passing the request object around.
"""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RequestContext:
    request_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    method: str | None = None
    path: str | None = None
    user_id: int | None = None


_context: ContextVar[RequestContext | None] = ContextVar("sims_request_context", default=None)


def current() -> RequestContext:
    """The active request's context (an empty one outside of requests, e.g. in the worker)."""
    return _context.get() or RequestContext()


def bind(ctx: RequestContext):
    return _context.set(ctx)


def reset(token) -> None:
    _context.reset(token)


def set_user(user_id: int) -> None:
    ctx = _context.get()
    if ctx is not None:
        ctx.user_id = user_id
