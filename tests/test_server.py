import sys
import pathlib
import asyncio
import os

sys.path.append(
    str(pathlib.Path(__file__).resolve().parents[1] / "src" / "intervals_mcp_server")
)
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("ATHLETE_ID", "i123456")
from intervals_mcp_server.server import (
    get_activities,
    get_activity_details,
    get_events,
    get_event_by_id,
    get_wellness_data,
    get_activity_intervals,
)


def test_get_activities(monkeypatch):
    sample = {
        "name": "Morning Ride",
        "id": 123,
        "type": "Ride",
        "startTime": "2024-01-01T08:00:00Z",
        "distance": 1000,
        "duration": 3600,
    }

    async def fake_request(*args, **kwargs):
        return [sample]

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_activities(athlete_id="1", limit=1, include_unnamed=True))
    assert "Morning Ride" in result
    assert "Activities:" in result


def test_get_activity_details(monkeypatch):
    sample = {
        "name": "Morning Ride",
        "id": 123,
        "type": "Ride",
        "startTime": "2024-01-01T08:00:00Z",
        "distance": 1000,
        "duration": 3600,
    }

    async def fake_request(*args, **kwargs):
        return sample

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_activity_details(123))
    assert "Activity: Morning Ride" in result


def test_get_events(monkeypatch):
    event = {
        "date": "2024-01-01",
        "id": "e1",
        "name": "Test Event",
        "description": "desc",
        "race": True,
    }

    async def fake_request(*args, **kwargs):
        return [event]

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_events(athlete_id="1", start_date="2024-01-01", end_date="2024-01-02"))
    assert "Test Event" in result
    assert "Events:" in result


def test_get_event_by_id(monkeypatch):
    event = {
        "id": "e1",
        "date": "2024-01-01",
        "name": "Test Event",
        "description": "desc",
        "race": True,
    }

    async def fake_request(*args, **kwargs):
        return event

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_event_by_id("e1", athlete_id="1"))
    assert "Event Details:" in result
    assert "Test Event" in result


def test_get_wellness_data(monkeypatch):
    wellness = {
        "2024-01-01": {
            "id": "w1",
            "date": "2024-01-01",
            "ctl": 75,
            "sleepSecs": 28800,
        }
    }

    async def fake_request(*args, **kwargs):
        return wellness

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_wellness_data(athlete_id="1"))
    assert "Wellness Data:" in result
    assert "2024-01-01" in result


def test_get_activity_intervals(monkeypatch):
    intervals_data = {
        "id": "i1",
        "analyzed": True,
        "icu_intervals": [
            {
                "type": "work",
                "label": "Rep 1",
                "elapsed_time": 60,
                "moving_time": 60,
                "distance": 100,
                "average_watts": 200,
                "max_watts": 300,
                "average_watts_kg": 3.0,
                "max_watts_kg": 5.0,
                "weighted_average_watts": 220,
                "intensity": 0.8,
                "training_load": 10,
                "average_heartrate": 150,
                "max_heartrate": 160,
                "average_cadence": 90,
                "max_cadence": 100,
                "average_speed": 6,
                "max_speed": 8,
            }
        ],
    }

    async def fake_request(*args, **kwargs):
        return intervals_data

    monkeypatch.setattr("intervals_mcp_server.server.make_intervals_request", fake_request)
    result = asyncio.run(get_activity_intervals("123"))
    assert "Intervals Analysis:" in result
    assert "Rep 1" in result
