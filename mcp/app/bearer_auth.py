"""Bearer authentication middleware for streamable HTTP MCP (e.g. Claude Managed Agents vault static_bearer)."""

import secrets
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


class MCPBearerAuthMiddleware(BaseHTTPMiddleware):
    """Require ``Authorization: Bearer <token>`` for protected paths.

    Paths ``/health`` and ``GET /`` are exempt so platform health probes work without a token.
    Managed Agents inject vault credentials when connecting to the MCP URL; Anthropic documents
    ``static_bearer`` credentials keyed by ``mcp_server_url``. This server expects a Bearer token
    matching ``MCP_BEARER_TOKEN``.
    """

    def __init__(self, app: ASGIApp, *, bearer_token: str) -> None:
        super().__init__(app)
        self._bearer_token = bearer_token

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path == "/health":
            return await call_next(request)
        if path == "/" and request.method == "GET":
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        provided = auth_header[7:].strip()
        expected = self._bearer_token
        if len(provided) != len(expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if not secrets.compare_digest(provided, expected):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return await call_next(request)
