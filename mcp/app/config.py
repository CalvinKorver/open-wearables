"""Configuration settings for Open Wearables MCP server."""

import sys
from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, ValidationError, field_validator, model_validator
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

    mcp_transport: Literal["stdio", "streamable-http"] = Field(
        default="stdio",
        description="stdio for Cursor/coach subprocess MCP; streamable-http for remote HTTPS",
    )

    mcp_auth_mode: Literal["oauth", "bearer"] = Field(
        default="bearer",
        description="bearer: Managed Agents static_bearer; oauth: Claude custom connector (GitHub login)",
    )

    mcp_public_base_url: str = Field(
        default="",
        description="Public HTTPS origin for OAuth (e.g. https://mcp.example.com), no trailing slash",
    )

    mcp_github_client_id: str = Field(
        default="",
        description="GitHub OAuth App client ID (required when mcp_auth_mode=oauth)",
    )

    mcp_github_client_secret: SecretStr = Field(
        default=SecretStr(""),
        description="GitHub OAuth App client secret (required when mcp_auth_mode=oauth)",
    )

    mcp_jwt_signing_key: SecretStr = Field(
        default=SecretStr(""),
        description="Optional stable JWT signing key for OAuth tokens across restarts (Fernet-safe random string)",
    )

    mcp_http_host: str = Field(
        default="0.0.0.0",
        description="Bind address for streamable HTTP MCP",
    )

    mcp_http_port: int = Field(
        default=8765,
        description="Listen port when PORT env is unset (Railway sets PORT)",
    )

    mcp_http_path: str = Field(
        default="/mcp",
        description="URL path for MCP streamable HTTP endpoint (must match vault mcp_server_url)",
    )

    mcp_bearer_token: SecretStr = Field(
        default=SecretStr(""),
        description="Bearer token for authenticating clients to streamable HTTP MCP (vault static_bearer)",
        validation_alias=AliasChoices("MCP_BEARER_TOKEN"),
    )

    # Optional settings
    log_level: str = Field(default="INFO", description="Logging level")
    request_timeout: int = Field(default=30, description="HTTP request timeout in seconds")

    @model_validator(mode="after")
    def validate_streamable_http_auth(self) -> Self:
        if self.mcp_transport != "streamable-http":
            return self

        if self.mcp_auth_mode == "bearer":
            if not self.mcp_bearer_token.get_secret_value():
                raise ValueError(
                    "MCP_BEARER_TOKEN is required when MCP_AUTH_MODE=bearer and MCP_TRANSPORT=streamable-http"
                )
            return self

        if not self.mcp_public_base_url:
            raise ValueError("MCP_PUBLIC_BASE_URL is required when MCP_AUTH_MODE=oauth (HTTPS, no trailing slash)")
        if not self.mcp_public_base_url.startswith("https://"):
            raise ValueError("MCP_PUBLIC_BASE_URL must use HTTPS for Claude OAuth discovery")
        if not self.mcp_github_client_id or not self.mcp_github_client_secret.get_secret_value():
            raise ValueError("MCP_GITHUB_CLIENT_ID and MCP_GITHUB_CLIENT_SECRET are required when MCP_AUTH_MODE=oauth")
        return self

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
