"""Unified date-range parsing for API query parameters.

Endpoints choose a :class:`DateRangeMode` instead of importing parsers from
``dates.py`` directly. This keeps fork calendar-day semantics isolated and
makes upstream merges to ``dates.py`` less likely to touch every route file.

Endpoint mapping
----------------
CALENDAR_DAY (``default_calendar_timezone``, exclusive end bound for date-only strings):
  - GET .../summaries/activity, .../summaries/sleep
  - GET .../events/workouts, .../events/sleep

UTC_INSTANT (date-only strings normalized to midnight UTC via ``parse_query_datetime``):
  - GET .../summaries/recovery
  - GET .../events/menstrual-cycles
  - GET .../timeseries, .../health_scores (use ``parse_query_datetime`` directly)

Repository aggregation uses per-point ``zone_offset`` (see data_point_series_repository).
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from app.utils.dates import parse_events_range_datetime, parse_query_datetime


class DateRangeMode(StrEnum):
    """How ``start_date`` / ``end_date`` query params are converted to UTC datetimes."""

    UTC_INSTANT = "utc_instant"
    CALENDAR_DAY = "calendar_day"


def parse_range_bound(
    dt_str: str,
    *,
    bound: Literal["start", "end"],
    mode: DateRangeMode,
) -> datetime:
    """Parse one bound of a range query parameter."""
    if mode == DateRangeMode.CALENDAR_DAY:
        return parse_events_range_datetime(dt_str, bound=bound)
    return parse_query_datetime(dt_str)


def parse_range_start(dt_str: str, mode: DateRangeMode) -> datetime:
    """Parse a range ``start_date`` / ``start_time`` query parameter."""
    return parse_range_bound(dt_str, bound="start", mode=mode)


def parse_range_end(dt_str: str, mode: DateRangeMode) -> datetime:
    """Parse a range ``end_date`` / ``end_time`` query parameter."""
    return parse_range_bound(dt_str, bound="end", mode=mode)
