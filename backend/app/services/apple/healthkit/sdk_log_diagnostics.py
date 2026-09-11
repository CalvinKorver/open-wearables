"""Helpers to extract high-signal sync diagnostics from SDK log events.

Mobile sync UIs often report "Sync complete: 0 samples" with every data type
marked complete. That is not a backend error — it usually means HealthKit /
Samsung Health returned no new samples for the anchored query window.

These helpers surface sleep-specific counts (especially SleepAnalysis) into
structured logs so Railway / CloudWatch queries can distinguish:

1. Client found no new samples (pre-backend gap)
2. Client uploaded sleep but backend dropped / deferred it
"""

from __future__ import annotations

from typing import Any

from app.constants.series_types.sdk.category_types import AppleCategoryType
from app.schemas.providers.mobile_sdk.sdk_log_events import (
    HistoricalDataSyncStartEvent,
    HistoricalDataTypeSyncEndEvent,
    SDKLogEvent,
)

# Type strings the SDK may emit for sleep (iOS HealthKit + normalized aliases).
_SLEEP_TYPE_ALIASES: frozenset[str] = frozenset(
    {
        AppleCategoryType.SLEEP_ANALYSIS.value,
        "SleepAnalysis",
        "sleep",
        "SLEEP",
        "SLEEP_ANALYSIS",
    }
)


def _is_sleep_type(data_type: str) -> bool:
    normalized = data_type.strip()
    if normalized in _SLEEP_TYPE_ALIASES:
        return True
    lower = normalized.lower()
    return "sleep" in lower


def summarize_sdk_log_events(events: list[SDKLogEvent]) -> dict[str, Any]:
    """Build a compact diagnostic summary from SDK log events.

    Returns keys useful for structured logging / Railway filters:
    - total_samples: sum of dataTypeCounts from sync_start (0 ⇒ empty sync)
    - sleep_sample_count: sleep-related counts from sync_start
    - sleep_type_ends: per-type SleepAnalysis completion results
    - sync_time_range_*: lookback window from sync_start when present
    - zero_sample_sync: True when a sync_start reported 0 total samples
    """
    total_samples = 0
    sleep_sample_count = 0
    sleep_type_ends: list[dict[str, Any]] = []
    sync_time_range_start: str | None = None
    sync_time_range_end: str | None = None
    saw_sync_start = False

    for event in events:
        if isinstance(event, HistoricalDataSyncStartEvent):
            saw_sync_start = True
            for item in event.dataTypeCounts:
                total_samples += item.count
                if _is_sleep_type(item.type):
                    sleep_sample_count += item.count
            if event.timeRange is not None:
                sync_time_range_start = event.timeRange.startDate.isoformat()
                sync_time_range_end = event.timeRange.endDate.isoformat()
        elif isinstance(event, HistoricalDataTypeSyncEndEvent) and _is_sleep_type(event.dataType):
            sleep_type_ends.append(
                {
                    "data_type": event.dataType,
                    "success": event.success,
                    "record_count": event.recordCount,
                    "duration_ms": event.durationMs,
                }
            )

    zero_sample_sync = saw_sync_start and total_samples == 0

    return {
        "total_samples": total_samples if saw_sync_start else None,
        "sleep_sample_count": sleep_sample_count if saw_sync_start else None,
        "sleep_type_ends": sleep_type_ends,
        "sync_time_range_start": sync_time_range_start,
        "sync_time_range_end": sync_time_range_end,
        "zero_sample_sync": zero_sample_sync,
        "sleep_sync_empty": (
            zero_sample_sync
            or (saw_sync_start and sleep_sample_count == 0)
            or any(end.get("record_count") == 0 for end in sleep_type_ends)
        ),
    }
