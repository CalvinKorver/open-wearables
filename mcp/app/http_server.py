"""Streamable HTTP MCP server entry (Claude custom connector OAuth, Managed Agents bearer)."""

import asyncio
import os

from fastmcp import FastMCP
from starlette.middleware import Middleware

from app.bearer_auth import MCPBearerAuthMiddleware
from app.config import Settings, settings


def _listen_port() -> int:
    raw = os.environ.get("PORT")
    if raw:
        return int(raw)
    return settings.mcp_http_port


def run_streamable_http_server(server: FastMCP) -> None:
    """Run MCP with streamable HTTP transport."""
    middleware: list[Middleware] | None = None

    if settings.mcp_auth_mode == "bearer":
        token = settings.mcp_bearer_token.get_secret_value()
        if not token:
            env_file = Settings.model_config.get("env_file")
            raise RuntimeError(
                "MCP_BEARER_TOKEN is required when MCP_AUTH_MODE=bearer. "
                f"File is `{env_file}` — line must look like: MCP_BEARER_TOKEN=<long-random-secret> "
                "(no leading #)."
            )
        middleware = [Middleware(MCPBearerAuthMiddleware, bearer_token=token)]

    async def _serve() -> None:
        await server.run_http_async(
            transport="streamable-http",
            host=settings.mcp_http_host,
            port=_listen_port(),
            path=settings.mcp_http_path,
            middleware=middleware,
            show_banner=True,
        )

    asyncio.run(_serve())


def http_main() -> None:
    """Console script entry: ``uv run start-http``."""
    from app.main import mcp

    run_streamable_http_server(mcp)
