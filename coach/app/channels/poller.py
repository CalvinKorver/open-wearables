"""Long-poll Telegram getUpdates and dispatch inbound messages to the coach."""

import asyncio
from contextlib import suppress
from logging import getLogger

from app.channels import telegram
from app.chat import handle_incoming
from app.storage import db

logger = getLogger(__name__)

_BACKOFF_START = 1.0
_BACKOFF_MAX = 30.0
_CRASH_RETRY_SECONDS = 5.0


async def run_poller(stop: asyncio.Event) -> None:
    """Poll until ``stop`` is set. Network errors back off; unexpected crashes propagate."""
    offset = db.get_telegram_offset()
    if offset is None:
        drained = await telegram.acknowledge_pending()
        if drained is not None:
            db.set_telegram_offset(drained)
            offset = drained
    logger.info("Telegram poller starting offset=%s", offset)

    backoff = _BACKOFF_START
    while not stop.is_set():
        try:
            updates = await telegram.get_updates(offset)
            backoff = _BACKOFF_START
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram getUpdates failed; retrying in %.1fs", backoff)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
            continue

        for update in updates:
            update_id = update.get("update_id")
            if update_id is None:
                continue
            offset = int(update_id) + 1
            db.set_telegram_offset(offset)
            incoming = telegram.parse_update(update)
            if incoming is None:
                continue
            try:
                await handle_incoming(incoming)
            except Exception:
                logger.exception("Failed handling Telegram message_id=%s", incoming.message_id)
                try:
                    await telegram.send_alert("Coach hit an error answering that. Try again in a moment.")
                except Exception:
                    logger.exception("Failed to send error alert")


async def run_poller_forever(stop: asyncio.Event) -> None:
    """Restart the poller after unexpected crashes until shutdown."""
    while not stop.is_set():
        try:
            await run_poller(stop)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram poller crashed; restarting in %.0fs", _CRASH_RETRY_SECONDS)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=_CRASH_RETRY_SECONDS)
