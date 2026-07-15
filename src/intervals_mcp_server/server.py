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
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error

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
    global httpx_client  # noqa: PLW0603
    if httpx_client is None or httpx_client.is_closed:
        httpx_client = httpx.AsyncClient()
    return httpx_client


@asynccontextmanager
async def lifespan(_app: FastMCP):
    """Context manager to close the shared httpx client when the server stops."""
    try:
        yield
    finally:
        if httpx_client and not httpx_client.is_closed:
            await httpx_client.aclose()


# Initialize FastMCP server with custom lifespan
mcp = FastMCP("intervals-icu", lifespan=lifespan)

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

    # Use provided api_key or fall back to global API_KEY
    key_to_use = api_key if api_key is not None else API_KEY
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

    Returns:
        List of activity dictionaries or error message
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
            url=f"/athlete/{athlete_id_to_use}/events/{event.get('id')}", api_key=api_key, method="DELETE"
        )
        if isinstance(result, dict) and "error" in result:
            failed_events.append(event.get('id'))
    return f"Deleted {len(events) - len(failed_events)} events. Failed to delete {len(failed_events)} events: {failed_events}"


@mcp.tool()
async def add_or_update_event( # pylint: disable=locally-disabled, too-many-arguments, too-many-positional-arguments
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
    """Post event for an athlete to Intervals.icu.
    If event_id is provided, the event will be updated instead of created.

    Args:
        workout_type: Workout type (Ride, Run, Swim, Walk, Row, VirtualRide, VirtualRun)
        name: Name of the workout
        description: Workout steps in Intervals.icu native text format (see format guide and examples below)
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        event_id: The Intervals.icu event ID (optional, for updates)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        moving_time: Total expected moving time of the workout in seconds (optional)
        distance: Total expected distance of the workout in meters (optional)

    Description Format Guide:
        Each step is a line starting with a dash (-) followed by duration/distance, intensity, and label.
        Non-step lines (without a dash) are treated as comments/section headers.

        Duration: s=seconds, m=minutes, h=hours (combinable: 1h30m10s)
            30s, 5m, 1h, 1h30m, 4m50s
        Distance: mtr=meters, km=kilometers
            100mtr, 200mtr, 1km, 1.2km, 0.4km
        Power intensity (cycling): percentage of FTP, absolute watts, or zone
            80%, 110%, 50-75%, 200w, 100-140w, Z2, Z4
        Pace intensity (running/swimming): percentage of threshold pace or zone
            80% Pace, 92% Pace, Z2 Pace
        Heart rate: percentage of max HR or LTHR
            75% HR, 85% LTHR, Z2 HR
        Ramps: gradual intensity change
            ramp 50-75%, ramp 80-90% Pace
        Repeats: Nx on its own line, followed by the steps to repeat.
            IMPORTANT: blank line before and after the repeated section.
        Rest: use 0% Pace for swimming wall rest, or duration-only lines
            10s 0% Pace Rest, 30s Rest, 15s intensity=rest Rest

    Example - Cycling Intervals:
        - 5m ramp 50-75%
        - 5m 75%

        5x
        - 5m 85%
        - 5m 65%

        - 5m 75%
        - 5m ramp 75-50%

    Example - Cycling Threshold:
        - 20m ramp 50-75%

        5x
        - 8m 100%
        - 4m 40%

        - 16m 65%

    Example - Cycling Endurance:
        - 10m ramp 50-72%
        - 90m 72%
        - 10m ramp 72-50%

    Example - Running Endurance:
        - 5m 76% Pace Warmup
        - 50m 87% Pace Steady
        - 5m 76% Pace Cooldown

    Example - Running VO2max Intervals:
        - 2km 75% Pace Warm-up

        5x
        - 1km 106% Pace VO2max effort
        - 500mtr 60% Pace Recovery jog

        - 2km 75% Pace Cool down

    Example - Running with Strides:
        - 10m 75% Pace Easy warm-up
        - 35m 82% Pace Steady Z2

        6x
        - 20s 105% Pace Stride
        - 40s 72% Pace Recovery

        - 5m 75% Pace Cool-down

    Example - Swimming Endurance:
        - 0.2km 75% Pace Warmup Freestyle
        - 1.5km 82% Pace Main Set Freestyle
        - 0.2km 75% Pace Cooldown Freestyle

    Example - Swimming Intervals with Rest:
        8x
        - 50mtr 77% Pace
        - 10s 0% Pace Rest

        - 1300mtr 87% Pace

        4x
        - 50mtr 77% Pace
        - 10s 0% Pace Rest

    Example - Swimming Technique Session:
        ## Warmup
        - 400mtr 74% Pace Easy

        8x
        - 50mtr 82% Pace Choice drill
        - 15s intensity=rest Rest

        ## Technique Focus
        5x
        - 100mtr 87% Pace Smooth swim
        - 20s intensity=rest Rest

        ## Cool Down
        - 200mtr 74% Pace Easy choice

    Example - Swimming Ladder:
        - 200mtr 70% Pace Warmup

        1x
        - 400mtr 82% Pace
        - 30s Rest
        - 800mtr 82% Pace
        - 45s Rest
        - 1.2km 82% Pace
        - 1m Rest
        - 800mtr 82% Pace
        - 45s Rest
        - 400mtr 82% Pace

        - 200mtr 65% Pace Cooldown
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
                url=f"/athlete/{athlete_id}/events" +("/"+event_id if event_id else ""),
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
) -> list[dict[str, float]] | str:
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
) -> list[dict[str, float]] | str:
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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
        error_message = result.get("message", "Unknown error")
        return f"Error fetching pace curves: {error_message}"

    return result["list"] if isinstance(result, dict) and "list" in result else []


@mcp.tool()
async def get_activity_pace_curve(
    activity_id: str,
    api_key: str | None = None,
    gap: bool = False,
) -> dict[str, float] | str:
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
        return f"Error fetching activity power curve: {error_message}"

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
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
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
async def get_activity_power_vs_hr(
    activity_id: str, api_key: str | None = None
) -> dict | str:
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
async def get_activity_hr_curve(
    activity_id: str, api_key: str | None = None
) -> dict | str:
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


# Run the server
if __name__ == "__main__":
    mcp.run()
