"""Entrypoint for the coach service: configure logging, start the scheduler, run forever."""

import asyncio
import logging
import signal
import sys

from app.config import settings
from app.scheduler import build_scheduler
from app.storage import db

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def _validate_required() -> None:
    missing = settings.required_missing()
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing) + ". See coach/config/.env.example."
        )


async def _run_forever() -> None:
    _validate_required()
    db.init_db()
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("Coach scheduler started. Waiting for the next briefing.")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await stop.wait()
    finally:
        logger.info("Shutting down scheduler")
        scheduler.shutdown(wait=False)


def main() -> None:
    _configure_logging()
    asyncio.run(_run_forever())


if __name__ == "__main__":
    main()
