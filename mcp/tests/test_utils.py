"""Tests for MCP utility helpers."""

from datetime import datetime, timezone

from app.utils import (
    format_time_ampm,
    local_time_fields_for_range,
    parse_instant_to_utc,
    zone_offset_to_fixed_tz,
)


def test_parse_instant_to_utc_z_suffix() -> None:
    dt = parse_instant_to_utc("2026-05-08T07:00:00Z")
    assert dt is not None
    assert dt == datetime(2026, 5, 8, 7, 0, 0, tzinfo=timezone.utc)


def test_parse_instant_to_utc_naive_assumes_utc() -> None:
    dt = parse_instant_to_utc("2026-05-08T07:00:00")
    assert dt is not None
    assert dt.tzinfo == timezone.utc


def test_zone_offset_to_fixed_tz_invalid() -> None:
    assert zone_offset_to_fixed_tz(None) is None
    assert zone_offset_to_fixed_tz("") is None
    assert zone_offset_to_fixed_tz("invalid") is None


def test_local_fields_with_record_zone_offset() -> None:
    start = "2026-05-08T07:00:00+00:00"
    end = "2026-05-08T07:45:00+00:00"
    fields = local_time_fields_for_range(start, end, "-07:00", "UTC")
    assert fields["local_start_time"] == "12:00 AM"
    assert fields["local_end_time"] == "12:45 AM"
    assert fields["start_local"] is not None
    assert "-07:00" in fields["start_local"]


def test_local_fields_fallback_iana_matches_offset_when_dst() -> None:
    """07:00 UTC on 2026-05-08 is 00:00 PDT (America/Los_Angeles)."""
    start = "2026-05-08T07:00:00+00:00"
    fields = local_time_fields_for_range(start, None, None, "America/Los_Angeles")
    assert fields["local_start_time"] == "12:00 AM"
    assert fields["start_local"] is not None
    assert "-07:00" in fields["start_local"]
    assert fields["end_local"] is None
    assert fields["local_end_time"] is None


def test_format_time_ampm() -> None:
    dt = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
    assert format_time_ampm(dt) == "12:05 AM"
    dt_noon = datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc)
    assert format_time_ampm(dt_noon) == "12:30 PM"
