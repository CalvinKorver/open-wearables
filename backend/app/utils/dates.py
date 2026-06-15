import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import Query
from pydantic import BeforeValidator, Field

from app.utils.exceptions import DatetimeParseError

_CALENDAR_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DATE_PARAM_DESCRIPTION = (
    "ISO 8601 datetime (e.g. `2023-11-07T05:31:56Z`) or Unix timestamp in seconds. "
    "Date-only strings (e.g. `2023-11-07`) are also accepted and normalized to midnight UTC."
)

DateTimeQueryParam = Annotated[
    str,
    Query(
        description=_DATE_PARAM_DESCRIPTION,
        examples=["2023-11-07T05:31:56Z", "2023-11-07"],
        json_schema_extra={"format": "date-time"},
    ),
]


def _normalize_zone_offset(v: str | None) -> str | None:
    if v == "Z":
        return "+00:00"
    return v


ZoneOffset = Annotated[
    str | None,
    Field(
        None,
        description="Timezone offset in the format '+01:00' or '-05:30'",
        pattern=r"^[+-]\d{2}:\d{2}$",
        examples=["+01:00", "-05:30"],
        max_length=10,
    ),
    BeforeValidator(_normalize_zone_offset),
]


def is_calendar_date_only(dt_str: str) -> bool:
    """True if ``dt_str`` is exactly ``YYYY-MM-DD`` (no time component)."""
    if not _CALENDAR_DATE_ONLY.match(dt_str):
        return False
    try:
        datetime.fromisoformat(dt_str)
    except ValueError:
        return False
    return True


def parse_events_range_datetime(dt_str: str, *, bound: Literal["start", "end"]) -> datetime:
    """Parse ``start_date`` / ``end_date`` for event list and summary endpoints.

    Plain ``YYYY-MM-DD`` values are interpreted as **calendar days** in
    ``settings.default_calendar_timezone`` (default America/Los_Angeles), then converted
    to UTC. For ``bound=="end"``, the result is the **exclusive** upper bound (start of
    the following local calendar day as UTC), matching filters
    ``start_datetime >= start`` and ``end_datetime < end``.
    """
    if is_calendar_date_only(dt_str):
        from app.config import settings

        tz = ZoneInfo(settings.default_calendar_timezone)
        d = date.fromisoformat(dt_str)
        if bound == "start":
            local_start = datetime.combine(d, time.min, tzinfo=tz)
            return local_start.astimezone(timezone.utc)
        local_next = datetime.combine(d + timedelta(days=1), time.min, tzinfo=tz)
        return local_next.astimezone(timezone.utc)
    return parse_query_datetime(dt_str)


def parse_query_datetime(dt_str: str) -> datetime:
    """Parse datetime from ISO string or Unix timestamp (seconds).

    Raises:
        DatetimeParseError: If the string is not a valid ISO 8601 datetime or Unix timestamp.
    """
    try:
        timestamp = float(dt_str)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        raise DatetimeParseError(dt_str)


def parse_iso_datetime(dt_str: str | None) -> datetime | None:
    """Parse ISO 8601 datetime string, handling trailing Z notation.

    Converts "Z" suffix to "+00:00" timezone offset before parsing.
    Returns None if the string is None or invalid.

    Args:
        dt_str: ISO 8601 datetime string (e.g., "2024-01-15T08:00:00Z")

    Returns:
        Parsed datetime with timezone or None if parsing fails
    """
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_datetime_or_default(
    value: datetime | str | None,
    fallback: datetime,
) -> datetime:
    """Parse a datetime-or-string argument, falling back to default.

    Args:
        value: Datetime object, ISO string, or None
        fallback: Default datetime to use if value is None or invalid

    Returns:
        Parsed datetime or fallback
    """
    if value is None:
        return fallback
    if isinstance(value, str):
        return parse_iso_datetime(value) or fallback
    return value


def parse_webhook_data_timestamp(data_timestamp: str | None) -> datetime:
    """Parse a webhook data_timestamp to a UTC datetime.

    Tries ISO 8601 parsing; falls back to ``datetime.now(timezone.utc)``
    when the value is ``None`` or unparseable.
    """
    if data_timestamp:
        try:
            dt = datetime.fromisoformat(data_timestamp.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            pass
    return datetime.now(timezone.utc)


def offset_to_iso(offset_seconds: int | None) -> str | None:
    """Convert a timezone offset in seconds to ISO 8601 format (e.g. 3600 -> '+01:00')."""
    if offset_seconds is None:
        return None
    sign = "+" if offset_seconds >= 0 else "-"
    total = abs(offset_seconds)
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    return f"{sign}{hours:02d}:{minutes:02d}"
