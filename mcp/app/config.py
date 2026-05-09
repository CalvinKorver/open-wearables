"""Configuration settings for Open Wearables MCP server."""

import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """MCP server configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / "config" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required settings
    open_wearables_api_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for Open Wearables backend API",
    )
    open_wearables_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="API key for authenticating with Open Wearables backend",
    )

    user_local_timezone: str = Field(
        default="America/Los_Angeles",
        description=(
            "IANA timezone used for start_local/end_local when a record has no zone_offset "
            "(match Coach BRIEFING_TIMEZONE when both are deployed for the same user)"
        ),
        validation_alias=AliasChoices(
            "USER_LOCAL_TIMEZONE",
            "BRIEFING_TIMEZONE",
        ),
    )

    # Optional settings
    log_level: str = Field(default="INFO", description="Logging level")
    request_timeout: int = Field(default=30, description="HTTP request timeout in seconds")

    @field_validator("user_local_timezone")
    @classmethod
    def validate_user_local_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Unknown timezone: {v}") from e
        return v

    def is_configured(self) -> bool:
        """Check if the API key is configured."""
        return bool(self.open_wearables_api_key.get_secret_value())


try:
    settings = Settings()
    if not settings.is_configured():
        print(
            f"Warning: OPEN_WEARABLES_API_KEY not set. Expected .env file at: {Settings.model_config.get('env_file')}",
            file=sys.stderr,
        )
except ValidationError as e:
    print(f"Configuration error: {e}", file=sys.stderr)
    settings = Settings(open_wearables_api_key=SecretStr(""))
