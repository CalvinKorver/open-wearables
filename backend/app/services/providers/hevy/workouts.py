from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from app.database import DbSession
from app.schemas.enums import WorkoutType
from app.schemas.model_crud.activities import (
    EventRecordCreate,
    EventRecordDetailCreate,
    EventRecordMetrics,
)
from app.services.event_record_service import event_record_service
from app.services.providers.templates.base_workouts import BaseWorkoutsTemplate
from app.utils.structured_logging import log_structured

HEVY_MAX_PAGES = 500
HEVY_PAGE_SIZE = 10


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class HevyWorkouts(BaseWorkoutsTemplate):
    """Fetch Hevy strength workouts via API key and map to event records."""

    def get_workouts(
        self,
        db: DbSession,
        user_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> list[Any]:
        collected: list[dict[str, Any]] = []
        page = 1
        while page <= HEVY_MAX_PAGES:
            try:
                response = self._make_api_request(
                    db,
                    user_id,
                    "/v1/workouts",
                    params={"page": page, "pageSize": HEVY_PAGE_SIZE},
                )
            except Exception as e:
                log_structured(
                    self.logger,
                    "error",
                    "Error fetching Hevy workouts page",
                    provider="hevy",
                    action="hevy_fetch_page_error",
                    page=page,
                    user_id=str(user_id),
                    error=str(e),
                )
                if collected:
                    log_structured(
                        self.logger,
                        "warning",
                        "Returning partial Hevy workout data due to error",
                        provider="hevy",
                        action="hevy_partial_data",
                        count=len(collected),
                        user_id=str(user_id),
                        error=str(e),
                    )
                    break
                raise

            if not isinstance(response, dict):
                break

            workouts = response.get("workouts")
            if not isinstance(workouts, list):
                break

            for raw in workouts:
                if isinstance(raw, dict):
                    start = _parse_iso_datetime(raw.get("start_time"))
                    if start is None:
                        continue
                    if start_date <= start <= end_date:
                        collected.append(raw)

            page_count = int(response.get("page_count") or 1)
            if page >= page_count:
                break
            page += 1

        return collected

    def _normalize_workout(
        self,
        raw_workout: dict[str, Any],
        user_id: UUID,
    ) -> tuple[EventRecordCreate, EventRecordDetailCreate]:
        workout_id = uuid4()
        start = _parse_iso_datetime(raw_workout.get("start_time"))
        if start is None:
            start = datetime.now(timezone.utc)
        end = _parse_iso_datetime(raw_workout.get("end_time"))
        if end is None or end < start:
            end = start + timedelta(hours=1)

        duration_seconds = max(1, int((end - start).total_seconds()))
        metrics: EventRecordMetrics = {"moving_time_seconds": duration_seconds}
        title_raw = raw_workout.get("title")
        title = title_raw.strip() if isinstance(title_raw, str) and title_raw.strip() else "Hevy workout"
        external = raw_workout.get("id")
        external_id = str(external) if external is not None else None

        record = EventRecordCreate(
            category="workout",
            type=WorkoutType.STRENGTH_TRAINING.value,
            source_name=title[:120],
            device_model="Hevy",
            duration_seconds=duration_seconds,
            start_datetime=start,
            end_datetime=end,
            zone_offset=None,
            id=workout_id,
            external_id=external_id,
            source="hevy",
            user_id=user_id,
        )

        detail = EventRecordDetailCreate(
            record_id=workout_id,
            **metrics,
            provider_extensions={"hevy": dict(raw_workout)},
        )
        return record, detail

    def load_data(
        self,
        db: DbSession,
        user_id: UUID,
        **kwargs: Any,
    ) -> int:
        start = kwargs.get("start") or kwargs.get("start_date")
        end = kwargs.get("end") or kwargs.get("end_date")

        if not start:
            start_dt = datetime.now(timezone.utc) - timedelta(days=30)
        elif isinstance(start, datetime):
            start_dt = start
        elif isinstance(start, str):
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        else:
            start_dt = datetime.now(timezone.utc) - timedelta(days=30)

        if not end:
            end_dt = datetime.now(timezone.utc)
        elif isinstance(end, datetime):
            end_dt = end
        elif isinstance(end, str):
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        else:
            end_dt = datetime.now(timezone.utc)

        raw_workouts = self.get_workouts(db, user_id, start_dt, end_dt)
        count = 0
        for raw in raw_workouts:
            if not isinstance(raw, dict):
                continue
            try:
                record, detail = self._normalize_workout(raw, user_id)
            except Exception as e:
                log_structured(
                    self.logger,
                    "warning",
                    "Failed to normalize Hevy workout",
                    provider="hevy",
                    action="hevy_normalize_error",
                    user_id=str(user_id),
                    error=str(e),
                )
                continue
            created_record = event_record_service.create(db, record)
            detail_for_record = detail.model_copy(update={"record_id": created_record.id})
            event_record_service.create_detail(db, detail_for_record)
            count += 1

        return count
