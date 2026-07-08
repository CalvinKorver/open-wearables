from datetime import date, datetime, timedelta
from logging import getLogger
from uuid import UUID
from zoneinfo import ZoneInfo

from anthropic import Anthropic
from celery import shared_task

from app.config import settings
from app.database import DbSession, SessionLocal
from app.schemas.model_crud.activities import EventRecordQueryParams
from app.schemas.responses.activity import SleepSummary, Workout
from app.services import event_record_service, summaries_service
from app.utils.date_ranges import DateRangeMode, parse_range_end, parse_range_start
from app.utils.sentry_helpers import log_and_capture_error
from app.utils.structured_logging import log_structured
from app.utils.telegram_client import send_message as send_telegram_message

logger = getLogger(__name__)

SYSTEM_PROMPT = """You are a concise morning health coach. Given the user's wearable data,
write a friendly daily briefing covering last night's sleep and yesterday's training.
Use plain text suitable for Telegram (no markdown tables). Keep under 3000 characters.
Highlight key metrics, trends worth noting, and one actionable suggestion if appropriate."""

CLAUDE_MODEL = "claude-sonnet-4-5"


def _is_briefing_configured() -> bool:
    return bool(
        settings.anthropic_api_key
        and settings.telegram_bot_token
        and settings.telegram_chat_id
        and settings.daily_briefing_user_id
    )


def _local_today() -> date:
    return datetime.now(ZoneInfo(settings.default_calendar_timezone)).date()


def _date_range_bounds(target_date: date) -> tuple[datetime, datetime]:
    date_str = target_date.isoformat()
    start = parse_range_start(date_str, DateRangeMode.CALENDAR_DAY)
    end = parse_range_end(date_str, DateRangeMode.CALENDAR_DAY)
    return start, end


def _minutes_to_hm(minutes: int | None) -> str:
    if minutes is None:
        return "unknown"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m"


def _format_sleep_summary(sleep: SleepSummary | None, sleep_date: date) -> str:
    lines = [f"Sleep (wake date {sleep_date.isoformat()}):"]
    if sleep is None:
        lines.append("  No sleep data recorded.")
        return "\n".join(lines)

    lines.append(f"  Duration: {_minutes_to_hm(sleep.duration_minutes)}")
    if sleep.time_in_bed_minutes is not None:
        lines.append(f"  Time in bed: {_minutes_to_hm(sleep.time_in_bed_minutes)}")
    if sleep.efficiency_percent is not None:
        lines.append(f"  Efficiency: {sleep.efficiency_percent:.1f}%")
    if sleep.stages:
        stages = sleep.stages
        lines.append(
            f"  Stages — deep: {_minutes_to_hm(stages.deep_minutes)}, "
            f"light: {_minutes_to_hm(stages.light_minutes)}, "
            f"REM: {_minutes_to_hm(stages.rem_minutes)}, "
            f"awake: {_minutes_to_hm(stages.awake_minutes)}"
        )
    if sleep.avg_heart_rate_bpm is not None:
        lines.append(f"  Avg heart rate: {sleep.avg_heart_rate_bpm} bpm")
    if sleep.avg_hrv_rmssd_ms is not None:
        lines.append(f"  Avg HRV (RMSSD): {sleep.avg_hrv_rmssd_ms:.1f} ms")
    if sleep.source and sleep.source.provider:
        lines.append(f"  Source: {sleep.source.provider}")
    return "\n".join(lines)


def _format_duration_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "unknown"
    return _minutes_to_hm(seconds // 60)


def _format_workouts(workouts: list[Workout], training_date: date) -> str:
    lines = [f"Training ({training_date.isoformat()}):"]
    if not workouts:
        lines.append("  No workouts recorded.")
        return "\n".join(lines)

    for workout in workouts:
        name = workout.name or workout.type
        lines.append(f"  - {name}")
        lines.append(f"    Type: {workout.type}")
        lines.append(f"    Duration: {_format_duration_seconds(workout.duration_seconds)}")
        if workout.distance_meters is not None:
            lines.append(f"    Distance: {workout.distance_meters / 1000:.2f} km")
        if workout.calories_kcal is not None:
            lines.append(f"    Calories: {workout.calories_kcal:.0f} kcal")
        if workout.avg_heart_rate_bpm is not None:
            lines.append(f"    Avg HR: {workout.avg_heart_rate_bpm} bpm")
        if workout.source and workout.source.provider:
            lines.append(f"    Source: {workout.source.provider}")
    return "\n".join(lines)


def _build_data_payload(
    sleep: SleepSummary | None,
    workouts: list[Workout],
    sleep_date: date,
    training_date: date,
) -> str:
    return "\n\n".join(
        [
            _format_sleep_summary(sleep, sleep_date),
            _format_workouts(workouts, training_date),
        ]
    )


def _generate_briefing_message(data_payload: str) -> str:
    client = Anthropic(api_key=settings.anthropic_api_key.get_secret_value())  # ty:ignore[unresolved-attribute]
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": data_payload}],
    )
    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        raise ValueError("Claude returned no text content")
    return "\n".join(text_blocks)


def _fetch_sleep_summary(db: DbSession, user_id: UUID, sleep_date: date) -> SleepSummary | None:
    start, end = _date_range_bounds(sleep_date)
    result = summaries_service.get_sleep_summaries(db, user_id, start, end, cursor=None, limit=10)
    if not result.data:
        return None
    return result.data[0]


def _fetch_workouts(db: DbSession, user_id: UUID, training_date: date) -> list[Workout]:
    start, end = _date_range_bounds(training_date)
    params = EventRecordQueryParams(
        start_datetime=start,
        end_datetime=end,
        limit=50,
        sort_order="asc",
    )
    result = event_record_service.get_workouts(db, user_id, params)
    return list(result.data)


@shared_task
def daily_health_briefing() -> dict[str, str]:
    """Generate and send a daily sleep + training briefing via Telegram."""
    if not _is_briefing_configured():
        log_structured(
            logger,
            "info",
            "Daily health briefing skipped — required settings not configured",
            task="daily_health_briefing",
        )
        return {"status": "skipped", "message": "Briefing not configured"}

    user_id = UUID(settings.daily_briefing_user_id)  # ty:ignore[arg-type]
    sleep_date = _local_today()
    training_date = sleep_date - timedelta(days=1)

    try:
        with SessionLocal() as db:
            sleep = _fetch_sleep_summary(db, user_id, sleep_date)
            workouts = _fetch_workouts(db, user_id, training_date)

        data_payload = _build_data_payload(sleep, workouts, sleep_date, training_date)
        briefing_text = _generate_briefing_message(data_payload)

        if not send_telegram_message(briefing_text):
            raise RuntimeError("Failed to send Telegram message")

        log_structured(
            logger,
            "info",
            f"Daily health briefing sent for user {user_id}",
            task="daily_health_briefing",
            user_id=str(user_id),
        )
        return {"status": "success", "message": "Daily health briefing sent"}
    except Exception as e:
        log_and_capture_error(
            e,
            logger,
            f"Daily health briefing failed: {e}",
            extra={"user_id": str(user_id), "task": "daily_health_briefing"},
        )
        raise
