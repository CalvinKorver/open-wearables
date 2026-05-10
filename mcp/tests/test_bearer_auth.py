"""Tests for MCP Bearer auth middleware."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.bearer_auth import MCPBearerAuthMiddleware


async def _echo(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def _app_with_bearer(token: str = "test-bearer-secret") -> Starlette:
    app = Starlette(
        routes=[
            Route("/health", _echo, methods=["GET"]),
            Route("/", _echo, methods=["GET"]),
            Route("/mcp", _echo, methods=["GET", "POST"]),
        ]
    )
    app.add_middleware(MCPBearerAuthMiddleware, bearer_token=token)
    return app


def test_health_exempt_without_authorization() -> None:
    client = TestClient(_app_with_bearer())
    response = client.get("/health")
    assert response.status_code == 200


def test_root_get_exempt_without_authorization() -> None:
    client = TestClient(_app_with_bearer())
    response = client.get("/")
    assert response.status_code == 200


def test_protected_path_without_authorization_returns_401() -> None:
    client = TestClient(_app_with_bearer())
    response = client.get("/mcp")
    assert response.status_code == 401


def test_protected_path_wrong_token_returns_401() -> None:
    client = TestClient(_app_with_bearer())
    response = client.get("/mcp", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_protected_path_correct_token_succeeds() -> None:
    client = TestClient(_app_with_bearer())
    response = client.get("/mcp", headers={"Authorization": "Bearer test-bearer-secret"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_case_insensitive_bearer_scheme() -> None:
    client = TestClient(_app_with_bearer())
    response = client.get("/mcp", headers={"Authorization": "bearer test-bearer-secret"})
    assert response.status_code == 200
