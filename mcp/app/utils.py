"""Common utility functions for MCP tools."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# OW stores zone_offset like "+08:00" / "-07:00" (same convention as event_record_service._local_sleep_date).


def normalize_datetime(dt_str: str | None) -> str | None:
    """Normalize datetime string to ISO 8601 format."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.isoformat()
    except (ValueError, AttributeError):
        return dt_str


def parse_instant_to_utc(dt_str: str | None) -> datetime | None:
    """Parse an API datetime string to an aware UTC instant."""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def zone_offset_to_fixed_tz(zone_offset: str | None) -> timezone | None:
    """Map OW zone_offset (+/-HH:MM) to a datetime.timezone, or None if invalid/missing."""
    if not zone_offset or len(zone_offset) < 6 or zone_offset[0] not in "+-":
        return None
    try:
        sign = 1 if zone_offset[0] == "+" else -1
        hours, minutes = int(zone_offset[1:3]), int(zone_offset[4:6])
    except ValueError:
        return None
    return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))


def to_local_wall(dt_utc: datetime, zone_offset: str | None, fallback_iana: str) -> datetime:
    """Convert an aware UTC instant to local civil time using record offset or IANA fallback."""
    utc = dt_utc.astimezone(timezone.utc)
    fixed = zone_offset_to_fixed_tz(zone_offset)
    if fixed is not None:
        return utc.astimezone(fixed)
    return utc.astimezone(ZoneInfo(fallback_iana))


def format_time_ampm(local_dt: datetime) -> str:
    """Format a local datetime as 12-hour clock, e.g. 7:30 PM."""
    h24 = local_dt.hour
    minute = local_dt.minute
    ap = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{minute:02d} {ap}"


def local_time_fields_for_range(
    start_iso: str | None,
    end_iso: str | None,
    zone_offset: str | None,
    fallback_iana: str,
) -> dict[str, str | None]:
    """Build start_local, end_local, local_start_time, local_end_time for LLM-friendly narration.

    start_iso/end_iso should be normalized ISO strings (e.g. from normalize_datetime).
    When zone_offset is absent, fallback_iana is used (typically settings.user_local_timezone).
    """
    out: dict[str, str | None] = {
        "start_local": None,
        "end_local": None,
        "local_start_time": None,
        "local_end_time": None,
    }
    start_utc = parse_instant_to_utc(start_iso)
    end_utc = parse_instant_to_utc(end_iso)
    if start_utc:
        loc = to_local_wall(start_utc, zone_offset, fallback_iana)
        out["start_local"] = loc.isoformat()
        out["local_start_time"] = format_time_ampm(loc)
    if end_utc:
        loc_e = to_local_wall(end_utc, zone_offset, fallback_iana)
        out["end_local"] = loc_e.isoformat()
        out["local_end_time"] = format_time_ampm(loc_e)
    return out
