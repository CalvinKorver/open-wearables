"""Construct the Open Wearables FastMCP server (stdio, bearer HTTP, or OAuth HTTP)."""

import logging
from datetime import date

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.oauth_setup import create_oauth_provider
from app.prompts import prompts_router
from app.tools.activity import activity_router
from app.tools.sleep import sleep_router
from app.tools.timeseries import timeseries_router
from app.tools.users import users_router
from app.tools.workouts import workouts_router

logger = logging.getLogger(__name__)


def _server_instructions() -> str:
    return f"""
    Today's date is {date.today().isoformat()}.

    Enables the model to query data describing user health states and general wellness metrics.
    Data is acquired from users' wearable devices (Garmin, Whoop, Polar, Suunto, etc.),
    covering all user-connected devices and providers, aggregated into a single unified format.

    Available tools:
    - get_users: Discover users accessible via your API key
    - get_activity_summary: Get daily activity data (steps, calories, heart rate, intensity minutes)
    - get_sleep_summary: Get sleep data for a user over a specified time period
    - get_workout_events: Get workout/exercise data for a user over a specified time period
    - get_timeseries: Get granular time-series samples (e.g. weight, SpO2, HRV, intraday heart rate)

    Available prompts:
    - present_health_data: Guidelines for formatting health data for human readability

    Workflow:
    1. If you don't know the user's ID, call get_users first to discover available users
    2. Select the appropriate user:
       - If only ONE user is returned: use that user automatically (personal API key)
       - If MULTIPLE users and query says "my" or "me": ask which user they mean
       - If MULTIPLE users with a name hint (e.g., "John's workouts"): match by name
    3. Determine the date range:
       - If user specifies a time period: calculate the appropriate start_date and end_date
       - If NO time period specified: default to the last 2 weeks (start_date = 14 days ago, end_date = today)
    4. Use the user's ID to query their health data with the appropriate tool
    5. Present the data in a human-friendly format, highlighting key insights

    The API key determines which users you can access (personal, team, or enterprise scope).
    All data is returned in a normalized format regardless of the original wearable provider.
    """


def _resolve_http_auth() -> AuthProvider | None:
    if settings.mcp_auth_mode == "oauth":
        return create_oauth_provider()
    return None


def create_mcp_server() -> FastMCP:
    """Create a configured FastMCP instance with tools, prompts, and optional OAuth."""
    auth = _resolve_http_auth()
    server = FastMCP(
        "open-wearables",
        instructions=_server_instructions(),
        auth=auth,
    )

    server.mount(users_router)
    server.mount(activity_router)
    server.mount(sleep_router)
    server.mount(workouts_router)
    server.mount(timeseries_router)
    server.mount(prompts_router)

    @server.custom_route("/health", methods=["GET"])
    async def health_check(_request: Request) -> Response:
        """Liveness probe without authentication."""
        return JSONResponse({"status": "ok"})

    @server.custom_route("/", methods=["GET"])
    async def root_health(_request: Request) -> Response:
        """Minimal probe for platforms that default health checks to GET /."""
        return JSONResponse({"status": "ok"})

    logger.info(
        "Open Wearables MCP initialized. API URL: %s, HTTP auth mode: %s",
        settings.open_wearables_api_url,
        settings.mcp_auth_mode,
    )
    return server
