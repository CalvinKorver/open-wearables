"""Unit tests for SDK log diagnostic summaries."""

from datetime import datetime, timezone

from app.schemas.providers.mobile_sdk.sdk_log_events import (
    DeviceStateEvent,
    HistoricalDataSyncStartEvent,
    HistoricalDataTypeSyncEndEvent,
    TimeRange,
)
from app.services.apple.healthkit.sdk_log_diagnostics import summarize_sdk_log_events


def test_zero_sample_sync_detected() -> None:
    events = [
        HistoricalDataSyncStartEvent(
            eventType="historical_data_sync_start",
            timestamp=datetime(2026, 7, 19, 15, 4, 14, tzinfo=timezone.utc),
            dataTypeCounts=[
                {"type": "HKCategoryTypeIdentifierSleepAnalysis", "count": 0},
                {"type": "HKQuantityTypeIdentifierHeartRate", "count": 0},
            ],
            timeRange=TimeRange(
                startDate=datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc),
                endDate=datetime(2026, 7, 19, 15, 4, 14, tzinfo=timezone.utc),
            ),
        ),
        HistoricalDataTypeSyncEndEvent(
            eventType="historical_data_type_sync_end",
            timestamp=datetime(2026, 7, 19, 15, 4, 14, tzinfo=timezone.utc),
            dataType="SleepAnalysis",
            success=True,
            recordCount=0,
            durationMs=12,
        ),
    ]

    summary = summarize_sdk_log_events(events)

    assert summary["zero_sample_sync"] is True
    assert summary["sleep_sync_empty"] is True
    assert summary["total_samples"] == 0
    assert summary["sleep_sample_count"] == 0
    assert summary["sync_time_range_start"] is not None
    assert summary["sleep_type_ends"] == [
        {
            "data_type": "SleepAnalysis",
            "success": True,
            "record_count": 0,
            "duration_ms": 12,
        }
    ]


def test_sleep_counts_from_sync_start() -> None:
    events = [
        HistoricalDataSyncStartEvent(
            eventType="historical_data_sync_start",
            timestamp=datetime(2026, 7, 19, 15, 4, 14, tzinfo=timezone.utc),
            dataTypeCounts=[
                {"type": "sleep", "count": 12},
                {"type": "workouts", "count": 1},
            ],
        )
    ]

    summary = summarize_sdk_log_events(events)

    assert summary["zero_sample_sync"] is False
    assert summary["sleep_sync_empty"] is False
    assert summary["total_samples"] == 13
    assert summary["sleep_sample_count"] == 12


def test_device_state_only_is_not_empty_sync() -> None:
    events = [
        DeviceStateEvent(
            eventType="device_state",
            timestamp=datetime(2026, 7, 19, 15, 4, 14, tzinfo=timezone.utc),
            batteryLevel=0.6,
        )
    ]

    summary = summarize_sdk_log_events(events)

    assert summary["zero_sample_sync"] is False
    assert summary["sleep_sync_empty"] is False
    assert summary["total_samples"] is None
    assert summary["sleep_sample_count"] is None
