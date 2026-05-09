"""Tests for date utility functions."""

from datetime import datetime, timezone

import pytest

from app.utils.dates import (
    is_calendar_date_only,
    parse_events_range_datetime,
    parse_query_datetime,
)
from app.utils.exceptions import DatetimeParseError


class TestParseQueryDatetime:
    """Test suite for parse_query_datetime."""

    def test_parse_unix_timestamp(self) -> None:
        result = parse_query_datetime("1704067200")
        assert result == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_parse_iso_format(self) -> None:
        result = parse_query_datetime("2024-01-01T00:00:00+00:00")
        assert result == datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_invalid_format_raises_error(self) -> None:
        with pytest.raises(DatetimeParseError) as exc_info:
            parse_query_datetime("invalid")
        assert "Invalid datetime format" in exc_info.value.detail


class TestParseEventsRangeDatetime:
    """Calendar-day bounds for /events/* list endpoints."""

    def test_date_only_start_is_utc_midnight(self) -> None:
        assert parse_events_range_datetime("2026-05-07", bound="start") == datetime(
            2026, 5, 7, 0, 0, 0, tzinfo=timezone.utc
        )

    def test_date_only_end_is_exclusive_next_day(self) -> None:
        assert parse_events_range_datetime("2026-05-07", bound="end") == datetime(
            2026, 5, 8, 0, 0, 0, tzinfo=timezone.utc
        )

    def test_iso_datetime_passthrough_uses_parse_query_datetime(self) -> None:
        s = "2026-05-07T12:00:00+00:00"
        assert parse_events_range_datetime(s, bound="start") == parse_query_datetime(s)
        assert parse_events_range_datetime(s, bound="end") == parse_query_datetime(s)


class TestIsCalendarDateOnly:
    def test_accepts_plain_date(self) -> None:
        assert is_calendar_date_only("2026-05-07") is True

    def test_rejects_datetime_string(self) -> None:
        assert is_calendar_date_only("2026-05-07T00:00:00Z") is False

    def test_rejects_invalid_calendar_date(self) -> None:
        assert is_calendar_date_only("2026-02-30") is False
