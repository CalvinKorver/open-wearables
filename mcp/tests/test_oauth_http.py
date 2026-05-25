"""Tests for OAuth streamable HTTP MCP app (Claude custom connector)."""

from fastmcp import FastMCP
from fastmcp.server.auth.providers.github import GitHubProvider
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.testclient import TestClient


def _oauth_app() -> TestClient:
    auth = GitHubProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",
        base_url="https://mcp.example.com",
    )
    server = FastMCP("open-wearables-test", auth=auth)

    @server.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    app = server.http_app(path="/mcp")
    return TestClient(app, raise_server_exceptions=False)


def test_health_unauthenticated() -> None:
    client = _oauth_app()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_requires_auth() -> None:
    client = _oauth_app()
    response = client.get("/mcp")
    assert response.status_code == 401


def test_protected_resource_metadata() -> None:
    client = _oauth_app()
    response = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == "https://mcp.example.com/mcp"
    assert body["authorization_servers"]
