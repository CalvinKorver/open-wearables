"""Daily briefing orchestration: idempotency, MCP, agent, channel, persistence."""

from datetime import date, datetime, timedelta
from logging import getLogger

from app.agent.loop import generate_briefing
from app.agent.mcp_client import open_mcp_client
from app.channels.telegram import send_alert, send_briefing
from app.config import settings
from app.storage import db

logger = getLogger(__name__)


def yesterday_local() -> date:
    """The local-yesterday date in the configured BRIEFING_TIMEZONE."""
    now_local = datetime.now(settings.tz)
    return (now_local - timedelta(days=1)).date()


async def run_for_date(local_date: date, *, force: bool = False) -> None:
    """Run a single briefing for `local_date`. Idempotent on (local_date) unless force=True."""
    db.init_db()

    claimed = db.claim_run(local_date, force=force)
    if claimed is None:
        logger.info("Briefing for %s already sent; skipping (use --force to override)", local_date)
        return

    logger.info("Generating briefing for %s", local_date)
    try:
        async with open_mcp_client() as session:
            text = await generate_briefing(session, local_date)
    except Exception as e:
        logger.exception("Briefing generation failed for %s", local_date)
        db.mark_failed(local_date, f"generation: {e}")
        await _notify_failure(local_date, e)
        raise

    try:
        message_id = await send_briefing(text)
    except Exception as e:
        logger.exception("Telegram send failed for %s", local_date)
        db.mark_failed(local_date, f"send: {e}")
        await _notify_failure(local_date, e)
        raise

    db.mark_sent(local_date, message_id)
    logger.info("Briefing for %s delivered (message_id=%s)", local_date, message_id)


async def run_daily() -> None:
    """Entrypoint used by the scheduler: brief yesterday in the user's timezone."""
    await run_for_date(yesterday_local())


async def _notify_failure(local_date: date, exc: BaseException) -> None:
    """Best-effort error ping to Telegram so the user notices missed briefings."""
    try:
        await send_alert(f"Coach briefing for {local_date} failed: {exc}")
    except Exception:
        logger.exception("Failed to send fatal-error alert to Telegram")
