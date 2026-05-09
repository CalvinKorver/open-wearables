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

    open_wearables_api_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for the Open Wearables backend API",
    )
    open_wearables_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="API key for the single user the coach acts on behalf of",
    )
    ow_user_id: str = Field(
        default="",
        description="UUID of the user the coach should brief",
    )
    ow_mcp_dir: str = Field(
        default="/opt/mcp",
        description="Path to the OW MCP server source directory (parent of pyproject.toml)",
    )

    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""),
        description="Anthropic API key",
    )
    anthropic_model: str = Field(
        default="claude-sonnet-4-5",
        description="Anthropic model to use for the agent",
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
        default="07:00",
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

    def required_missing(self) -> list[str]:
        """Return the names of required settings that are not configured."""
        missing: list[str] = []
        if not self.open_wearables_api_key.get_secret_value():
            missing.append("OPEN_WEARABLES_API_KEY")
        if not self.ow_user_id:
            missing.append("OW_USER_ID")
        if not self.anthropic_api_key.get_secret_value():
            missing.append("ANTHROPIC_API_KEY")
        if not self.telegram_bot_token.get_secret_value():
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        return missing


settings = Settings()
