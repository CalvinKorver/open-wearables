"""Wrapper around fastmcp.Client that spawns the OW MCP server over stdio.

The OW MCP server is a separate package (see `mcp/` in this repo). We spawn
`uv run --directory <OW_MCP_DIR> start` as a subprocess and pass the OW API
URL + key in the child env (the MCP server reads them from its own pydantic
settings, see mcp/app/config.py).
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from app.config import settings


@dataclass(frozen=True)
class ToolSpec:
    """A single tool descriptor as advertised by the OW MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]


def _build_transport() -> StdioTransport:
    return StdioTransport(
        command="uv",
        args=["run", "--frozen", "--directory", settings.ow_mcp_dir, "start"],
        env={
            "OPEN_WEARABLES_API_URL": settings.open_wearables_api_url,
            "OPEN_WEARABLES_API_KEY": settings.open_wearables_api_key.get_secret_value(),
            "LOG_LEVEL": settings.log_level,
        },
        keep_alive=False,
    )


@asynccontextmanager
async def open_mcp_client() -> AsyncIterator["McpSession"]:
    """Spawn the OW MCP server and yield a session usable for the duration of the block."""
    transport = _build_transport()
    client = Client(transport)
    async with client:
        yield McpSession(client)


class McpSession:
    """Thin convenience wrapper around an active fastmcp.Client connection."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def list_tools(self) -> list[ToolSpec]:
        tools = await self._client.list_tools()
        specs: list[ToolSpec] = []
        for tool in tools:
            schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {}
            specs.append(
                ToolSpec(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=schema,
                )
            )
        return specs

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool by name and return its structured result.

        Falls back to text content if the tool has no output schema.
        """
        result = await self._client.call_tool(name, arguments, raise_on_error=False)
        if result.is_error:
            text = ""
            if result.content:
                first = result.content[0]
                text = getattr(first, "text", str(first))
            return {"error": text or "tool returned error"}
        if result.data is not None:
            return _ensure_dict(result.data)
        if result.structured_content is not None:
            return _ensure_dict(result.structured_content)
        if result.content:
            text = getattr(result.content[0], "text", "")
            return {"text": text}
        return {}


def _ensure_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"result": value}
