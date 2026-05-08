"""Tests for Hevy workout sync and normalization."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.database import DbSession
from app.services.providers.hevy.workouts import HevyWorkouts


@pytest.fixture
def hevy_workouts() -> HevyWorkouts:
    return HevyWorkouts(
        workout_repo=MagicMock(),
        connection_repo=MagicMock(),
        provider_name="hevy",
        api_base_url="https://api.hevyapp.com",
        oauth=None,
    )


def test_get_workouts_filters_by_date_range(hevy_workouts: HevyWorkouts, db: DbSession) -> None:
    """Should request paginated workouts and keep only those in the date window."""
    user_id = uuid4()
    start = datetime(2024, 6, 1, tzinfo=timezone.utc)
    end = datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

    page_one = {
        "page": 1,
        "page_count": 2,
        "workouts": [
            {
                "id": "w-in",
                "title": "Inside",
                "start_time": "2024-06-15T10:00:00Z",
                "end_time": "2024-06-15T11:00:00Z",
                "exercises": [],
            },
            {
                "id": "w-out",
                "title": "Outside",
                "start_time": "2024-05-01T10:00:00Z",
                "end_time": "2024-05-01T11:00:00Z",
                "exercises": [],
            },
        ],
    }
    page_two = {"page": 2, "page_count": 2, "workouts": []}

    hevy_workouts._make_api_request = MagicMock(side_effect=[page_one, page_two])  # type: ignore[method-assign]

    result = hevy_workouts.get_workouts(db, user_id, start, end)

    assert len(result) == 1
    assert result[0]["id"] == "w-in"
    assert hevy_workouts._make_api_request.call_count == 2


def test_normalize_workout_maps_external_id(hevy_workouts: HevyWorkouts) -> None:
    user_id = uuid4()
    raw = {
        "id": "abc-123",
        "title": "Push day",
        "start_time": "2024-06-10T12:00:00Z",
        "end_time": "2024-06-10T13:30:00Z",
        "description": "Chest focus",
        "routine_id": "routine-1",
        "exercises": [
            {
                "title": "Bench Press",
                "notes": "Pause reps",
                "sets": [
                    {
                        "set_type": "normal",
                        "weight_kg": 80.0,
                        "reps": 8,
                        "rpe": 7.5,
                    }
                ],
            }
        ],
    }

    record, detail = hevy_workouts._normalize_workout(raw, user_id)

    assert record.external_id == "abc-123"
    assert record.source == "hevy"
    assert record.user_id == user_id
    assert detail.record_id == record.id
    assert detail.moving_time_seconds == 5400
    assert detail.provider_extensions is not None
    assert detail.provider_extensions["hevy"] == raw
    assert detail.provider_extensions["hevy"]["exercises"][0]["title"] == "Bench Press"
