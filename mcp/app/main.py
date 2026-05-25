"""Open Wearables MCP Server - Main entry point."""

import logging

from app.config import settings
from app.server_factory import create_mcp_server

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

mcp = create_mcp_server()


def main() -> None:
    """Entry point for the MCP server (stdio by default; streamable-http when configured)."""
    if settings.mcp_transport == "streamable-http":
        from app.http_server import run_streamable_http_server

        run_streamable_http_server(mcp)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
