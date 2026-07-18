from __future__ import annotations

import logging
import os
import signal
import socket
import threading

from kavach_saathi.container import get_container
from kavach_saathi.events import start_order_consumer, start_review_consumer, start_workflow_consumer
from kavach_saathi.redis_client import get_redis


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    container = get_container()
    threads = [
        start_review_consumer(container),
        start_order_consumer(container),
        start_workflow_consumer(container),
    ]
    stopped = threading.Event()

    def stop(_signum, _frame) -> None:
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    heartbeat_value = f"{socket.gethostname()}:{os.getpid()}"
    while not stopped.wait(2):
        try:
            get_redis().setex(
                "workers:event:heartbeat",
                container.settings.worker_heartbeat_ttl_seconds,
                heartbeat_value,
            )
        except Exception:
            logging.getLogger(__name__).warning("Could not publish worker heartbeat", exc_info=True)
        if any(not thread.is_alive() for thread in threads):
            raise RuntimeError("A required event-consumer thread stopped unexpectedly")


if __name__ == "__main__":
    main()
