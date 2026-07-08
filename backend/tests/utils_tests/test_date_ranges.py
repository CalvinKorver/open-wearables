"""Tests for date_ranges module."""

from datetime import datetime, timezone

from app.utils.date_ranges import DateRangeMode, parse_range_end, parse_range_start
from app.utils.dates import parse_query_datetime


class TestDateRangeMode:
    def test_calendar_day_start_matches_events_parser(self) -> None:
        assert parse_range_start("2026-05-07", DateRangeMode.CALENDAR_DAY) == datetime(
            2026, 5, 7, 7, 0, 0, tzinfo=timezone.utc
        )

    def test_calendar_day_end_is_exclusive_next_local_day(self) -> None:
        assert parse_range_end("2026-05-07", DateRangeMode.CALENDAR_DAY) == datetime(
            2026, 5, 8, 7, 0, 0, tzinfo=timezone.utc
        )

    def test_utc_instant_uses_parse_query_datetime(self) -> None:
        assert parse_range_start("2026-05-07", DateRangeMode.UTC_INSTANT) == parse_query_datetime("2026-05-07")
        assert parse_range_end("2026-05-07", DateRangeMode.UTC_INSTANT) == parse_query_datetime("2026-05-07")
