"""Tests for bearer streamable HTTP MCP app (Claude Managed Agents)."""

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

from app.bearer_auth import MCPBearerAuthMiddleware

_BEARER_TOKEN = "test-bearer-secret"


def _bearer_app() -> TestClient:
    server = FastMCP("open-wearables-test")

    @server.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    app = server.http_app(path="/mcp")
    app.add_middleware(MCPBearerAuthMiddleware, bearer_token=_BEARER_TOKEN)
    return TestClient(app, raise_server_exceptions=False)


def test_health_unauthenticated() -> None:
    client = _bearer_app()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_requires_bearer() -> None:
    client = _bearer_app()
    response = client.get("/mcp")
    assert response.status_code == 401


def test_mcp_accepts_valid_bearer() -> None:
    client = _bearer_app()
    response = client.get("/mcp", headers={"Authorization": f"Bearer {_BEARER_TOKEN}"})
    assert response.status_code != 401
