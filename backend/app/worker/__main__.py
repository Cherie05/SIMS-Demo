"""Entry point: python -m app.worker  (graceful shutdown on SIGTERM / Ctrl+C)."""

import signal

from prometheus_client import start_http_server

from app.core.config import settings
from app.core.logging import configure_logging


def main() -> None:
    configure_logging("sims-worker")
    from app.worker.runner import Worker  # after logging is configured

    worker = Worker()

    def stop(signum, _frame):
        worker.stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if settings.METRICS_ENABLED:
        start_http_server(settings.WORKER_METRICS_PORT, addr=settings.WORKER_METRICS_HOST)
    worker.heartbeat(force=True)
    worker.run_forever()


if __name__ == "__main__":
    main()
