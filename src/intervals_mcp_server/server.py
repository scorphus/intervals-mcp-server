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
        - get_events
        - get_event_by_id
        - get_wellness_data
        - get_activity_intervals
        - add_events

    See the README for more details on configuration and usage.
"""

from json import JSONDecodeError
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any
import json

import httpx  # pylint: disable=import-error
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error

# Import formatting utilities
from intervals_mcp_server.utils.formatting import (
    format_activity_summary,
    format_event_details,
    format_event_summary,
    format_intervals,
    format_wellness_entry,
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

# Create a single AsyncClient instance for all requests
httpx_client = httpx.AsyncClient()


@asynccontextmanager
async def lifespan(_app: FastMCP):
    """
    Context manager to ensure the shared httpx client is closed when the server stops.

    Args:
        _app (FastMCP): The MCP server application instance.
    """
    try:
        yield
    finally:
        await httpx_client.aclose()


# Initialize FastMCP server with custom lifespan
mcp = FastMCP("intervals-icu", lifespan=lifespan)

# Constants
INTERVALS_API_BASE_URL = os.getenv("INTERVALS_API_BASE_URL", "https://intervals.icu/api/v1")
API_KEY = os.getenv("API_KEY", "")  # Provide default empty string
ATHLETE_ID = os.getenv("ATHLETE_ID", "")  # Default athlete ID from .env
USER_AGENT = "intervalsicu-mcp-server/1.0"

# Validate environment variables on import
if API_KEY == "":
    raise ValueError("API_KEY environment variable is not set or empty")

# Accept athlete IDs that are either all digits or start with 'i' followed by digits
if not re.fullmatch(r"i?\d+", ATHLETE_ID):
    raise ValueError(
        "ATHLETE_ID must be all digits (e.g. 123456) or start with 'i' followed by digits (e.g. i123456)"
    )


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
) -> dict[str, Any] | list[dict[str, Any]]:
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

    if method == "POST":
        headers["Content-Type"] = "application/json"

    # Use provided api_key or fall back to global API_KEY
    key_to_use = api_key if api_key is not None else API_KEY
    auth = httpx.BasicAuth("API_KEY", key_to_use)
    full_url = f"{INTERVALS_API_BASE_URL}{url}"

    try:
        if method == "POST" and data is not None:
            response = await httpx_client.request(
                method=method,
                url=full_url,
                headers=headers,
                params=params,
                auth=auth,
                timeout=30.0,
                content=json.dumps(data),
            )
        else:
            response = await httpx_client.request(
                method=method,
                url=full_url,
                headers=headers,
                params=params,
                auth=auth,
                timeout=30.0,
            )
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


def _format_activities_response(
    activities: list[dict[str, Any]],
    athlete_id: str,
    include_unnamed: bool,
) -> str:
    """Format the activities response based on the results."""
    if not activities:
        if include_unnamed:
            return (
                f"No valid activities found for athlete {athlete_id} in the specified date range."
            )
        return f"No named activities found for athlete {athlete_id} in the specified date range. Try with include_unnamed=True to see all activities."

    # Format the output
    activities_summary = "Activities:\n\n"
    for activity in activities:
        if isinstance(activity, dict):
            activities_summary += format_activity_summary(activity) + "\n"
        else:
            activities_summary += f"Invalid activity format: {activity}\n\n"

    return activities_summary


@mcp.tool()
async def get_activities(  # pylint: disable=too-many-arguments,too-many-return-statements,too-many-branches,too-many-positional-arguments
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 10,
    include_unnamed: bool = False,
) -> str:
    """Get a list of activities for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to 30 days ago)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)
        limit: Maximum number of activities to return (optional, defaults to 10)
        include_unnamed: Whether to include unnamed activities (optional, defaults to False)
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

    return _format_activities_response(activities, athlete_id_to_use, include_unnamed)


@mcp.tool()
async def get_activity_details(activity_id: str, api_key: str | None = None) -> str:
    """Get detailed information for a specific activity from Intervals.icu

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
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

    # Return a more detailed view of the activity
    detailed_view = format_activity_summary(activity_data)

    # Add additional details if available
    if "zones" in activity_data:
        zones = activity_data["zones"]
        detailed_view += "\nPower Zones:\n"
        for zone in zones.get("power", []):
            detailed_view += f"Zone {zone.get('number')}: {zone.get('secondsInZone')} seconds\n"

        detailed_view += "\nHeart Rate Zones:\n"
        for zone in zones.get("hr", []):
            detailed_view += f"Zone {zone.get('number')}: {zone.get('secondsInZone')} seconds\n"

    return detailed_view


@mcp.tool()
async def get_activity_intervals(activity_id: str, api_key: str | None = None) -> str:
    """Get interval data for a specific activity from Intervals.icu

    This endpoint returns detailed metrics for each interval in an activity, including power, heart rate,
    cadence, speed, and environmental data. It also includes grouped intervals if applicable.

    Args:
        activity_id: The Intervals.icu activity ID
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
    """
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

    # Format the intervals data
    return format_intervals(result)


@mcp.tool()
async def get_events(
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Get events for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        end_date: End date in YYYY-MM-DD format (optional, defaults to 30 days from today)
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Parse date parameters
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    # Call the Intervals.icu API
    params = {"oldest": start_date, "newest": end_date}

    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/events", api_key=api_key, params=params
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching events: {error_message}"

    # Format the response
    if not result:
        return f"No events found for athlete {athlete_id_to_use} in the specified date range."

    # Ensure result is a list
    events = result if isinstance(result, list) else []

    if not events:
        return f"No events found for athlete {athlete_id_to_use} in the specified date range."

    events_summary = "Events:\n\n"
    for event in events:
        if not isinstance(event, dict):
            continue

        events_summary += format_event_summary(event) + "\n\n"

    return events_summary


@mcp.tool()
async def get_event_by_id(
    event_id: str,
    athlete_id: str | None = None,
    api_key: str | None = None,
) -> str:
    """Get detailed information for a specific event from Intervals.icu

    Args:
        event_id: The Intervals.icu event ID
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
    """
    # Use provided athlete_id or fall back to global ATHLETE_ID
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
    if not athlete_id_to_use:
        return "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."

    # Call the Intervals.icu API
    result = await make_intervals_request(
        url=f"/athlete/{athlete_id_to_use}/event/{event_id}", api_key=api_key
    )

    if isinstance(result, dict) and "error" in result:
        error_message = result.get("message", "Unknown error")
        return f"Error fetching event details: {error_message}"

    # Format the response
    if not result:
        return f"No details found for event {event_id}."

    if not isinstance(result, dict):
        return f"Invalid event format for event {event_id}."

    return format_event_details(result)


@mcp.tool()
async def get_wellness_data(
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Get wellness data for an athlete from Intervals.icu

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to 30 days ago)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)
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

    wellness_summary = "Wellness Data:\n\n"

    # Handle both list and dictionary responses
    if isinstance(result, dict):
        for date_str, data in result.items():
            # Add the date to the data dictionary if it's not already present
            if isinstance(data, dict) and "date" not in data:
                data["date"] = date_str
            wellness_summary += format_wellness_entry(data) + "\n\n"
    elif isinstance(result, list):
        for entry in result:
            if isinstance(entry, dict):
                wellness_summary += format_wellness_entry(entry) + "\n\n"

    return wellness_summary


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
async def add_events(  # pylint: disable=too-many-arguments,too-many-locals,too-many-branches,too-many-statements,too-many-positional-arguments
    athlete_id: str | None = None,
    api_key: str | None = None,
    start_date: str | None = None,
    name: str | None = None,
    description: str | None = None,
    workout_type: str | None = None,
    moving_time: int | None = None,
    distance: int | None = None,
) -> str:
    """Post events for an athlete to Intervals.icu this follows the event api from intervals.icu as listed
    in https://intervals.icu/api-docs.html#post-/api/v1/athlete/-id-/events

    Example:
    {
        "start_date": "2025-01-14",
        "name": "Run - VO2 Max Intervals",
        "workout_type": "Run",  # Workout type (Ride, Run, Swim, etc.)
        "moving_time": "1800",  # Total expected duration of the workout in seconds
        "distance": "5000",  # Total expected distance of the workout in meters
        "description": "- 15m 80% Warm-up\n- 500m 110% High-intensity interval\n- 90s 80% Recovery\n- 500m 110% High-intensity interval\n- 10m 80% Cool-down"  # Important! See formatting details below
    }

    Common workout types:
        - "Run" for running workouts
        - "Ride" for cycling workouts
        - "Swim" for swimming workouts
        - "Walk" for walking/hiking
        - "Row" for rowing

    Description:
        Description of the workout including steps and target (see details on formatting at https://forum.intervals.icu/t/workout-builder/1163/12)
        Each step is on a line starting with a dash (-) and then the duration/distance, intensity, and description. Sections of steps can be repeated
        by preceding them with a line starting with "Nx" and an optional description, where N is the number of times to repeat the section.
        Other lines can be used to add additional information such as a description of the workout or a note.
        Important: m = minutes, mtr = meters

        Distance: Specify distance using mtr for meters or km for kilometers. For example:
            100mtr
            1km
            10km
        Duration: Specify time using s for seconds, m for minutes, and h for hours or a combination of those. For example:
            30s
            5m
            1h30m10s
        Intensity: Define intensity as:
            Percentage of FTP: 80%
            Absolute power: 200w
            Heart rate: 75% HR or 85% LTHR
            Cadence: 90 rpm
            Pace: 85% Pace
            Zone by power: Z2
            Zone by heart rate: Z2 HR
            Pace zone: Z2 Pace
            Important: FTP only for rides, Pace for all else except rides.
        Ranges: Specify ranges for power, heart rate, or cadence:
            80-90%
            Z2
            Z1-Z2
            100-140w
            70-80% HR
            85-95 rpm
            6:00/km - 6:30/km
        Ramps: Indicate a gradual change in intensity (useful for ERG workouts):
            Ramp 60-80%
            Ramp 100-200w
            Ramp 75-85% Pace
        Repeats: Use Nx (on a separate line!) to repeat a set of steps (all steps immediately following this line), where N is the number of times to repeat the section:
            3x
        Free Ride: Include free to indicate a segment without ERG control, optionally with a suggested power range:
            10m free @ 0.85-0.95
        Comments and Labels: Add descriptive text before the duration to label steps:
            Warmup - 10m @ 60%
        Advanced Options:
            Specify intensity type: intensity=active, intensity=recovery, etc.
            Set power target averaging: power: 1s
        Important: Warmups and cooldowns are usually ramps

    Example of description for interval training (run):
        - 15m 80% Pace Warm-up

        4x repeats of the following:
        - 200mtr 110% Pace High-intensity interval
        - 60s 80% Pace Recovery

        - 8m 80% Pace Cool-down

    Example of description for a cycling workout with no comments:
        - 8m z1
        - 4m ramp z1-z3

        5x
        - 45s 95%
        - 2m15s 65%

        3x
        - 20s 110%
        - 1m40s 65%

        - 8m z1

    Example of description for a swim workout:
        - 25mtr 82-86% Pace Warmup

        10x
        - 100mtr 95% Pace Work
        - 30s 0.0% Pace Rest

        - 25mtr 82-86% Pace Cooldown

    Args:
        athlete_id: The Intervals.icu athlete ID (optional, will use ATHLETE_ID from .env if not provided)
        api_key: The Intervals.icu API key (optional, will use API_KEY from .env if not provided)
        start_date: Start date in YYYY-MM-DD format (optional, defaults to today)
        name: Name of the activity
        description: Description of the activity including steps (IMPORTANT: see details on formatting above, workout steps must follow that format)
        workout_type: Workout type (Run, Ride, Swim, etc.)
        moving_time: Total expected moving time of the workout
        distance: Total expected distance of the workout
    """
    message = None
    athlete_id_to_use = athlete_id if athlete_id is not None else ATHLETE_ID
    if not athlete_id_to_use:
        message = "Error: No athlete ID provided and no default ATHLETE_ID found in environment variables."
    else:
        if not start_date:
            start_date = datetime.now().strftime("%Y-%m-%d")
        try:
            resolved_workout_type = _resolve_workout_type(name, workout_type)
            final_data = {
                "start_date_local": start_date + "T00:00:00",
                "category": "WORKOUT",
                "name": name,
                "description": description,
                "type": resolved_workout_type,
                "moving_time": moving_time,
                "distance": distance,
            }
            result = await make_intervals_request(
                url=f"/athlete/{athlete_id_to_use}/events",
                api_key=api_key,
                data=final_data,
                method="POST",
            )
            if isinstance(result, dict) and "error" in result:
                error_message = result.get("message", "Unknown error")
                message = f"Error posting events: {error_message}, data used: {final_data}"
            elif not result:
                message = f"No events posted for athlete {athlete_id_to_use}."
            elif isinstance(result, dict):
                message = f"Successfully created event: {json.dumps(result, indent=2)}"
            else:
                message = f"Event created successfully at {start_date}"
        except ValueError as e:
            message = f"Error: {e}"
    return message


# Run the server
if __name__ == "__main__":
    mcp.run()
