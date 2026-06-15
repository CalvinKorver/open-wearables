import contextlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.database import DbSession
from app.integrations.celery.tasks import sync_vendor_data
from app.models import ProviderSetting, UserConnection
from app.repositories.provider_settings_repository import ProviderSettingsRepository
from app.repositories.user_connection_repository import UserConnectionRepository
from app.schemas.auth import ConnectionStatus
from app.schemas.enums import ProviderName
from app.schemas.model_crud.user_management import (
    UserConnectionCreate,
    UserConnectionRead,
    UserConnectionWithCapabilities,
)
from app.services import ApiKeyDep, user_connection_service, user_service
from app.services.providers.factory import ProviderFactory

router = APIRouter()
factory = ProviderFactory()
provider_settings_repo = ProviderSettingsRepository()

HEVY_API_BASE = "https://api.hevyapp.com"
HEVY_INITIAL_SYNC_DAYS = 30


class HevyConnectBody(BaseModel):
    """Request body for storing a Hevy Pro API key on the user connection."""

    api_key: str = Field(..., min_length=1, description="Hevy API key from hevy.com developer settings")


def _validate_hevy_api_key(api_key: str) -> None:
    try:
        response = httpx.get(
            f"{HEVY_API_BASE}/v1/workouts/count",
            headers={"api-key": api_key.strip()},
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Hevy API key or Hevy API rejected the request",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach Hevy API: {exc}",
        ) from exc


def _with_capabilities(
    conn: object,
    settings_map: dict[str, ProviderSetting],
) -> UserConnectionWithCapabilities:
    enriched = UserConnectionWithCapabilities.model_validate(conn)
    with contextlib.suppress(ValueError):
        strategy = factory.get_provider(enriched.provider)
        caps = strategy.capabilities
        enriched.max_historical_days = caps.max_historical_days
        enriched.rest_pull = caps.rest_pull
        enriched.webhook_stream = caps.webhook_stream
        enriched.webhook_ping = caps.webhook_ping
        enriched.webhook_callback = caps.webhook_callback
        setting = settings_map.get(enriched.provider)
        enriched.live_sync_mode = (
            setting.live_sync_mode
            if (setting and setting.live_sync_mode is not None)
            else strategy.default_live_sync_mode
        )
    return enriched


@router.get("/users/{user_id}/connections", response_model=list[UserConnectionWithCapabilities])
def get_connections_endpoint(
    user_id: UUID,
    db: DbSession,
    _api_key: ApiKeyDep,
):
    """Get all connections for a user, enriched with provider capability metadata."""
    settings_map = provider_settings_repo.get_all(db)
    return [
        _with_capabilities(conn, settings_map) for conn in user_connection_service.get_connections_by_user(db, user_id)
    ]


@router.post(
    "/users/{user_id}/connections/hevy",
    response_model=UserConnectionRead,
    status_code=status.HTTP_201_CREATED,
)
def connect_hevy(
    user_id: str,
    body: HevyConnectBody,
    db: DbSession,
    _api_key: ApiKeyDep,
) -> UserConnection:
    """Store a Hevy API key for the user and queue an initial workout sync (response omits secrets)."""
    user_uuid = UUID(user_id)
    user_service.get(db, user_uuid, raise_404=True)

    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key is required")

    _validate_hevy_api_key(key)

    repo = UserConnectionRepository()
    existing = repo.get_by_user_and_provider(db, user_uuid, ProviderName.HEVY.value)
    now = datetime.now(timezone.utc)

    if existing:
        existing.access_token = key
        existing.refresh_token = None
        existing.token_expires_at = None
        existing.status = ConnectionStatus.ACTIVE
        existing.updated_at = now
        db.add(existing)
        db.commit()
        db.refresh(existing)
        connection = existing
    else:
        connection = repo.create(
            db,
            UserConnectionCreate(
                user_id=user_uuid,
                provider=ProviderName.HEVY.value,
                access_token=key,
                refresh_token=None,
                token_expires_at=None,
                status=ConnectionStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
        )

    # Match OAuth connect: backfill recent history. A live-only cursor (start=now)
    # would import zero past workouts on first connect.
    now = datetime.now(timezone.utc)
    sync_vendor_data.delay(
        user_id=str(user_uuid),
        start_date=(now - timedelta(days=HEVY_INITIAL_SYNC_DAYS)).isoformat(),
        end_date=now.isoformat(),
        providers=[ProviderName.HEVY.value],
        is_historical=True,
    )
    return connection


@router.delete("/users/{user_id}/connections/{provider}")
def disconnect_provider_endpoint(
    user_id: UUID,
    provider: ProviderName,
    db: DbSession,
    _api_key: ApiKeyDep,
) -> Response:
    """Disconnect a user from a provider, revoking the connection and clearing tokens."""
    strategy = ProviderFactory().get_provider(provider.value)
    user_connection_service.disconnect(db, user_id, provider.value, oauth=strategy.oauth)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
