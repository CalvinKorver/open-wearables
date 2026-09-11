"""Tests for bearer streamable HTTP MCP app (Claude Managed Agents)."""

from typing import Any

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient

from app.bearer_auth import MCPBearerAuthMiddleware

_BEARER_TOKEN = "test-bearer-secret"


def _mcp_app(*, stateless_http: bool) -> Any:
    server = FastMCP("open-wearables-test")

    @server.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    app = server.http_app(path="/mcp", stateless_http=stateless_http)
    app.add_middleware(MCPBearerAuthMiddleware, bearer_token=_BEARER_TOKEN)
    return app


def _bearer_app() -> TestClient:
    return TestClient(_mcp_app(stateless_http=False), raise_server_exceptions=False)


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


def _mcp_json_headers(**extra: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_BEARER_TOKEN}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        **extra,
    }


def test_stale_session_returns_400_when_stateful() -> None:
    """Railway App Sleep drops in-memory sessions; Anthropic retries the old id."""
    with TestClient(_mcp_app(stateless_http=False), raise_server_exceptions=False) as client:
        response = client.post(
            "/mcp",
            headers=_mcp_json_headers(**{"mcp-session-id": "02fc0b6b750f4ffe98e69948e2a01ecf"}),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert response.status_code == 400
    assert "session" in response.text.lower()


def test_stale_session_does_not_400_when_stateless() -> None:
    with TestClient(_mcp_app(stateless_http=True), raise_server_exceptions=False) as client:
        response = client.post(
            "/mcp",
            headers=_mcp_json_headers(**{"mcp-session-id": "02fc0b6b750f4ffe98e69948e2a01ecf"}),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert response.status_code != 400
