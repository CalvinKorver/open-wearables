"""Configuration for the Open Wearables coach service."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Coach configuration loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent / "config" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ow_user_id: str = Field(
        default="",
        description="UUID of the user the coach should brief",
    )

    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Anthropic API key",
    )
    anthropic_api_url: str = Field(
        default="https://api.anthropic.com",
        description="Anthropic API base URL",
    )
    managed_agent_id: str = Field(
        default="",
        description="Claude Managed Agent ID",
    )
    managed_environment_id: str = Field(
        default="",
        description="Claude Managed Agents environment ID",
    )
    managed_vault_ids: str = Field(
        default="",
        description="Comma-separated vault IDs made available to each managed session",
    )
    managed_memory_store_id: str = Field(
        default="",
        description="Native Anthropic memory store containing the athlete profile",
    )
    managed_agent_timeout_seconds: float = Field(
        default=300,
        gt=0,
        description="Maximum time to wait for one managed-agent turn",
    )

    telegram_bot_token: SecretStr = Field(
        default=SecretStr(""),
        description="Telegram bot token from @BotFather",
    )
    telegram_chat_id: str = Field(
        default="",
        description="Telegram chat id for the recipient",
    )

    briefing_timezone: str = Field(
        default="America/Los_Angeles",
        description="IANA timezone for scheduling the daily briefing",
    )
    briefing_time: str = Field(
        default="11:00",
        description="Local time for the daily briefing in HH:MM 24-hour format",
    )

    coach_db_path: str = Field(
        default="./coach.db",
        description="Path to the SQLite database file",
    )

    log_level: str = Field(default="INFO", description="Logging level")

    @field_validator("briefing_timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Unknown timezone: {v}") from e
        return v

    @field_validator("briefing_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError(f"BRIEFING_TIME must be HH:MM, got: {v}")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as e:
            raise ValueError(f"BRIEFING_TIME must contain integers, got: {v}") from e
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"BRIEFING_TIME out of range: {v}")
        return v

    @property
    def briefing_hour(self) -> int:
        return int(self.briefing_time.split(":")[0])

    @property
    def briefing_minute(self) -> int:
        return int(self.briefing_time.split(":")[1])

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.briefing_timezone)

    @property
    def vault_ids(self) -> list[str]:
        return [vault_id.strip() for vault_id in self.managed_vault_ids.split(",") if vault_id.strip()]

    def required_missing(self) -> list[str]:
        """Return the names of required settings that are not configured."""
        missing: list[str] = []
        if not self.ow_user_id:
            missing.append("OW_USER_ID")
        if not self.anthropic_api_key.get_secret_value():
            missing.append("ANTHROPIC_API_KEY")
        if not self.managed_agent_id:
            missing.append("MANAGED_AGENT_ID")
        if not self.managed_environment_id:
            missing.append("MANAGED_ENVIRONMENT_ID")
        if not self.vault_ids:
            missing.append("MANAGED_VAULT_IDS")
        if not self.managed_memory_store_id:
            missing.append("MANAGED_MEMORY_STORE_ID")
        if not self.telegram_bot_token.get_secret_value():
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return missing


settings = Settings()
