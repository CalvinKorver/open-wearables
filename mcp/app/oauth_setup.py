"""OAuth provider setup for Claude custom connectors (streamable HTTP)."""

from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.providers.github import GitHubProvider

from app.config import settings


def create_oauth_provider() -> AuthProvider:
    """Build the FastMCP auth provider for Claude remote MCP (GitHub OAuth proxy)."""
    client_id = settings.mcp_github_client_id
    client_secret = settings.mcp_github_client_secret.get_secret_value()
    base_url = settings.mcp_public_base_url.rstrip("/")

    kwargs: dict[str, object] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "base_url": base_url,
    }
    signing_key = settings.mcp_jwt_signing_key.get_secret_value()
    if signing_key:
        kwargs["jwt_signing_key"] = signing_key

    return GitHubProvider(**kwargs)
