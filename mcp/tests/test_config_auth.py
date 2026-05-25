"""Tests for MCP HTTP auth configuration."""

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from app.config import Settings


class _TestSettings(Settings):
    """Settings without loading the project .env file."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def test_bearer_mode_requires_token() -> None:
    with pytest.raises(ValidationError, match="MCP_BEARER_TOKEN"):
        _TestSettings(
            mcp_transport="streamable-http",
            mcp_auth_mode="bearer",
            mcp_bearer_token="",
            open_wearables_api_key="sk-test",
        )


def test_oauth_mode_requires_https_base_url_and_github() -> None:
    with pytest.raises(ValidationError, match="MCP_PUBLIC_BASE_URL"):
        _TestSettings(
            mcp_transport="streamable-http",
            mcp_auth_mode="oauth",
            mcp_public_base_url="",
            open_wearables_api_key="sk-test",
        )

    with pytest.raises(ValidationError, match="HTTPS"):
        _TestSettings(
            mcp_transport="streamable-http",
            mcp_auth_mode="oauth",
            mcp_public_base_url="http://localhost:8765",
            mcp_github_client_id="id",
            mcp_github_client_secret="secret",
            open_wearables_api_key="sk-test",
        )

    with pytest.raises(ValidationError, match="MCP_GITHUB"):
        _TestSettings(
            mcp_transport="streamable-http",
            mcp_auth_mode="oauth",
            mcp_public_base_url="https://mcp.example.com",
            open_wearables_api_key="sk-test",
        )


def test_oauth_mode_valid() -> None:
    s = _TestSettings(
        mcp_transport="streamable-http",
        mcp_auth_mode="oauth",
        mcp_public_base_url="https://mcp.example.com",
        mcp_github_client_id="gh-id",
        mcp_github_client_secret="gh-secret",
        open_wearables_api_key="sk-test",
    )
    assert s.mcp_auth_mode == "oauth"
