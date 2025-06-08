"""
Unit tests for the main MCP server tool functions in intervals_mcp_server.server.

These tests use monkeypatching to mock API responses and verify the formatting and output of each tool function:
- get_activities
- get_activity_details
- get_events
- get_event_by_id
- get_wellness_data
- get_activity_intervals

The tests ensure that the server's public API returns expected strings and handles data correctly.
"""

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("API_KEY", "test")
os.environ.setdefault("ATHLETE_ID", "i1")

from intervals_mcp_server.server import (  # pylint: disable=wrong-import-position
    calculate_date_info,
    get_activities,
    get_activity_details,
    get_current_date_info,
    get_events,
    get_event_by_id,
    get_wellness_data,
    get_activity_intervals,
)
from tests.sample_data import INTERVALS_DATA  # pylint: disable=wrong-import-position


def test_get_activities(monkeypatch):
    """
    Test get_activities returns a formatted string containing activity details when given a sample activity.
    """
    sample = {
        "name": "Morning Ride",
        "id": 123,
        "type": "Ride",
        "startTime": "2024-01-01T08:00:00Z",
        "distance": 1000,
        "duration": 3600,
    }

    async def fake_request(*_args, **_kwargs):
        return [sample]

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_activities(athlete_id="1", limit=1, include_unnamed=True))
    assert "Morning Ride" in result
    assert "Activities:" in result


def test_get_activity_details(monkeypatch):
    """
    Test get_activity_details returns a formatted string with the activity name and details.
    """
    sample = {
        "name": "Morning Ride",
        "id": 123,
        "type": "Ride",
        "startTime": "2024-01-01T08:00:00Z",
        "distance": 1000,
        "duration": 3600,
    }

    async def fake_request(*_args, **_kwargs):
        return sample

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_activity_details(123))
    assert "Activity: Morning Ride" in result


def test_get_events(monkeypatch):
    """
    Test get_events returns a formatted string containing event details when given a sample event.
    """
    event = {
        "date": "2024-01-01",
        "id": "e1",
        "name": "Test Event",
        "description": "desc",
        "race": True,
    }

    async def fake_request(*_args, **_kwargs):
        return [event]

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_events(athlete_id="1", start_date="2024-01-01", end_date="2024-01-02"))
    assert "Test Event" in result
    assert "Events:" in result


def test_get_event_by_id(monkeypatch):
    """
    Test get_event_by_id returns a formatted string with event details for a given event ID.
    """
    event = {
        "id": "e1",
        "date": "2024-01-01",
        "name": "Test Event",
        "description": "desc",
        "race": True,
    }

    async def fake_request(*_args, **_kwargs):
        return event

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_event_by_id("e1", athlete_id="1"))
    assert "Event Details:" in result
    assert "Test Event" in result


def test_get_wellness_data(monkeypatch):
    """
    Test get_wellness_data returns a formatted string containing wellness data for a given athlete.
    """
    wellness = {
        "2024-01-01": {
            "id": "w1",
            "date": "2024-01-01",
            "ctl": 75,
            "sleepSecs": 28800,
        }
    }

    async def fake_request(*_args, **_kwargs):
        return wellness

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_wellness_data(athlete_id="1"))
    assert "Wellness Data:" in result
    assert "2024-01-01" in result


def test_get_activity_intervals(monkeypatch):
    """
    Test get_activity_intervals returns a formatted string with interval analysis for a given activity.
    """

    async def fake_request(*_args, **_kwargs):
        return INTERVALS_DATA

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_activity_intervals("123"))
    assert "Intervals Analysis:" in result
    assert "Rep 1" in result


def test_get_current_date_info():
    """
    Test get_current_date_info returns current date and time information
    """
    from datetime import datetime

    result = asyncio.run(get_current_date_info())

    # Verify the structure
    assert isinstance(result, dict)
    assert "current_date" in result
    assert "day_of_week" in result
    assert "week_number" in result
    assert "days_until_weekend" in result
    assert "is_weekend" in result
    assert "year" in result
    assert "month" in result
    assert "day" in result

    # Verify data types and ranges
    assert isinstance(result["current_date"], str)
    assert isinstance(result["day_of_week"], str)
    assert isinstance(result["week_number"], int)
    assert isinstance(result["days_until_weekend"], int)
    assert isinstance(result["is_weekend"], bool)
    assert isinstance(result["year"], int)
    assert isinstance(result["month"], int)
    assert isinstance(result["day"], int)

    # Verify reasonable ranges
    assert 0 <= result["days_until_weekend"] <= 6
    assert 1 <= result["month"] <= 12
    assert 1 <= result["day"] <= 31
    assert result["year"] >= 2025

    # Verify date format
    datetime.strptime(result["current_date"], "%Y-%m-%d")  # Should not raise

    # Verify day of week is valid
    valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    assert result["day_of_week"] in valid_days


def test_calculate_date_info():
    """
    Test calculate_date_info returns correct information for given dates
    """
    from datetime import datetime, timedelta

    # Test with today's date
    today = datetime.now().strftime("%Y-%m-%d")
    result = asyncio.run(calculate_date_info(today))

    assert isinstance(result, dict)
    assert result["date"] == today
    assert result["is_today"] is True
    assert result["is_past"] is False
    assert result["is_future"] is False
    assert result["days_from_today"] == 0

    # Test with future date
    future_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    result = asyncio.run(calculate_date_info(future_date))

    assert result["date"] == future_date
    assert result["is_today"] is False
    assert result["is_past"] is False
    assert result["is_future"] is True
    assert result["days_from_today"] == 5

    # Test with past date
    past_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    result = asyncio.run(calculate_date_info(past_date))

    assert result["date"] == past_date
    assert result["is_today"] is False
    assert result["is_past"] is True
    assert result["is_future"] is False
    assert result["days_from_today"] == -3

    # Test with known weekend date (Saturday June 7, 2025)
    result = asyncio.run(calculate_date_info("2025-06-07"))

    assert result["date"] == "2025-06-07"
    assert result["day_of_week"] == "Saturday"
    assert result["is_weekend"] is True
    assert result["year"] == 2025
    assert result["month"] == 6
    assert result["day"] == 7

    # Test with known weekday (Monday June 9, 2025)
    result = asyncio.run(calculate_date_info("2025-06-09"))

    assert result["date"] == "2025-06-09"
    assert result["day_of_week"] == "Monday"
    assert result["is_weekend"] is False


def test_calculate_date_info_invalid_format():
    """
    Test calculate_date_info handles invalid date formats gracefully
    """
    result = asyncio.run(calculate_date_info("invalid-date"))

    assert "error" in result
    assert result["error"] is True
    assert "Invalid date format" in result["message"]

    # Test other invalid formats
    result = asyncio.run(calculate_date_info("2025/06/09"))
    assert "error" in result
    assert result["error"] is True

    result = asyncio.run(calculate_date_info("June 9, 2025"))
    assert "error" in result
    assert result["error"] is True
