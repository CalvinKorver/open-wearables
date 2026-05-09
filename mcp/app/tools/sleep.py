"""MCP tools for querying sleep records."""

import logging

from fastmcp import FastMCP

from app.config import settings
from app.services.api_client import client
from app.utils import local_time_fields_for_range, normalize_datetime

logger = logging.getLogger(__name__)

# Create router for sleep-related tools
sleep_router = FastMCP(name="Sleep Tools")


@sleep_router.tool
async def get_sleep_summary(
    user_id: str,
    start_date: str,
    end_date: str,
) -> dict:
    """
    Get daily sleep summaries for a user within a date range.

    This tool retrieves daily sleep summaries including start time, end time,
    duration, and sleep stages (if available from the wearable device).

    Args:
        user_id: UUID of the user. Use get_users to discover available users.
        start_date: Start date in YYYY-MM-DD format.
                    Example: "2026-01-01"
        end_date: End date in YYYY-MM-DD format.
                  Example: "2026-01-07"

    Returns:
        A dictionary containing:
        - user: Information about the user (id, first_name, last_name)
        - period: The date range queried (start, end)
        - records: List of sleep records with date, start_datetime, end_datetime, duration
        - summary: Aggregate statistics (avg_duration, total_nights, etc.)

    Example response:
        {
            "user": {"id": "uuid-1", "first_name": "John", "last_name": "Doe"},
            "period": {"start": "2026-01-05", "end": "2026-01-12"},
            "records": [
                {
                    "date": "2026-01-11",
                    "start_datetime": "2026-01-11T23:15:00+00:00",
                    "end_datetime": "2026-01-12T07:30:00+00:00",
                    "start_local": "2026-01-11T15:15:00-08:00",
                    "end_local": "2026-01-11T23:30:00-08:00",
                    "local_start_time": "3:15 PM",
                    "local_end_time": "11:30 PM",
                    "duration_minutes": 495,
                    "source": "whoop"
                }
            ],
            "summary": {
                "total_nights": 7,
                "nights_with_data": 6,
                "avg_duration_minutes": 465,
                "min_duration_minutes": 360,
                "max_duration_minutes": 540
            }
        }

    Notes for LLMs:
        - Call get_users first to get the user_id.
        - Calculate dates based on user queries:
          "last week" → start_date = 7 days ago, end_date = today
          "January 2026" → start_date = "2026-01-01", end_date = "2026-01-31"
        - Duration is in minutes.
        - The 'date' field is based on end_datetime (when the user woke up), not when they fell asleep.
        - start_datetime and end_datetime are full ISO 8601 timestamps. Sleep typically
          spans midnight, so end_datetime is often the day after start_datetime.
        - For bedtime and wake time in the user's local clock, use start_local, end_local,
          local_start_time, and local_end_time (derived using MCP USER_LOCAL_TIMEZONE /
          BRIEFING_TIMEZONE; sleep summaries do not include per-record zone_offset).
        - The 'source' field indicates which wearable provided the data (whoop, garmin, etc.)
    """
    try:
        # Fetch user details
        try:
            user_data = await client.get_user(user_id)
            user = {
                "id": str(user_data.get("id")),
                "first_name": user_data.get("first_name"),
                "last_name": user_data.get("last_name"),
            }
        except ValueError as e:
            return {"error": f"User not found: {user_id}", "details": str(e)}

        # Fetch sleep data
        sleep_response = await client.get_sleep_summaries(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
        )

        records_data = sleep_response.get("data", [])

        # Transform records
        records = []
        durations = []

        for record in records_data:
            duration = record.get("duration_minutes")
            if duration is not None:
                durations.append(duration)

            source = record.get("source", {})
            start_n = normalize_datetime(record.get("start_time"))
            end_n = normalize_datetime(record.get("end_time"))
            local_fields = local_time_fields_for_range(
                start_n,
                end_n,
                None,
                settings.user_local_timezone,
            )
            records.append(
                {
                    "date": str(record.get("date")),
                    "start_datetime": start_n,
                    "end_datetime": end_n,
                    **local_fields,
                    "duration_minutes": duration,
                    "source": source.get("provider") if isinstance(source, dict) else source,
                }
            )

        # Calculate summary statistics
        summary = {
            "total_nights": len(records),
            "nights_with_data": len(durations),
            "avg_duration_minutes": None,
            "min_duration_minutes": None,
            "max_duration_minutes": None,
        }

        if durations:
            avg = sum(durations) / len(durations)
            summary.update(
                {
                    "avg_duration_minutes": round(avg),
                    "min_duration_minutes": min(durations),
                    "max_duration_minutes": max(durations),
                }
            )

        return {
            "user": user,
            "period": {"start": start_date, "end": end_date},
            "records": records,
            "summary": summary,
        }

    except ValueError as e:
        logger.error(f"API error in get_sleep_summary: {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.exception(f"Unexpected error in get_sleep_summary: {e}")
        return {"error": f"Failed to fetch sleep summary: {e}"}
