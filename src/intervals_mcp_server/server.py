"""
Intervals.icu MCP Server

This module implements a Model Context Protocol (MCP) server for connecting
Claude with the Intervals.icu API. It provides tools for retrieving and managing
athlete data, including activities, events, workouts, and wellness metrics.

Main Features:
    - Activity retrieval and detailed analysis
    - Event management (races, workouts, calendar items)
    - Wellness data tracking and visualization
    - Error handling with user-friendly messages
    - Configurable parameters with environment variable support

Usage:
    This server is designed to be run as a standalone script and exposes several MCP tools
    for use with Claude Desktop or other MCP-compatible clients. The server loads configuration
    from environment variables (optionally via a .env file) and communicates with the Intervals.icu API.

    To run the server:
        $ python src/intervals_mcp_server/server.py

    MCP tools provided:
        - get_activities
        - get_activity_details
        - get_athlete
        - get_events
        - get_event_by_id
        - get_wellness_data
        - get_activity_intervals
        - add_events
        - calculate_date_info
        - get_current_date_and_time_info
        - download_workout_zwo
        - get_races
        - get_power_curves
        - get_activity_power_curves
        - get_pace_curves
        - get_activity_pace_curve
        - get_power_hr_curve
        - get_activity_power_vs_hr
        - get_activity_hr_curve

    See the README for more details on configuration and usage.
"""

import contextvars
from json import JSONDecodeError
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any
import json

import httpx  # pylint: disable=import-error
from mcp.server.mcpserver import MCPServer  # pylint: disable=import-error

from intervals_mcp_server import usage
from intervals_mcp_server.utils.filtering import (
    transform_activities,
    transform_activity_details,
    transform_activity_intervals,
    transform_athlete,
)

# Try to load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv

    _ = load_dotenv()
except ImportError:
    # python-dotenv not installed, proceed without it
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("intervals_icu_mcp_server")

# Shared httpx client, lazily (re)created if closed
httpx_client: httpx.AsyncClient | None = None


def _get_httpx_client() -> httpx.AsyncClient:
    global httpx_client  # noqa: PLW0603  # pylint: disable=global-statement
    if httpx_client is None or httpx_client.is_closed:
        httpx_client = httpx.AsyncClient()
    return httpx_client


_bearer_api_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_bearer_api_key", default=None
)


def _get_intervals_api_key() -> str | None:
    from mcp.server.auth.middleware.auth_context import get_access_token

    access_token = get_access_token()
    if access_token and hasattr(access_token, "intervals_api_key"):
        return access_token.intervals_api_key
    return _bearer_api_key.get()


def _get_intervals_athlete_id() -> str | None:
    from mcp.server.auth.middleware.auth_context import get_access_token

    access_token = get_access_token()
    if access_token and hasattr(access_token, "intervals_athlete_id"):
        return access_token.intervals_athlete_id
    return None


class BearerAuthMiddleware:
    """ASGI middleware that extracts Authorization: Bearer <key> into a context var."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth.startswith("Bearer "):
                token = _bearer_api_key.set(auth[7:])
                try:
                    return await self.app(scope, receive, send)
                finally:
                    _bearer_api_key.reset(token)
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: MCPServer):
    """Context manager to close the shared httpx client when the server stops."""
    try:
        yield
    finally:
        if httpx_client and not httpx_client.is_closed:
            await httpx_client.aclose()


def _build_auth() -> tuple[Any, dict[str, Any]]:
    """Build OAuth constructor kwargs for MCPServer when running over HTTP.

    MCP SDK 2.x only accepts auth configuration at construction time, so the
    decision has to happen at import. Auth is enabled when MCP_ISSUER_URL is
    set (Vercel) or the transport is streamable-http (local HTTP testing,
    issuer defaulting to localhost). In stdio mode (Claude Desktop) both are
    unset and the server is built without auth.

    Returns the provider instance (None when auth is disabled — the provider
    also serves the landing and credential pages) and the kwargs.
    """
    issuer_url = os.getenv("MCP_ISSUER_URL")
    if not issuer_url:
        if os.getenv("MCP_TRANSPORT") != "streamable-http":
            return None, {}
        issuer_url = f"http://localhost:{os.getenv('MCP_PORT', '8000')}"

    from intervals_mcp_server.auth import IntervalsOAuthProvider
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

    provider = IntervalsOAuthProvider()
    return provider, {
        "auth_server_provider": provider,
        "auth": AuthSettings(
            issuer_url=issuer_url,
            resource_server_url=os.getenv("MCP_RESOURCE_URL", issuer_url),
            # Our tokens are JWTs we sign ourselves (JWT_SECRET) and carry no
            # RFC 8707 resource claim, so no other server can mint one we'd
            # accept. True would reject every token we issue.
            validate_token_resource=False,
            client_registration_options=ClientRegistrationOptions(enabled=True),
        ),
    }


auth_provider, _auth_kwargs = _build_auth()

class UsageLoggingMCPServer(MCPServer):
    """MCPServer that records each tool call in the usage log (see usage.py)."""

    async def call_tool(self, name, arguments, context=None):
        await usage.record(_get_httpx_client(), _get_intervals_athlete_id(), name)
        return await super().call_tool(name, arguments, context)


# Initialize the MCP server with custom lifespan (and OAuth when over HTTP)
mcp = UsageLoggingMCPServer("intervals-icu", lifespan=lifespan, **_auth_kwargs)


async def _send_response(send, status: int, body: bytes = b"", headers=()) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-length", str(len(body)).encode()), *headers],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive):
    """Read the whole request body. Return it and a receive() that replays it."""
    messages = []
    body = b""
    while True:
        message = await receive()
        messages.append(message)
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    replay_iter = iter(messages)

    async def replay():
        try:
            return next(replay_iter)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    return body, replay


def _parse_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (JSONDecodeError, UnicodeDecodeError):
        return None


class RefuseStreamsMiddleware:
    """Answer, right away, the two MCP streams this stateless server can't use.

    The server never pushes messages, but MCP clients open two long-lived
    streams anyway: GET /mcp and POST subscriptions/listen. Both stay open
    whatever json_response says, and on Vercel each one held a function
    instance until the 300 s timeout. GET gets 405 (the spec's way to say
    "no server stream here") and listen gets a method-not-found error.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/mcp":
            return await self.app(scope, receive, send)
        if scope.get("method") == "GET":
            return await _send_response(send, 405, headers=[(b"allow", b"POST")])
        if scope.get("method") != "POST":
            return await self.app(scope, receive, send)

        body, replay = await _read_body(receive)
        payload = _parse_json(body)
        if isinstance(payload, dict) and payload.get("method") == "subscriptions/listen":
            error = {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "error": {
                    "code": -32601,
                    "message": "subscriptions/listen is not supported: this server is stateless",
                },
            }
            return await _send_response(
                send,
                200,
                json.dumps(error).encode(),
                headers=[(b"content-type", b"application/json")],
            )
        await self.app(scope, replay, send)


class RequestLoggingMiddleware:
    """Log every HTTP request when it starts and when it ends.

    Logs method, path, status, client, user agent, the referer for non-MCP
    pages, and for /mcp the JSON-RPC method and tool name from the body —
    never tool arguments, credentials, or token contents. Logging at the
    start too means a request killed by the platform timeout still leaves a
    trace.
    """

    def __init__(self, app):
        self.app = app

    @staticmethod
    def _mcp_detail(payload: Any) -> str:
        if payload is None:
            return ""
        msgs = payload if isinstance(payload, list) else [payload]
        parts = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            detail = str(m.get("method", ""))
            if detail == "tools/call":
                detail += f":{m.get('params', {}).get('name', '?')}"
            if detail:
                parts.append(detail)
        return ",".join(parts)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        method = scope.get("method", "?")
        path = scope.get("path", "?")
        client = (scope.get("client") or ("?",))[0]
        headers = dict(scope.get("headers", []))
        ua = headers.get(b"user-agent", b"").decode(errors="replace")[:80]
        referer = headers.get(b"referer", b"").decode(errors="replace")[:200]

        body, replay = await _read_body(receive)
        payload = _parse_json(body) if path == "/mcp" and body else None
        detail = self._mcp_detail(payload)
        label = f"{method} {path}{f' [{detail}]' if detail else ''}"
        status: dict[str, Any] = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        logger.info(
            "req start %s client=%s ua=%s%s",
            label,
            client,
            ua,
            f" referer={referer or '-'}" if path != "/mcp" else "",
        )
        try:
            await self.app(scope, replay, send_wrapper)
        finally:
            logger.info(
                "req done %s -> %s client=%s ua=%s",
                label,
                status.get("code", "?"),
                client,
                ua,
            )


_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_STATIC_FILES = {
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/favicon.svg": ("icon.svg", "image/svg+xml"),
    "/logo.svg": ("logo.svg", "image/svg+xml"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
}


def build_http_app():
    """Create the Streamable HTTP ASGI app with landing and credential-form routes."""
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.responses import FileResponse

    for route, (filename, media_type) in _STATIC_FILES.items():

        @mcp.custom_route(route, methods=["GET"])  # pylint: disable=cell-var-from-loop
        async def static_file(_request, filename=filename, media_type=media_type):
            return FileResponse(
                os.path.join(_STATIC_DIR, filename),
                media_type=media_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )

    if auth_provider is not None:

        @mcp.custom_route("/", methods=["GET"])
        async def landing(request):
            return await auth_provider.handle_landing_page(request)

        @mcp.custom_route("/intervals-auth", methods=["GET"])
        async def auth_page(request):
            return await auth_provider.handle_auth_page(request)

        @mcp.custom_route("/intervals-auth", methods=["POST"])
        async def auth_submit(request):
            return await auth_provider.handle_auth_submit(request)

    # json_response: answer each POST with a plain JSON body and close, instead of
    # wrapping every response in an SSE stream. The two streams it doesn't cover
    # are refused in RefuseStreamsMiddleware.
    app = RefuseStreamsMiddleware(
        mcp.streamable_http_app(
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
    )
    return RequestLoggingMiddleware(app)

# Constants
INTERVALS_API_BASE_URL = os.getenv("INTERVALS_API_BASE_URL", "https://intervals.icu/api/v1")
API_KEY = os.getenv("API_KEY", "")  # Provide default empty string
ATHLETE_ID = os.getenv("ATHLETE_ID", "")  # Default athlete ID from .env
USER_AGENT = "intervalsicu-mcp-server/1.0"

# Accept athlete IDs that are either all digits or start with 'i' followed by digits
if ATHLETE_ID and not re.fullmatch(r"i?\d+", ATHLETE_ID):
    raise ValueError(
        "ATHLETE_ID must be all digits (e.g. 123456) or start with 'i' followed by digits (e.g. i123456)"
    )


def validate_date(date_str: str) -> str:
    """Validate date string format (YYYY-MM-DD) and return it if valid."""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError as exc:
        raise ValueError("Invalid date format. Please use YYYY-MM-DD.") from exc


def _get_error_message(error_code: int, error_text: str) -> str:
    """Return a user-friendly error message for a given HTTP status code."""
    error_messages = {
        HTTPStatus.UNAUTHORIZED: f"{HTTPStatus.UNAUTHORIZED.value} {HTTPStatus.UNAUTHORIZED.phrase}: Please check your API key.",
        HTTPStatus.FORBIDDEN: f"{HTTPStatus.FORBIDDEN.value} {HTTPStatus.FORBIDDEN.phrase}: You may not have permission to access this resource.",
        HTTPStatus.NOT_FOUND: f"{HTTPStatus.NOT_FOUND.value} {HTTPStatus.NOT_FOUND.phrase}: The requested endpoint or ID doesn't exist.",
        HTTPStatus.UNPROCESSABLE_ENTITY: f"{HTTPStatus.UNPROCESSABLE_ENTITY.value} {HTTPStatus.UNPROCESSABLE_ENTITY.phrase}: The server couldn't process the request (invalid parameters or unsupported operation).",
        HTTPStatus.TOO_MANY_REQUESTS: f"{HTTPStatus.TOO_MANY_REQUESTS.value} {HTTPStatus.TOO_MANY_REQUESTS.phrase}: Too many requests in a short time period.",
        HTTPStatus.INTERNAL_SERVER_ERROR: f"{HTTPStatus.INTERNAL_SERVER_ERROR.value} {HTTPStatus.INTERNAL_SERVER_ERROR.phrase}: The Intervals.icu server encountered an internal error.",
        HTTPStatus.SERVICE_UNAVAILABLE: f"{HTTPStatus.SERVICE_UNAVAILABLE.value} {HTTPStatus.SERVICE_UNAVAILABLE.phrase}: The Intervals.icu server might be down or undergoing maintenance.",
    }
    try:
        status = HTTPStatus(error_code)
        return error_messages.get(status, error_text)
    except ValueError:
        return error_text


async def make_intervals_request(
    url: str,
    api_key: str | None = None,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    raw_response: bool = False,
) -> dict[str, Any] | list[dict[str, Any]] | str:
    """
    Make a request to the Intervals.icu API with proper error handling.

    Args:
        url (str): The API endpoint path (e.g., '/athlete/{id}/activities').
        api_key (str | None): Optional API key to use for authentication. Defaults to the global API_KEY.
        params (dict[str, Any] | None): Optional query parameters for the request.
        method (str): HTTP method to use (GET, POST, etc.). Defaults to GET.
        data (dict[str, Any] | None): Optional data to send in the request body.

    Returns:
        dict[str, Any] | list[dict[str, Any]]: The parsed JSON response from the API, or an error dict.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    has_body = method in ["POST", "PUT"]

    if has_body:
        headers["Content-Type"] = "application/json"

    # Use provided api_key, then token from auth context, then env var
    key_to_use = api_key if api_key is not None else _get_intervals_api_key() or API_KEY
    if not key_to_use:
        logger.error("No API key provided for request to: %s", url)
        return {
            "error": True,
            "message": "API key is required. Set API_KEY env var or pass api_key",
        }

    auth = httpx.BasicAuth("API_KEY", key_to_use)
    full_url = f"{INTERVALS_API_BASE_URL}{url}"

    try:
        response = await _get_httpx_client().request(
            method=method,
            url=full_url,
            headers=headers,
            params=params,
            auth=auth,
            timeout=30.0,
            content=json.dumps(data) if has_body and data is not None else None,
        )
        if raw_response:
            return response.text
        try:
            response_data = response.json() if response.content else {}
        except JSONDecodeError:
            logger.error("Invalid JSON in response from: %s", full_url)
            return {"error": True, "message": "Invalid JSON in response"}
        _ = response.raise_for_status()
        return response_data
    except httpx.HTTPStatusError as e:
        error_code = e.response.status_code
        error_text = e.response.text

        logger.error("HTTP error: %s - %s", error_code, error_text)

        return {
            "error": True,
            "status_code": error_code,
            "message": _get_error_message(error_code, error_text),
        }
    except httpx.RequestError as e:
        logger.error("Request error: %s", str(e))
        return {"error": True, "message": f"Request error: {str(e)}"}
    except httpx.HTTPError as e:
        logger.error("HTTP client error: %s", str(e))
        return {"error": True, "message": f"HTTP client error: {str(e)}"}


# ----- MCP Tool Implementations ----- #


def _parse_activities_from_result(result: Any) -> list[dict[str, Any]]:
    """Extract a list of activity dictionaries from the API result."""
    activities: list[dict[str, Any]] = []

    if isinstance(result, list):
        activities = [item for item in result if isinstance(item, dict)]
    elif isinstance(result, dict):
        # Result is a single activity or a container
        for _key, value in result.items():
            if isinstance(value, list):
                activities = [item for item in value if isinstance(item, dict)]
                break
        # If no list was found but the dict has typical activity fields, treat it as a single activity
        if not activities and any(key in result for key in ["name", "startTime", "distance"]):
            activities = [result]

    return activities


def _filter_named_activities(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out unnamed activities from the list."""
    return [
        activity
        for activity in activities
        if activity.get("name") and activity.get("name") != "Unnamed"
    ]


async def _fetch_more_activities(
    athlete_id: str,
    start_date: str,
    api_key: str | None,
    api_limit: int,
) -> list[dict[str, Any]]:
    """Fetch additional activities from an earlier date range."""
    oldest_date = datetime.fromisoformat(start_date)
    older_start_date = (oldest_date - timedelta(days=60)).strftime("%Y-%m-%d")
    older_end_date = (oldest_date - timedelta(days=1)).strftime("%Y-%m-%d")

    if older_start_date >= older_end_date:
        return []

    more_params = {
        "oldest": older_start_date,
        "newest": older_end_date,
        "limit": api_limit,
    }
    more_result = await make_intervals_request(
        url=f"/athlete/{athlete_id}/activities",
        api_key=api_key,
        params=more_params,
    )

    if isinstance(more_result, list):
        return _filter_named_activities(more_result)
    return []


@mcp.tool()
async def get_activities(  # pylint: disable=too-many-arguments,too-many-return-statements,too-many-branches,too-many-positional-arguments
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
    include_unnamed: bool = False,
) -> list[dict] | str:
    """Get a list of activities for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to 30 days ago)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)
        limit: Maximum number of activities to return (optional, defaults to 10)
        include_unnamed: Whether to include unnamed activities (optional, defaults to False)

    `interval_summary` is Intervals' auto-grouping, NOT the workout's real
    splits: `11x 490m 2:22` can be ten 500s re-chunked, and the uniform pace
    it shows is an artefact of the grouping. Never read pacing evenness or
    compliance off it — call get_activity_intervals for the actual splits.

    An activity's top-level `moving_time` excludes pauses the device detected
    inside each interval, while the per-interval times from
    get_activity_intervals are wall-to-wall. The two yield different paces
    for the same session; state which one you used.

    Returns:
        List of activity dictionaries or error message
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Parse date parameters
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # Fetch more activities if we need to filter out unnamed ones
    api_limit = limit * 3 if not include_unnamed else limit

    # Call the Intervals.icu API
    params = {"oldest": start_date, "newest": end_date, "limit": api_limit}
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/activities", api_key=api_key, params=params
    )

    # Check for error
    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching activities: {error_message}"

    if not result:
        return f"No activities found for athlete {athlete_id_to_use} in the specified date range."

    # Parse activities from result
    activities = _parse_activities_from_result(result)

    if not activities:
        return f"No valid activities found for athlete {athlete_id_to_use} in the specified date range."

    # Filter and fetch more if needed
    if not include_unnamed:
        activities = _filter_named_activities(activities)

        # If we don't have enough named activities, try to fetch more
        if len(activities) < limit:
            more_activities = await _fetch_more_activities(
                athlete_id_to_use, start_date, api_key, api_limit
            )
            activities.extend(more_activities)

    # Limit to requested count
    activities = activities[:limit]

    return transform_activities(activities)


@mcp.tool()
async def get_activity_details(activity_id: str, api_key: str | None = None) -> dict | str:
    """Get detailed information for a specific activity from Intervals.icu

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)

    Returns:
        Dictionary containing activity details or error message
    """
    # Call the Intervals.icu API
    result = await make_intervals_request(url=f"/activity/{activity_id}", api_key=api_key)

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching activity details: {error_message}"

    # Format the response
    if not result:
        return f"No details found for activity {activity_id}."

    # If result is a list, use the first item if available
    activity_data = result[0] if isinstance(result, list) and result else result
    if not isinstance(activity_data, dict):
        return f"Invalid activity format for activity {activity_id}."

    return transform_activity_details(activity_data)


@mcp.tool()
async def get_activity_intervals(activity_id: str, api_key: str | None = None) -> dict | str:
    """Get interval data for a specific activity from Intervals.icu

    This endpoint returns detailed metrics for each interval in an activity, including power, heart rate,
    cadence, speed, and environmental data. It also includes grouped intervals if applicable.

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)

    `icu_groups` is Intervals' auto-grouping (the same one get_activities
    shows as `interval_summary`), NOT the workout's real splits:
    `11x 490m 2:22` can be ten 500s re-chunked, and the uniform pace it
    shows is an artefact of the grouping. Never read pacing evenness or
    compliance off it — use `icu_intervals` for the actual splits.

    An activity's top-level `moving_time` (from get_activities) excludes
    pauses the device detected inside each interval, while the per-interval
    times here are wall-to-wall. The two yield different paces for the same
    session; state which one you used.

    In pool swims a rest ends when its timer does: time spent at the wall
    after that (breathing, drinking, adjusting a Tempo Trainer) is counted
    in the next interval, so interval paces come out slower than the
    swimming itself. That is why a rest that ends on the lap button
    (`Press lap`, see add_or_update_event) is often the better choice: the
    next interval then starts when the athlete actually pushes off.

    Returns:
        Dictionary containing interval data or error message
    """
    # Get activity details to determine activity type for proper formatting
    activity_details = await get_activity_details(activity_id, api_key)
    if isinstance(activity_details, str):
        return activity_details
    activity_type = activity_details.get("type", "")
    # Call the Intervals.icu API
    result = await make_intervals_request(url=f"/activity/{activity_id}/intervals", api_key=api_key)

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching intervals: {error_message}"

    # Format the response
    if not result:
        return f"No interval data found for activity {activity_id}."

    # If the result is empty or doesn't contain expected fields
    if not isinstance(result, dict) or not any(
        key in result for key in ["icu_intervals", "icu_groups"]
    ):
        return f"No interval data or unrecognized format for activity {activity_id}."

    return transform_activity_intervals(result, activity_type)


@mcp.tool()
async def get_activity_messages(activity_id: str, api_key: str | None = None) -> list | str:
    """Get messages (notes/comments) for a specific activity from Intervals.icu.

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
    """
    result = await make_intervals_request(url=f"/activity/{activity_id}/messages", api_key=api_key)

    if isinstance(result, dict) and "error" in result:
        return f"Error fetching activity messages: {result.get('message')}"

    if not result or not isinstance(result, list):
        return f"No messages found for activity {activity_id}."

    return result


@mcp.tool()
async def add_activity_message(
    activity_id: str,
    content: str,
    api_key: str | None = None,
) -> dict | str:
    """Add a message (note/comment) to an activity on Intervals.icu.

    Args:
        activity_id: The Intervals.icu activity ID
        content: The message text to add
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
    """
    result = await make_intervals_request(
        url=f"/activity/{activity_id}/messages",
        api_key=api_key,
        method="POST",
        data={"content": content},
    )

    if isinstance(result, dict) and "error" in result:
        return f"Error adding message to activity: {result.get('message')}"

    if not result or not isinstance(result, dict):
        return "Error: unexpected response when adding message."

    return result


@mcp.tool()
async def list_events(
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    limit: int = 30,
    include_shared_events: bool = True,
) -> list[dict] | str:
    """Get events for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        end_date: End date in YYYY-MM-DD format (optional, defaults to 7 days from start_date)
        category: Filter by event category (optional, e.g., "WORKOUT,RACE_A,RACE_B,RACE_C")
        limit: Maximum number of events to return (optional, defaults to 30)
        include_shared_events: If True, fetch and include shared event data for events with shared_event_id (optional, defaults to True)

    Returns:
        List of event dictionaries or error message
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Use existing format parameter to ensure JSON output
    format_param = ""

    # Build query parameters
    params = {}
    if start_date:
        params["oldest"] = start_date
    if end_date:
        params["newest"] = end_date
    if category:
        params["category"] = category
    if limit:
        params["limit"] = limit

    # Call the Intervals.icu API using the existing helper function
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/events{format_param}",
        api_key=api_key,
        params=params,
    )

    # Handle potential errors
    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching events: {error_message}"

    # Process and format the events for better readability
    if isinstance(result, list):
        # Fetch shared event data if requested
        if include_shared_events:
            for event in result:
                if not isinstance(event, dict):
                    continue
                if shared_event_id := event.get("shared_event_id"):
                    shared_event = await make_intervals_request(
                        url=f"/shared-event/{shared_event_id}", api_key=api_key
                    )
                    if isinstance(shared_event, dict):
                        event["shared_event"] = shared_event
        return result

    return "No events found or invalid response format"


@mcp.tool()
async def get_event_by_id(
    event_id: str,
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> dict | str:
    """Get detailed information for a specific event from Intervals.icu

    Args:
        event_id: The Intervals.icu event ID
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)

    Returns:
        Dictionary containing event details or error message
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Call the Intervals.icu API
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/events/{event_id}", api_key=api_key
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching event details: {error_message}"

    # Format the response
    if not result:
        return f"No details found for event {event_id}."

    if not isinstance(result, dict):
        return f"Invalid event format for event {event_id}."

    return result


@mcp.tool()
async def get_wellness_data(
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict | list | str:
    """Get wellness data for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to 30 days ago)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)

    Returns:
        Dictionary or list containing wellness data, or error message
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Parse date parameters
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # Call the Intervals.icu API
    params = {"oldest": start_date, "newest": end_date}

    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/wellness", api_key=api_key, params=params
    )

    if isinstance(result, dict) and "error" in result:
        return f"Error fetching wellness data: {result.get('message')}"

    # Format the response
    if not result:
        return (
            f"No wellness data found for athlete {athlete_id_to_use} in the specified date range."
        )

    return result


def _resolve_workout_type(name: str | None, workout_type: str | None) -> str:
    """Determine the workout type based on the name and provided value."""
    if workout_type:
        return workout_type
    name_lower = name.lower() if name else ""
    mapping = [
        ("Ride", ["bike", "cycle", "cycling", "ride"]),
        ("Run", ["run", "running", "jog", "jogging"]),
        ("Swim", ["swim", "swimming", "pool"]),
        ("Walk", ["walk", "walking", "hike", "hiking"]),
        ("Row", ["row", "rowing"]),
    ]
    for workout, keywords in mapping:
        if any(keyword in name_lower for keyword in keywords):
            return workout
    return "Ride"  # Default


@mcp.tool()
async def delete_event(
    event_id: str,
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> str:
    """Delete event for an athlete from Intervals.icu
    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        event_id: The Intervals.icu event ID
    """
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."
    if not event_id:
        return "Error: No event ID provided."
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/events/{event_id}", api_key=api_key, method="DELETE"
    )
    if isinstance(result, dict) and "error" in result:
        return f"Error deleting event: {result.get('message')}"
    return json.dumps(result, indent=2)


@mcp.tool()
async def delete_events_by_date_range(
    start_date: str,
    end_date: str,
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> str:
    """Delete events for an athlete from Intervals.icu in the specified date range.

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."
    params = {"oldest": validate_date(start_date), "newest": validate_date(end_date)}
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/events", api_key=api_key, params=params
    )
    if isinstance(result, dict) and "error" in result:
        return f"Error deleting events: {result.get('message')}"
    events = result if isinstance(result, list) else []
    failed_events = []
    for event in events:
        result = await make_intervals_request(
            url=f"/athlete/{athlete_id_to_use}/events/{event.get('id')}",
            api_key=api_key,
            method="DELETE",
        )
        if isinstance(result, dict) and "error" in result:
            failed_events.append(event.get("id"))
    return f"Deleted {len(events) - len(failed_events)} events. Failed to delete {len(failed_events)} events: {failed_events}"


@mcp.tool()
async def add_or_update_event(  # pylint: disable=locally-disabled, too-many-arguments, too-many-positional-arguments
    workout_type: str,
    name: str,
    description: str | None = None,
    athlete_id: str | None = None,
    api_key: str | None = None,
    event_id: str | None = None,
    start_date: str | None = None,
    moving_time: int | None = None,
    distance: int | None = None,
) -> str:
    """Create or update a planned workout on the Intervals.icu calendar.

    If event_id is given the event is updated in place, otherwise created.

    Args:
        workout_type: Workout type (Ride, Run, Swim, Walk, Row, VirtualRide, VirtualRun)
        name: Name of the workout
        description: Workout steps in Intervals.icu native text format (see STEP FORMAT below)
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        event_id: The Intervals.icu event ID (optional, for updates)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        moving_time: Total expected moving time of the workout in seconds (optional; the saved duration comes from the parsed steps)
        distance: Total expected distance of the workout in meters (optional)

    ALWAYS VERIFY THE RESULT. The parser never errors on a malformed step —
    it silently drops the line. After every call, compare the returned
    `workout_doc.steps` against what you sent: a step you wrote that is
    missing from `steps` did not parse, and an expected flag (e.g.
    `until_lap_press`) that is absent means the step parsed as something
    else. `workout_doc.duration` is the sum of the parsed steps and
    overrides whatever you passed as `moving_time`; if they disagree, the
    parsed steps are the truth.

    STEP FORMAT
        - <duration|distance> <intensity> [modifiers]
      Lines without a leading dash are section headers. Headers are the only
      place free text reliably survives, so put anything the athlete must
      read on screen there.

    CUE TEXT — use `<!>`
        - <cue> <!> <duration|distance> <intensity> [intensity=<type>]
      The cue MUST come before `<!>`. Text placed AFTER the intensity is
      discarded silently: `- 25s intensity=rest Wall` keeps the step but
      loses the word "Wall".

    LAP-BUTTON STEPS (wait for the athlete to press lap)
        - Press lap <duration> intensity=rest
      `Press lap` must be the FIRST thing after the dash, with NOTHING
      between it and the duration. Parses to
      `{"text": "Press lap", "duration": N, "until_lap_press": true}`.
      The duration is only a time estimate for the plan; the step ends on
      the button press.
        WRONG: `- until Press lap`                      -> line vanishes
        WRONG: `- Press lap — set watch <!> 2m ...`      -> plain rest, no flag
      Put the instruction in the preceding section header instead.

    DURATIONS — `m` MEANS MINUTES
        30s  5m  1h  1h30m  4m50s  10m30s
      `2h35` parses as 2h + 35 SECONDS, not 2h35m. Write `155m`.
      For distance use `mtr` or `km`: `100mtr`, `1.2km`.

    INTENSITY
        Power:  80%  200w  100-140w  Z4  ramp 50-75%
        Pace:   86% Pace  Z2 Pace        (running and swimming)
        HR:     75% HR  85% LTHR  Z2 HR
      Type:     intensity=warmup|active|rest|cooldown
      A bare `1% Pace` on a rest step still gets a tiny distance assigned
      and throws the workout total off by a metre. Omit the pace target on
      rest steps: `- 2m intensity=rest`.
      Watch ramp seams: a ramp ending at 50% followed by a step at 48%
      leaves a visible discontinuity in the chart.

    REPEATS
        Nx on its own line, then the steps. Blank line BEFORE and AFTER the
        block. No nesting.
      Where the rest sits inside the group is a real choice: rest-last ends
      the block on a rest, rest-first gives the first rep a cushion and
      avoids a dangling rest before a steady block. Follow the athlete's
      stated preference, which may differ per sport.

    SWIM WORKOUTS
      If the athlete uses a Finis Tempo Trainer, each step's cue carries the
      Tempo Trainer time per 25 m, worked out per zone as
      `<%> -> <pace per 100m> -> FTT <sec:hundredths> per 25m`.
      Take these from calculate_swim_pace, never by hand — it reads the
      athlete's live CSS, which may differ from the value a previous session
      used. Any mid-session Tempo Trainer change needs a `Press lap` stop,
      not a timed wall rest.

    DESCRIPTION TEXT
      Markdown. End every line inside a paragraph with TWO trailing spaces
      or the line breaks collapse. Keep the athlete's language and accents.
      Do not write resolved watt or pace values into the text when the steps
      are expressed in percentages — Intervals renders them beside each step
      and a hand-typed table goes stale the moment FTP or CSS changes.

    EXAMPLE (Ride)
        Warm-up
        - 10m ramp 50-75% intensity=warmup

        Main set — 4 × 5 min at threshold

        4x
        - Hold 90 rpm <!> 5m 100%
        - 3m 50% intensity=rest

        Press lap when ready to cool down
        - Press lap 2m intensity=rest
        - 10m 60% intensity=cooldown

    EXAMPLE (Swim, Tempo Trainer)
        Warm-up
        - 35:12 easy <!> 400mtr 84% Pace intensity=warmup

        Set the Tempo Trainer to 34:30, press lap to start
        - Press lap 1m intensity=rest

        Main set

        10x
        - 34:30 even pace <!> 500mtr 86% Pace intensity=active
        - Wall <!> 15s intensity=rest

        Set the Tempo Trainer to 35:12, press lap to start
        - Press lap 1m intensity=rest

        Cool-down
        - 35:12 easy choice <!> 200mtr 84% Pace intensity=cooldown

    Returns:
        A string. On success, "Successfully created event:" (or "updated")
        followed by the saved event as JSON, including `workout_doc` (the
        parsed structure), `icu_training_load`, and projected
        `icu_ctl`/`icu_atl`. Those CTL/ATL figures include
        planned-but-unexecuted work: they are projections, not the athlete's
        current form. On failure, a string starting with "Error" — check for
        it before verifying the steps.
    """
    message = None
    if not athlete_id:
        athlete_id = ATHLETE_ID
    if not athlete_id:
        message = "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."
    else:
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")
        try:
            data = {
                "start_date_local": start_date + "T00:00:00",
                "category": "WORKOUT",
                "name": name,
                "description": description,
                "type": _resolve_workout_type(name, workout_type),
                "moving_time": moving_time,
                "distance": distance,
            }
            result = await make_intervals_request(
                url=f"/athlete/{athlete_id}/events" + ("/" + event_id if event_id else ""),
                api_key=api_key,
                data=data,
                method="PUT" if event_id else "POST",
            )
            action = "updated" if event_id else "created"
            if isinstance(result, dict) and "error" in result:
                error_message = result.get("message", "Unknown error")
                message = f"Error {action} event: {error_message}, data used: {data}"
            elif not result:
                message = f"No events {action} for athlete {athlete_id}."
            elif isinstance(result, dict):
                message = f"Successfully {action} event: {json.dumps(result, indent=2)}"
            else:
                message = f"Event {action} successfully at {start_date}"
        except ValueError as e:
            message = f"Error: {e}"
    return message


@mcp.tool()
async def add_or_update_note(
    name: str,
    description: str,
    start_date: str | None = None,
    color: str | None = "green",
    athlete_id: str | None = None,
    api_key: str | None = None,
    event_id: str | None = None,
) -> str:
    """Add or update a plain text note (category NOTE) on the Intervals.icu calendar.

    Args:
        name: Title of the note
        description: Plain text content of the note
        start_date: Date in YYYY-MM-DD format (optional, defaults to today)
        color: Color of the note (e.g. green, orange, red, blue)
        athlete_id: The Intervals.icu athlete ID (optional)
        api_key: The Intervals.icu API key (optional)
        event_id: The Intervals.icu event ID (optional, for updates)
    """
    if not athlete_id:
        athlete_id = ATHLETE_ID
    if not athlete_id:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")

    try:
        validated_date = validate_date(start_date)
        data = {
            "category": "NOTE",
            "name": name,
            "description": description,
            "start_date_local": validated_date + "T00:00:00",
            "color": color,
        }
        url = f"/athlete/{athlete_id}/events"
        if event_id:
            url += f"/{event_id}"
        result = await make_intervals_request(
            url=url, api_key=api_key, data=data, method="PUT" if event_id else "POST"
        )
        action = "updated" if event_id else "created"
        if isinstance(result, dict) and "error" in result:
            return f"Error {action} note: {result.get('message', 'Unknown error')}"
        if isinstance(result, dict):
            return f"Successfully {action} note: {json.dumps(result, indent=2)}"
        return f"Note {action} successfully at {validated_date}"
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
async def get_athlete(
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> dict | str:
    """Get detailed information for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)

    Returns:
        Dictionary containing comprehensive athlete data including sport settings and custom items
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Call the Intervals.icu API
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}",
        api_key=api_key,
        params={},
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching athlete data: {error_message}"
    if not isinstance(result, dict):
        return {}
    return transform_athlete(result)


@mcp.tool()
async def get_current_date_and_time_info() -> dict[str, Any]:
    """Get current date and time information

    Returns comprehensive information about the current date and time including
    day of week, week number, time details, timezone, and relative day calculations.

    Returns:
        Dictionary containing current date and time information:
        - current_date: ISO format date (YYYY-MM-DD)
        - current_time: 24-hour format time (HH:MM:SS)
        - current_datetime: ISO format datetime (YYYY-MM-DDTHH:MM:SS)
        - current_datetime_with_tz: ISO format datetime with timezone (YYYY-MM-DDTHH:MM:SS±HH:MM)
        - timezone_name: Timezone name (e.g., "UTC", "America/New_York")
        - timezone_offset: UTC offset in format ±HH:MM
        - utc_datetime: UTC datetime (YYYY-MM-DDTHH:MM:SSZ)
        - day_of_week: Full day name (e.g., "Sunday")
        - week_number: ISO week number (1-53)
        - days_until_weekend: Days until Saturday (0-6)
        - is_weekend: Whether today is Saturday or Sunday
        - year: Current year
        - month: Current month (1-12)
        - day: Current day of month (1-31)
        - hour: Current hour (0-23)
        - minute: Current minute (0-59)
        - second: Current second (0-59)
    """
    # Capture the current time once with UTC timezone
    base_time = datetime.now(timezone.utc)
    now_utc = base_time
    now_local = base_time.astimezone()  # Convert to local timezone
    now_with_tz = base_time.astimezone()  # System's timezone-aware datetime

    # Get timezone information
    timezone_name = time.tzname[time.daylight] if time.daylight else time.tzname[0]
    utc_offset_seconds = -time.timezone if not time.daylight else -time.altzone
    utc_offset_hours = utc_offset_seconds // 3600
    utc_offset_minutes = abs(utc_offset_seconds % 3600) // 60
    utc_offset_str = f"{utc_offset_hours:+03d}:{utc_offset_minutes:02d}"

    # Calculate days until weekend (Saturday = 5, Sunday = 6 in weekday())
    # weekday(): Monday=0, Tuesday=1, ..., Sunday=6
    current_weekday = now_local.weekday()  # 0=Monday, 6=Sunday
    days_until_saturday = (5 - current_weekday) % 7  # Saturday is weekday 5

    return {
        "current_date": now_local.strftime("%Y-%m-%d"),
        "current_time": now_local.strftime("%H:%M:%S"),
        "current_datetime": now_local.strftime("%Y-%m-%dT%H:%M:%S"),
        "current_datetime_with_tz": now_with_tz.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "timezone_name": timezone_name,
        "timezone_offset": utc_offset_str,
        "utc_datetime": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "day_of_week": now_local.strftime("%A"),
        "week_number": now_local.isocalendar().week,  # ISO week number
        "days_until_weekend": days_until_saturday,
        "is_weekend": current_weekday in [5, 6],  # Saturday=5, Sunday=6
        "year": now_local.year,
        "month": now_local.month,
        "day": now_local.day,
        "hour": now_local.hour,
        "minute": now_local.minute,
        "second": now_local.second,
    }


@mcp.tool()
async def calculate_date_info(date: str) -> dict[str, Any]:
    """Calculate date information for any given date

    Given a date string, returns comprehensive information about that date
    including day of week, relative position to today, and weekend status.

    Args:
        date: Date in YYYY-MM-DD format (e.g., "2025-06-09")

    Returns:
        Dictionary containing date information:
        - date: The input date in YYYY-MM-DD format
        - day_of_week: Full day name (e.g., "Monday")
        - days_from_today: Number of days from today (negative = past, positive = future)
        - is_weekend: Whether the date is Saturday or Sunday
        - week_number: ISO week number (1-53)
        - year: Year of the date
        - month: Month of the date (1-12)
        - day: Day of month (1-31)
        - is_past: Whether the date is in the past
        - is_future: Whether the date is in the future
        - is_today: Whether the date is today
    """
    try:
        # Parse the input date
        target_date = datetime.strptime(date, "%Y-%m-%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        target_date_normalized = target_date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Calculate days difference
        days_diff = (target_date_normalized - today).days

        # Get weekday (0=Monday, 6=Sunday)
        weekday = target_date.weekday()

        return {
            "date": date,
            "day_of_week": target_date.strftime("%A"),
            "days_from_today": days_diff,
            "is_weekend": weekday in [5, 6],  # Saturday=5, Sunday=6
            "week_number": target_date.isocalendar().week,
            "year": target_date.year,
            "month": target_date.month,
            "day": target_date.day,
            "is_past": days_diff < 0,
            "is_future": days_diff > 0,
            "is_today": days_diff == 0,
        }
    except ValueError as e:
        return {
            "error": True,
            "message": f"Invalid date format. Expected YYYY-MM-DD, got: {date}. Error: {str(e)}",
        }


@mcp.tool()
async def download_workout_zwo(
    event_id: str,
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> str:
    """Download a workout in Zwift (zwo) format from Intervals.icu

    This endpoint retrieves a workout file in Zwift format, which can be imported into Zwift
    or other training platforms that support the ZWO format.

    Args:
        event_id: The Intervals.icu event ID for the workout
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)

    Returns:
        The workout file content in Zwift (zwo) XML format as a string
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Call the Intervals.icu API
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/events/{event_id}/downloadzwo",
        api_key=api_key,
        raw_response=True,
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error downloading workout: {error_message}"

    return result


@mcp.tool()
async def get_power_curves(
    athlete_id: str | None = None,
    api_key: str | None = None,
    curves: str = "42d",
    type_: str = "Ride",
) -> list[dict[str, Any]] | str:
    """Get power curves for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        curves: Comma separated list of curves to return. Default is "1y". Possible values are:
            - 1y (past year)
            - 2y (past 2 years) etc.
            - 42d (past 42 days) etc.
            - s0 (current season)
            - s1 (previous season) etc.
            - all (all time)
            - r.2023-10-01.2023-10-31 (date range)
        type_: The sport (Ride, Run, Swim, etc.)

    Returns:
        List of dictionaries containing power curves for the specified athlete and sport
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Call the Intervals.icu API
    params = {"curves": curves, "type": type_}

    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/power-curves",
        api_key=api_key,
        params=params,
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching power curves: {error_message}"

    return result["list"] if isinstance(result, dict) and "list" in result else []


@mcp.tool()
async def get_activity_power_curves(
    activity_id: str,
    api_key: str | None = None,
    type_: str = "power",
) -> list[dict[str, Any]] | str:
    """Get power curves for a specific activity from Intervals.icu

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        type_: The curve type. Default is "power". Unsure what possible values are.

    Returns:
        List of dictionaries containing power curve data for the specified activity
    """
    # Validate required activity_id
    if not activity_id:
        return "Error: Activity ID is required."

    # Call the Intervals.icu API
    params = {"type": type_}

    result = await make_intervals_request(
        url=f"/activity/{activity_id}/power-curves", api_key=api_key, params=params
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching activity power curve: {error_message}"

    return result if isinstance(result, list) else []


@mcp.tool()
async def get_pace_curves(
    athlete_id: str | None = None,
    api_key: str | None = None,
    curves: str = "42d",
    type_: str = "Run",
) -> list[dict[str, Any]] | str:
    """Get pace curves for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        curves: Comma separated list of curves to return. Default is "1y". Possible values are:
            - 1y (past year)
            - 2y (past 2 years) etc.
            - 42d (past 42 days) etc.
            - s0 (current season)
            - s1 (previous season) etc.
            - all (all time)
            - r.2023-10-01.2023-10-31 (date range)
        type_: The sport (Run, Swim, Rowing, etc.)

    Returns:
        List of dictionaries containing pace curves for the specified athlete and sport
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Call the Intervals.icu API
    params = {"curves": curves, "type": type_}

    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/pace-curves",
        api_key=api_key,
        params=params,
    )

    if isinstance(result, dict) and "error" in result:
        if result.get("status_code") == 404:
            return (
                f"Error: No pace curves available for type '{type_}'. "
                "Intervals.icu only computes pace curves for pace-based sports "
                "such as Run and Swim."
            )
        error_message = result.get("message", "Unknown error")
        return f"Error fetching pace curves: {error_message}"

    return result["list"] if isinstance(result, dict) and "list" in result else []


@mcp.tool()
async def get_activity_pace_curve(
    activity_id: str,
    api_key: str | None = None,
    gap: bool = False,
) -> dict[str, Any] | str:
    """Get activity pace curve in JSON format

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        gap: Boolean indicating whether to use gradient adjusted pace (default: False)

    Returns:
        Dictionary containing pace curve data for the specified activity
    """
    # Validate required activity_id
    if not activity_id:
        return "Error: Activity ID is required."

    # Set up the parameters
    params = {"gap": gap}

    # Call the Intervals.icu API
    result = await make_intervals_request(
        url=f"/activity/{activity_id}/pace-curve.json",
        api_key=api_key,
        params=params,
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching activity pace curve: {error_message}"

    return result if isinstance(result, dict) else {}


@mcp.tool()
async def get_power_hr_curve(
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict | str:
    """Get the athlete's power vs heart rate curve for a date range

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Starting local date (ISO-8601 format, e.g., '2024-01-01')
        end_date: Ending local date (ISO-8601 format, inclusive, e.g., '2024-12-31')

    Returns:
        Dictionary containing power vs heart rate curve data including:
        - athleteId: The athlete ID
        - start/end: Date range
        - minWatts/maxWatts: Power range
        - bucketSize: Watts per bucket
        - bpm: Array of heart rate values
        - cadence: Array of cadence values
        - minutes: Array of time spent at each power/HR combination
        - lthr: Lactate threshold heart rate
        - max_hr: Maximum heart rate
        - ftp: Functional threshold power
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Parse date parameters
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # Call the Intervals.icu API
    params = {"start": start_date, "end": end_date}

    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/power-hr-curve",
        api_key=api_key,
        params=params,
    )

    if isinstance(result, dict) and "error" in result:
        return f"Error fetching power_hr curve: {result.get('message')}"

    return result if isinstance(result, dict) else {}


@mcp.tool()
async def get_activity_power_vs_hr(activity_id: str, api_key: str | None = None) -> dict | str:
    """Get activity power vs heart rate data in JSON format

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)

    Returns:
        Dictionary containing power vs heart rate data for the specified activity including:
        - bucketSize: Watts per bucket for grouping
        - warmup/cooldown: Time periods excluded from analysis
        - elapsedTime: Total activity time
        - hrLag: Heart rate lag in seconds
        - powerHr: Overall power/HR ratio
        - powerHrFirst/powerHrSecond: First/second half ratios
        - decoupling: Cardiac drift percentage
        - powerHrZ2: Power/HR ratio in zone 2
        - medianCadenceZ2/avgCadenceZ2: Cadence metrics for zone 2
        - series: Array of buckets with power, HR, cadence data
        - curves: Fitted curves and trend analysis
    """
    # Validate required activity_id
    if not activity_id:
        return "Error: Activity ID is required."

    # Call the Intervals.icu API
    result = await make_intervals_request(
        url=f"/activity/{activity_id}/power-vs-hr", api_key=api_key
    )

    if isinstance(result, dict) and "error" in result:
        return f"Error fetching activity power vs HR data: {result.get('message')}"

    return result if isinstance(result, dict) else {}


@mcp.tool()
async def get_activity_hr_curve(activity_id: str, api_key: str | None = None) -> dict | str:
    """Get activity heart rate curve in JSON format

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)

    Returns:
        Dictionary containing heart rate curve data for the specified activity including:
        - id: Activity ID
        - filters: Applied filters
        - label: Curve label
        - start_date_local/end_date_local: Activity date
        - secs: Array of durations in seconds
        - values: Array of heart rate values (BPM)
        - activity_id: Array of activity IDs for each point
        - start_index/end_index: Stream indexes for each effort
        - submax_values: Submaximal efforts data
        - And other curve metadata
    """
    # Validate required activity_id
    if not activity_id:
        return "Error: Activity ID is required."

    # Call the Intervals.icu API
    result = await make_intervals_request(
        url=f"/activity/{activity_id}/hr-curve.json", api_key=api_key
    )

    if isinstance(result, dict) and "error" in result:
        return f"Error fetching activity HR curve: {result.get('message')}"

    return result if isinstance(result, dict) else {}


@mcp.tool()
async def get_gear_list(
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> list | str:
    """Get the gear catalog (bikes, shoes, etc.) for an athlete from Intervals.icu.

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
    """
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    result = await make_intervals_request(url=f"/athlete/{athlete_id_to_use}/gear", api_key=api_key)

    if isinstance(result, dict) and "error" in result:
        return f"Error fetching gear: {result.get('message')}"

    if not result or not isinstance(result, list):
        return f"No gear found for athlete {athlete_id_to_use}."

    return result


@mcp.tool()
async def calculate_swim_pace(
    percentage: int,
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> dict | str:
    """Calculate swim pace per 25m at a given percentage of CSS (Critical Swim Speed).

    Fetches the athlete's CSS from their Intervals.icu swim sport settings,
    computes the pace at the requested percentage, and returns it formatted
    as minutes and seconds per 25m.

    Args:
        percentage: Target intensity as a percentage of CSS (e.g. 80 for 80%)
        athlete_id: The Intervals.icu athlete ID (optional)
        api_key: The Intervals.icu API key (optional)
    """
    athlete_id_to_use = (
        athlete_id if athlete_id is not None else _get_intervals_athlete_id() or ATHLETE_ID
    )
    if not athlete_id_to_use:
        return "Error: No athlete ID provided."

    result = await make_intervals_request(url=f"/athlete/{athlete_id_to_use}", api_key=api_key)
    if isinstance(result, dict) and "error" in result:
        return f"Error fetching athlete: {result.get('message')}"

    css_ms = None
    for sport in result.get("sportSettings", []):
        if sport.get("types") and any(t in sport["types"] for t in ["Swim", "OpenWaterSwim"]):
            css_ms = sport.get("threshold_pace")
            break

    if css_ms is None or css_ms <= 0:
        return "Error: No CSS (threshold pace) found in swim sport settings."

    secs_per_100m = 100 / css_ms
    target_secs_per_100m = secs_per_100m / (percentage / 100)
    target_secs_per_25m = target_secs_per_100m / 4

    whole_25 = int(target_secs_per_25m)
    frac_25 = round((target_secs_per_25m - whole_25) * 100)
    if frac_25 >= 100:
        whole_25 += 1
        frac_25 = 0

    css_rounded = round(secs_per_100m)
    target_rounded = round(target_secs_per_100m)

    return {
        "css_per_100m": f"{css_rounded // 60}:{css_rounded % 60:02d}",
        "percentage": percentage,
        "pace_per_25m": (whole_25, frac_25),
        "pace_per_25m_formatted": f"{whole_25}:{frac_25:02d}",
        "pace_per_25m_total_seconds": round(target_secs_per_25m, 2),
        "pace_per_100m": f"{target_rounded // 60}:{target_rounded % 60:02d}",
        "pace_per_100m_total_seconds": round(target_secs_per_100m, 2),
    }


# Run the server
if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        import uvicorn

        host = os.getenv("MCP_HOST", "0.0.0.0")
        port = int(os.getenv("MCP_PORT", "8000"))

        uvicorn.run(build_http_app(), host=host, port=port)
    else:
        mcp.run()
