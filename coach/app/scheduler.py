"""APScheduler setup for the daily briefing."""

from logging import getLogger

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.briefing import run_daily
from app.config import settings

logger = getLogger(__name__)

# If the coach was down at briefing time and comes back up later that morning,
# fire the missed run rather than waiting until tomorrow.
_MISFIRE_GRACE_SECONDS = 60 * 60


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    trigger = CronTrigger(
        hour=settings.briefing_hour,
        minute=settings.briefing_minute,
        timezone=settings.tz,
    )
    scheduler.add_job(
        run_daily,
        trigger=trigger,
        id="daily_briefing",
        name="Daily Telegram briefing",
        misfire_grace_time=_MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    logger.info(
        "Scheduled daily briefing at %02d:%02d %s",
        settings.briefing_hour,
        settings.briefing_minute,
        settings.briefing_timezone,
    )
    return scheduler
